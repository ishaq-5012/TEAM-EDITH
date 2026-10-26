import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import type { AiDocumentAssist, AiProviderState, AiStatus, InsightsOverview, Me, Permission, Role } from '../lib/types'

export const ALL_PERMISSIONS: Permission[] = [
  'users:manage', 'users:read', 'sessions:manage', 'audit:read', 'applications:read', 'applications:read_all',
  'applications:write', 'documents:upload', 'documents:read', 'rules:read', 'rules:manage', 'rules:publish', 'rules:simulate',
  'validation:run', 'review:resolve', 'system:read', 'exports:create', 'exports:sensitive',
]

/** Mirrors backend ROLE_PERMISSIONS for the roles exercised in UI tests. */
export const ROLE_PERMS: Record<Role, Permission[]> = {
  admin: ['users:manage', 'users:read', 'sessions:manage', 'audit:read', 'system:read',
    'applications:read', 'applications:read_all', 'documents:read', 'rules:read', 'exports:create'],
  compliance_manager: ALL_PERMISSIONS.filter((p) => !['users:manage', 'sessions:manage', 'rules:publish'].includes(p)),
  second_approver: ['rules:read', 'rules:publish', 'rules:simulate', 'applications:read', 'applications:read_all', 'audit:read', 'system:read'],
  reviewer: ['applications:read', 'applications:write', 'documents:upload', 'documents:read', 'rules:read', 'validation:run', 'review:resolve', 'system:read'],
  auditor: ['users:read', 'audit:read', 'applications:read', 'applications:read_all', 'documents:read', 'rules:read', 'system:read', 'exports:create'],
}

export function makeMe(role: Role = 'admin', overrides: Partial<Me> = {}): Me {
  const now = Date.now()
  return {
    id: 'u1',
    email: `${role}@example.com`,
    full_name: 'Ada Example',
    role,
    is_active: true,
    last_login_at: null,
    password_changed_at: null,
    created_at: '2026-01-01T00:00:00Z',
    permissions: ROLE_PERMS[role],
    session: {
      id: 's1',
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + 12 * 3600_000).toISOString(),
      idle_expires_at: new Date(now + 30 * 60_000).toISOString(),
      idle_timeout_minutes: 30,
    },
    ...overrides,
  }
}

export const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status, headers })

export const apiError = (status: number, code: string, message = code) => json(status, { error: { code, message, details: null } })

export const aiProviderOff = (): AiProviderState => ({
  name: 'disabled',
  configured_name: 'disabled',
  enabled: false,
  configured: false,
  model: null,
  detail: 'AI assistance is disabled. All validation features work without it.',
  health: {
    state: 'unknown', calls: 0, failures: 0, consecutive_failures: 0, last_success_at: null, last_error_at: null,
    last_error_code: null, last_check_at: null, last_check_ok: null, last_check_detail: null,
  },
})

/** The server's default: no AI provider, nothing leaves the environment. */
export const aiStatusDisabled = (): AiStatus => ({
  provider: aiProviderOff(),
  egress: { policy: 'none', description: 'Only rule and finding metadata leave this environment.', mask_identifiers: true, max_input_chars: 24000 },
  limits: { timeout_seconds: 30, max_retries: 2, max_output_tokens: 2048, rate_limit_per_minute: 20, user_rate_limit_per_hour: 60 },
  budget: { daily_usd: 5, spent_today_usd: 0, remaining_usd: 5, input_usd_per_mtok: 4, output_usd_per_mtok: 20 },
  tasks: [
    { key: 'explanation', label: 'Plain-language explanations of findings', available: false, reason: 'AI provider is off or not configured; deterministic results are shown.' },
    { key: 'classification', label: 'Document classification suggestions', available: false, reason: 'AI provider is off or not configured; deterministic results are shown.' },
    { key: 'field_suggestions', label: 'Structured field suggestions', available: false, reason: 'AI provider is off or not configured; deterministic results are shown.' },
  ],
  limitations: [],
})

export const aiDocumentAssistOff = (applicationId: string, documentId: string): AiDocumentAssist => ({
  application_id: applicationId,
  document_id: documentId,
  document_name: 'document.pdf',
  fallback: { document_type: null, document_type_source: null, fields: 'Extracted values from the deterministic extractor are in the Extraction Inspector.' },
  provider: aiProviderOff(),
  can_request: false,
  egress_allows_page_text: false,
  tasks: aiStatusDisabled().tasks,
  limitations: [],
  classification: null,
  classification_error: null,
  field_suggestions: null,
  field_suggestions_error: null,
})

