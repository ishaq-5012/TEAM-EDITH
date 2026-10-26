import type {
  AiCheck,
  AiDocumentAssist,
  AiExplanation,
  AiStatus,
  AiSubjectType,
  ApplicationCreate,
  ApplicationDetail,
  ApplicationList,
  ApplicationListParams,
  ApplicationUpdate,
  AnalysisMeta,
  AuditEvent,
  AuditQuery,
  ExportDataset,
  ExportRequest,
  InsightsOverview,
  InsightsParams,
  MetricDefinition,
  ReviewInsights,
  RuleGovernance,
  RuleInsights,
  CorrectionOut,
  EvidenceView,
  DocumentDetail,
  ExtractionRunOut,
  ExtractionView,
  PageTextOut,
  DocumentOut,
  MemberOut,
  MemberRole,
  TransitionAction,
  UploadLimits,
  Capabilities,
  ChainVerification,
  DefinitionCheck,
  TrustCapabilities,
  TrustHistory,
  TrustOverview,
  TrustVerification,
  ReviewActionIn,
  ReviewActionResult,
  ReviewCorrectionIn,
  ReviewDetail,
  ReviewQueue,
  ReviewQueueParams,
  DraftUpdate,
  Proposal,
  Reproduction,
  RuleCatalog,
  RuleCreate,
  RuleDefinition,
  RuleDetail,
  RuleList,
  RuleOutcome,
  RuleTestCase,
  SimulationResult,
  TestRun,
  ValidationRun,
  ValidationRunSummary,
  VersionComparison,
  Health,
  LoginResponse,
  Me,
  Page,
  RevokeResult,
  SessionOut,
  User,
  UserCreate,
  UserRef,
  UserUpdate,
} from './types'

const BASE = '/api/v1'
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/**
 * Authentication is an HttpOnly session cookie that this code can never read. The only
 * client-side secret is the CSRF token: it's readable by design and is echoed back in a
 * header on state-changing requests (the server checks it against the session).
 */
export function readCsrfToken(): string | null {
  for (const part of document.cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=')
    if (name === '__Host-vf_csrf' || name === 'vf_csrf') return decodeURIComponent(rest.join('='))
  }
  return null
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }

  /** Field-level messages from a 422 validation error, keyed by field name. */
  fieldErrors(): Record<string, string> {
    if (!Array.isArray(this.details)) return {}
    const out: Record<string, string> = {}
    for (const d of this.details as { loc?: unknown; msg?: string }[]) {
      // Request validation errors carry a path list; domain errors (e.g. rule checks) use other shapes.
      if (!Array.isArray(d.loc)) continue
      const field = d.loc[d.loc.length - 1]
      if (typeof field === 'string' && d.msg) out[field] = d.msg.replace(/^Value error, /, '')
    }
    return out
  }
}

type Listener<T = void> = (value: T) => void
const unauthorizedListeners = new Set<Listener<ApiError>>()
const expiryListeners = new Set<Listener<string>>()

/** Called whenever the server answers 401 (no session, or the session ended). */
export const onUnauthorized = (fn: Listener<ApiError>) => {
  unauthorizedListeners.add(fn)
  return () => {
    unauthorizedListeners.delete(fn)
  }
}

/** Called with the session's current expiry (ISO) after every authenticated response. */
export const onSessionExpiry = (fn: Listener<string>) => {
  expiryListeners.add(fn)
  return () => {
    expiryListeners.delete(fn)
  }
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const fields = Object.entries(err.fieldErrors())
    if (err.code === 'validation_error' && fields.length) return fields.map(([f, m]) => `${f.replace(/_/g, ' ')}: ${m}`).join('; ')
    return err.message
  }
  if (err instanceof Error) return err.message
  return 'Something went wrong.'
}

async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const method = (init.method ?? 'GET').toUpperCase()
  if (UNSAFE.has(method)) {
    const csrf = readCsrfToken()
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  let body = init.body
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { ...init, method, headers, body, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the VerifyFlow server. Check that the backend is running.')
  }

  const expires = res.headers.get('X-Session-Expires')
  if (expires) expiryListeners.forEach((fn) => fn(expires))

  if (res.status === 204) return undefined as T

  const text = await res.text()
  let parsed: unknown = undefined
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      throw new ApiError(res.status, 'bad_response', `Unexpected response from server (HTTP ${res.status})`)
    }
  }

  if (!res.ok) throw toApiError(res.status, parsed, path)
  return parsed as T
}

function toApiError(status: number, parsed: unknown, path: string): ApiError {
  const err = (parsed as { error?: { code: string; message: string; details: unknown } } | undefined)?.error
  const apiErr = new ApiError(status, err?.code ?? 'http_error', err?.message ?? `Request failed (HTTP ${status})`, err?.details)
  if (status === 401 && path !== '/auth/login') unauthorizedListeners.forEach((fn) => fn(apiErr))
  return apiErr
}

const qsArray = (params: Record<string, string | number | string[] | undefined | null>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => s.append(k, x))
    else if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  }
  const str = s.toString()
  return str ? `?${str}` : ''
}

export interface UploadHandle {
  promise: Promise<DocumentOut>
  abort: () => void
}

/**
 * Multipart upload with real progress events (fetch cannot report upload progress).
 * `onProgress(sent, total)` reflects bytes actually transmitted. Server-side validation
 * happens after the last byte and before the response arrives.
 */
export function uploadDocument(
  applicationId: string,
  file: File,
  documentType: string | null,
  onProgress: (sent: number, total: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest()
  const path = `/applications/${encodeURIComponent(applicationId)}/documents`
  const promise = new Promise<DocumentOut>((resolve, reject) => {
    xhr.open('POST', `${BASE}${path}`)
    const csrf = readCsrfToken()
    if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total)
    }
    xhr.onload = () => {
      const expires = xhr.getResponseHeader('X-Session-Expires')
      if (expires) expiryListeners.forEach((fn) => fn(expires))
      let parsed: unknown
      try {
        parsed = xhr.responseText ? JSON.parse(xhr.responseText) : undefined
      } catch {
        reject(new ApiError(xhr.status, 'bad_response', `Unexpected response from server (HTTP ${xhr.status})`))
        return
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(parsed as DocumentOut)
      else reject(toApiError(xhr.status, parsed, path))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'The upload was interrupted. Check your connection and retry.'))
    xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload cancelled'))
    const form = new FormData()
    form.append('file', file, file.name)
    if (documentType) form.append('document_type', documentType)
    xhr.send(form)
  })
  return { promise, abort: () => xhr.abort() }
}

const docPath = (applicationId: string, documentId: string) =>
  `/applications/${encodeURIComponent(applicationId)}/documents/${encodeURIComponent(documentId)}`

/** Server-rendered PNG of a page as displayed (the coordinate space of extracted field boxes). */
export async function fetchPageImage(applicationId: string, documentId: string, page: number, scale = 1.5): Promise<Blob> {
  const path = `${docPath(applicationId, documentId)}/pages/${page}/image?scale=${scale}`
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the VerifyFlow server.')
  }
  if (!res.ok) {
    let parsed: unknown
    try {
      parsed = await res.json()
    } catch {
      parsed = undefined
    }
    throw toApiError(res.status, parsed, path)
  }
  return res.blob()
}

export interface ExportDownload {
  blob: Blob
  filename: string
  rows: number
  truncated: boolean
}

/** Build an export on the server (audited there) and return the file. POST so it carries the CSRF token. */
export async function downloadExport(body: ExportRequest): Promise<ExportDownload> {
  const path = '/exports'
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const csrf = readCsrfToken()
  if (csrf) headers.set('X-CSRF-Token', csrf)
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: JSON.stringify(body), credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the VerifyFlow server.')
  }
  if (!res.ok) {
    let parsed: unknown
    try {
      parsed = await res.json()
    } catch {
      parsed = undefined
    }
    throw toApiError(res.status, parsed, path)
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `verifyflow-${body.dataset}.${body.format}`
  return {
    blob: await res.blob(),
    filename,
    rows: Number(res.headers.get('X-Export-Rows') ?? 0),
    truncated: res.headers.get('X-Export-Truncated') === 'true',
  }
}

/** Fetch a document's bytes for in-app preview/download. Never exposes a durable URL. */
export async function fetchDocumentBlob(applicationId: string, documentId: string): Promise<Blob> {
  const path = `/applications/${encodeURIComponent(applicationId)}/documents/${encodeURIComponent(documentId)}/content`
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the VerifyFlow server.')
  }
  if (!res.ok) {
    let parsed: unknown
    try {
      parsed = await res.json()
    } catch {
      parsed = undefined
    }
    throw toApiError(res.status, parsed, path)
  }
  return res.blob()
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