/** What the server returns for a scope with no applications: real zeros, no padding. */
export function emptyOverview(over: { applications?: number } = {}): InsightsOverview {
  const days = [{ date: '2026-10-23', count: 0 }]
  return {
    scope: { date_from: '2026-09-24', date_to: '2026-10-23', application_type: null, include_synthetic: true, timezone: 'UTC', applications: over.applications ?? 0, synthetic_applications: 0 },
    generated_at: '2026-10-23T10:00:00Z',
    current: {
      applications: { total: over.applications ?? 0, by_status: {}, synthetic: 0 },
      documents: { total: 0, by_status: {} },
      findings: {
        applications_with_run: 0, applications_without_run: over.applications ?? 0, by_outcome: {}, by_outcome_severity: [],
        engine_failures: 0, review_required: 0, insufficient: 0, not_applicable: 0, rates: { denominator: 0, uncertainty: null, insufficient: null },
      },
      evidence: { by_outcome: {}, by_outcome_severity: [] },
      human: { confirmed: 0, dismissed: 0 },
      review: { backlog: 0, by_status: {}, backlog_by_category: {}, backlog_by_severity: {}, unassigned: 0 },
      extraction: { documents_with_current_run: 0, fields_by_status: {}, pages_by_text_source: {}, pages_by_ocr_status: {}, correction_rate: { corrected: 0, eligible: 0, rate: null } },
    },
    window: {
      applications_created: { total: 0, by_day: days },
      processing: { finished: 0, by_status: {}, failure_rate: null },
      validation: { runs: 0, by_trigger: {}, by_day: [{ date: '2026-10-23', manual: 0, correction: 0 }], cases: { applications: 0, by_outcome: {} } },
      review: { opened: 0, confirmed: 0, dismissed: 0 },
      extraction: { corrections: 0 },
    },
  }
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined

/**
 * Route fetch calls by path. `me` controls /auth/me: a Me object (signed in) or null (401).
 * Extra handlers run first. Returns the spy for call assertions.
 */
export function mockApi({ me, handlers = [] }: { me: Me | null; handlers?: Handler[] }) {
  let current = me
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init = {}) => {
    const url = String(input)
    for (const h of handlers) {
      const r = await h(url, init)
      if (r) return r
    }
    if (url.endsWith('/auth/me')) return current ? json(200, current) : apiError(401, 'unauthorized', 'Not authenticated')
    if (url.endsWith('/auth/login')) {
      current = makeMe('admin')
      return json(200, { user: current, csrf_token: 'csrf-1' })
    }
    if (url.endsWith('/auth/logout')) {
      current = null
      return json(204, undefined)
    }
    if (url.endsWith('/health')) return json(200, { status: 'ok', database: 'ok', version: '0.1.0' })
    if (url.endsWith('/system/capabilities'))
      return json(200, { environment: 'test', version: '0.1.0', ai_provider_configured: 'disabled', ai_provider_active: 'disabled', ai_enabled: false, capabilities: [] })
    if (url.endsWith('/ai/status')) return json(200, aiStatusDisabled())
    if (url.includes('/insights/overview')) return json(200, emptyOverview())
    if (url.endsWith('/insights/definitions')) return json(200, [])
    if (url.endsWith('/audit/actions')) return json(200, [])
    if (url.includes('/audit/verify')) return json(200, { valid: true, checked: 0, first_invalid_seq: null, reason: null, head_hash: null })
    if (url.includes('/audit/events') || url.endsWith('/users') || url.includes('/users?')) return json(200, { items: [], total: 0, limit: 25, offset: 0 })
    if (url.endsWith('/auth/sessions')) return json(200, [])
    if (url.endsWith('/validation-runs')) return json(200, [])
    return apiError(404, 'not_found', 'Not found')
  })
  return spy
}


/** Operates a Dropdown the way a person does: open it, then pick an option by its visible name. */
export async function chooseOption(control: HTMLElement, option: string | RegExp) {
  await userEvent.click(control)
  await userEvent.click(await screen.findByRole('option', { name: option }))
}

/** The visible option names of an open Dropdown. */
export function optionNames(): string[] {
  return within(screen.getByRole('listbox')).getAllByRole('option').map((o) => o.textContent ?? '')
}