const rulePath = (id: string) => `/rules/${encodeURIComponent(id)}`
const versionPath = (id: string, versionId: string) => `${rulePath(id)}/versions/${encodeURIComponent(versionId)}`
const runsPath = (appId: string) => `/applications/${encodeURIComponent(appId)}/validation-runs`

export const api = {
  health: () => request<Health>('/health'),
  capabilities: () => request<Capabilities>('/system/capabilities'),

  login: (email: string, password: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', json: { email, password } }),
  evaluatorCredentials: () => request<{ accounts: { role: string; label: string; email: string; password: string }[] }>('/auth/evaluator-credentials'),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  me: () => request<Me>('/auth/me'),
  mySessions: () => request<SessionOut[]>('/auth/sessions'),
  revokeSession: (id: string) => request<void>(`/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  revokeOtherSessions: () => request<RevokeResult>('/auth/sessions/revoke-others', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>('/auth/change-password', { method: 'POST', json: { current_password, new_password } }),

  listUsers: (p: { limit?: number; offset?: number } = {}) => request<Page<User>>(`/users${qs(p)}`),
  createUser: (body: UserCreate) => request<User>('/users', { method: 'POST', json: body }),
  updateUser: (id: string, body: UserUpdate) => request<User>(`/users/${encodeURIComponent(id)}`, { method: 'PATCH', json: body }),
  resetPassword: (id: string, new_password: string, reason: string) =>
    request<void>(`/users/${encodeURIComponent(id)}/reset-password`, { method: 'POST', json: { new_password, reason } }),
  userSessions: (id: string) => request<SessionOut[]>(`/users/${encodeURIComponent(id)}/sessions`),
  revokeUserSessions: (id: string, reason: string) =>
    request<RevokeResult>(`/users/${encodeURIComponent(id)}/revoke-sessions`, { method: 'POST', json: { reason } }),

  applications: (p: ApplicationListParams = {}) =>
    request<ApplicationList>(`/applications${qsArray({ ...p })}`),
  createApplication: (body: ApplicationCreate) => request<ApplicationDetail>('/applications', { method: 'POST', json: body }),
  application: (id: string) => request<ApplicationDetail>(`/applications/${encodeURIComponent(id)}`),
  updateApplication: (id: string, body: ApplicationUpdate) =>
    request<ApplicationDetail>(`/applications/${encodeURIComponent(id)}`, { method: 'PATCH', json: body }),
  transitionApplication: (id: string, action: TransitionAction, reason: string) =>
    request<ApplicationDetail>(`/applications/${encodeURIComponent(id)}/transitions`, { method: 'POST', json: { action, reason } }),
  addMember: (id: string, email: string, role: MemberRole) =>
    request<MemberOut>(`/applications/${encodeURIComponent(id)}/members`, { method: 'POST', json: { email, role } }),
  removeMember: (id: string, userId: string) =>
    request<void>(`/applications/${encodeURIComponent(id)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
  uploadLimits: () => request<UploadLimits>('/applications/upload-limits'),
  documents: (id: string) => request<DocumentOut[]>(`/applications/${encodeURIComponent(id)}/documents`),
  document: (id: string, docId: string) =>
    request<DocumentDetail>(`/applications/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}`),
  evidence: (id: string) => request<EvidenceView>(`/applications/${encodeURIComponent(id)}/evidence`),
  evidenceAnalysis: (id: string, analysisId: string) =>
    request<EvidenceView>(`/applications/${encodeURIComponent(id)}/evidence/analyses/${encodeURIComponent(analysisId)}`),
  evidenceAnalyses: (id: string) => request<AnalysisMeta[]>(`/applications/${encodeURIComponent(id)}/evidence/analyses`),
  runEvidenceAnalysis: (id: string, force: boolean) =>
    request<EvidenceView>(`/applications/${encodeURIComponent(id)}/evidence/analyses`, { method: 'POST', json: { force } }),
  extraction: (id: string, docId: string) => request<ExtractionView>(`${docPath(id, docId)}/extraction`),
  extractionRuns: (id: string, docId: string) => request<ExtractionRunOut[]>(`${docPath(id, docId)}/extraction/runs`),
  pageText: (id: string, docId: string, page: number) => request<PageTextOut>(`${docPath(id, docId)}/pages/${page}/text`),
  reprocessDocument: (id: string, docId: string, force: boolean) =>
    request<DocumentOut>(`${docPath(id, docId)}/reprocess`, { method: 'POST', json: { force } }),
  correctField: (id: string, docId: string, fieldId: string, value: string, reason: string) =>
    request<CorrectionOut>(`${docPath(id, docId)}/extraction/fields/${encodeURIComponent(fieldId)}/corrections`, {
      method: 'POST',
      json: { value, reason },
    }),
  retryDocument: (id: string, docId: string) =>
    request<DocumentOut>(`/applications/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}/retry`, { method: 'POST' }),

  rules: () => request<RuleList>('/rules'),
  ruleCatalog: () => request<RuleCatalog>('/rules/catalog'),
  /** Schema-validate and summarise a definition. Writes nothing. */
  validateDefinition: (definition: unknown) => request<DefinitionCheck>('/rules/validate', { method: 'POST', json: { definition } }),
  createRule: (body: RuleCreate) => request<RuleDetail>('/rules', { method: 'POST', json: body }),
  rule: (id: string) => request<RuleDetail>(rulePath(id)),
  updateRule: (id: string, body: { name?: string; description?: string; category?: string; owner_id?: string }) =>
    request<RuleDetail>(rulePath(id), { method: 'PATCH', json: body }),
  newRuleVersion: (id: string, fromVersionId?: string) =>
    request<RuleDetail>(`${rulePath(id)}/versions`, { method: 'POST', json: { from_version_id: fromVersionId ?? null } }),
  updateDraft: (id: string, versionId: string, body: DraftUpdate) =>
    request<RuleDetail>(versionPath(id, versionId), { method: 'PATCH', json: body }),
  submitVersion: (id: string, versionId: string) => request<RuleDetail>(`${versionPath(id, versionId)}/submit`, { method: 'POST' }),
  approveVersion: (id: string, versionId: string, note: string) =>
    request<RuleDetail>(`${versionPath(id, versionId)}/approve`, { method: 'POST', json: { note } }),
  rejectVersion: (id: string, versionId: string, note: string) =>
    request<RuleDetail>(`${versionPath(id, versionId)}/reject`, { method: 'POST', json: { note } }),
  retireVersion: (id: string, versionId: string, reason: string) =>
    request<RuleDetail>(`${versionPath(id, versionId)}/retire`, { method: 'POST', json: { reason } }),
  compareVersions: (id: string, from: string, to: string) => request<VersionComparison>(`${rulePath(id)}/compare${qs({ from, to })}`),
  addTestCase: (id: string, body: { name: string; description?: string; case: unknown; expected_outcome: RuleOutcome }) =>
    request<RuleTestCase>(`${rulePath(id)}/test-cases`, { method: 'POST', json: body }),
  deleteTestCase: (id: string, caseId: string) =>
    request<void>(`${rulePath(id)}/test-cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' }),
  testVersion: (id: string, versionId: string) => request<TestRun>(`${versionPath(id, versionId)}/test`, { method: 'POST' }),
  /** Run the rule's synthetic cases against an unsaved definition. Writes nothing. */
  testDefinition: (id: string, definition: RuleDefinition) =>
    request<TestRun>(`${rulePath(id)}/test-definition`, { method: 'POST', json: { definition } }),
  /** What-if: read-only on the server; no rules, versions or runs are created or modified. */
  simulate: (body: { proposals: Proposal[]; application_ids?: string[]; evaluation_date?: string | null }) =>
    request<SimulationResult>('/rules/simulate', { method: 'POST', json: body }),

  validationRuns: (appId: string) => request<ValidationRunSummary[]>(runsPath(appId)),
  validationRun: (appId: string, runId: string) => request<ValidationRun>(`${runsPath(appId)}/${encodeURIComponent(runId)}`),
  runValidation: (appId: string, evaluationDate?: string | null) =>
    request<ValidationRun>(runsPath(appId), { method: 'POST', json: { evaluation_date: evaluationDate || null } }),
  reproduceRun: (appId: string, runId: string) => request<Reproduction>(`${runsPath(appId)}/${encodeURIComponent(runId)}/reproduction`),

  reviews: (p: ReviewQueueParams = {}) => request<ReviewQueue>(`/reviews${qs({ ...p })}`),
  review: (id: string) => request<ReviewDetail>(`/reviews/${encodeURIComponent(id)}`),
  reviewAssignees: (id: string) => request<UserRef[]>(`/reviews/${encodeURIComponent(id)}/assignees`),
  /** Versioned and idempotent: send expected_version and a request_id reused across retries. */
  reviewAction: (id: string, body: ReviewActionIn) =>
    request<ReviewActionResult>(`/reviews/${encodeURIComponent(id)}/actions`, { method: 'POST', json: body }),
  reviewCorrection: (id: string, body: ReviewCorrectionIn) =>
    request<ReviewActionResult>(`/reviews/${encodeURIComponent(id)}/corrections`, { method: 'POST', json: body }),

  trustCapabilities: () => request<TrustCapabilities>('/trust/capabilities'),
  trustDocuments: (p: { application_id?: string; limit?: number; offset?: number } = {}) => request<TrustOverview>(`/trust/documents${qs(p)}`),
  trustHistory: (appId: string, docId: string) => request<TrustHistory>(`${docPath(appId, docId)}/verifications`),
  trustVerification: (appId: string, docId: string, id: string) =>
    request<TrustVerification>(`${docPath(appId, docId)}/verifications/${encodeURIComponent(id)}`),
  /** Runs every configured check and stores an immutable record. */
  verifyDocument: (appId: string, docId: string) => request<TrustVerification>(`${docPath(appId, docId)}/verifications`, { method: 'POST' }),

  /** AI assistance (advisory). Every endpoint answers with the deterministic fallback when AI is off or fails. */
  aiStatus: () => request<AiStatus>('/ai/status'),
  /** Reachability and credentials check (admin). Spends no tokens. */
  aiCheck: () => request<AiCheck>('/ai/status/check', { method: 'POST' }),
  aiExplanation: (subjectType: AiSubjectType, subjectId: string) =>
    request<AiExplanation>(`/ai/explanations${qs({ subject_type: subjectType, subject_id: subjectId })}`),
  requestAiExplanation: (subjectType: AiSubjectType, subjectId: string, refresh = false) =>
    request<AiExplanation>('/ai/explanations', { method: 'POST', json: { subject_type: subjectType, subject_id: subjectId, refresh } }),
  aiDocumentAssist: (appId: string, docId: string) => request<AiDocumentAssist>(`/ai${docPath(appId, docId)}`),
  requestAiClassification: (appId: string, docId: string, refresh = false) =>
    request<AiDocumentAssist>(`/ai${docPath(appId, docId)}/classification`, { method: 'POST', json: { refresh } }),
  requestAiFieldSuggestions: (appId: string, docId: string, refresh = false) =>
    request<AiDocumentAssist>(`/ai${docPath(appId, docId)}/field-suggestions`, { method: 'POST', json: { refresh } }),

  /** Governance & insights. All aggregates are scoped server-side to applications the user can see. */
  metricDefinitions: () => request<MetricDefinition[]>('/insights/definitions'),
  insightsOverview: (p: InsightsParams = {}) => request<InsightsOverview>(`/insights/overview${qs({ ...p, include_synthetic: p.include_synthetic === false ? 'false' : undefined })}`),
  reviewInsights: (p: InsightsParams = {}) => request<ReviewInsights>(`/insights/review${qs({ ...p, include_synthetic: p.include_synthetic === false ? 'false' : undefined })}`),
  ruleInsights: (p: InsightsParams & { limit?: number; offset?: number } = {}) =>
    request<RuleInsights>(`/insights/rules${qs({ ...p, include_synthetic: p.include_synthetic === false ? 'false' : undefined })}`),
  ruleGovernance: (p: { from?: string; to?: string; rule_id?: string; limit?: number; offset?: number } = {}) =>
    request<RuleGovernance>(`/insights/rule-governance${qs(p)}`),
  exportDatasets: () => request<ExportDataset[]>('/exports/datasets'),
  auditActions: () => request<string[]>('/audit/actions'),

  auditEvents: (p: AuditQuery = {}) =>
    request<Page<AuditEvent>>(`/audit/events${qs({ ...p })}`),
  verifyAudit: () => request<ChainVerification>('/audit/verify'),
}
