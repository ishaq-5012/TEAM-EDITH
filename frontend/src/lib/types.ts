/**
 * API contracts. These mirror backend Pydantic schemas in backend/app/schemas.
 * Keep in sync: any backend schema change must update this file in the same change.
 */

export type Role = 'admin' | 'compliance_manager' | 'second_approver' | 'reviewer' | 'auditor'

export const ROLES: { value: Role; label: string; description: string }[] = [
  { value: 'admin', label: 'System administrator', description: 'Technical administration and account lifecycle; cannot approve rules' },
  { value: 'compliance_manager', label: 'Compliance manager', description: 'Rules, oversight of all applications, audit' },
  { value: 'second_approver', label: 'Second approver', description: 'Independent rule approval and rejection; cannot author rules' },
  { value: 'reviewer', label: 'Reviewer', description: 'Own and assigned applications, evidence, review' },
  { value: 'auditor', label: 'Auditor (read-only)', description: 'Read-only access to everything, including audit' },
]

export type Permission =
  | 'users:manage'
  | 'users:read'
  | 'sessions:manage'
  | 'audit:read'
  | 'applications:read'
  | 'applications:read_all'
  | 'applications:write'
  | 'documents:upload'
  | 'documents:read'
  | 'rules:read'
  | 'rules:manage'
  | 'rules:publish'
  | 'rules:simulate'
  | 'validation:run'
  | 'review:resolve'
  | 'system:read'
  | 'exports:create'
  | 'exports:sensitive'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Institution {
  id: string
  name: string
  code: string
}

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  last_login_at: string | null
  password_changed_at: string | null
  created_at: string
  /** The tenant this account belongs to. Records of other institutions are never visible. */
  institution?: Institution | null
}

export interface SessionInfo {
  id: string
  created_at: string
  expires_at: string
  idle_expires_at: string
  idle_timeout_minutes: number
}

export interface Me extends User {
  permissions: Permission[]
  session: SessionInfo
}

export interface LoginResponse {
  user: Me
  csrf_token: string
}

export interface SessionOut {
  id: string
  created_at: string
  last_seen_at: string
  expires_at: string
  idle_expires_at: string
  ip_address: string | null
  user_agent: string | null
  current: boolean
}

export interface RevokeResult {
  revoked: number
}

export interface UserCreate {
  email: string
  full_name: string
  role: Role
  password: string
}

export interface UserUpdate {
  full_name?: string
  role?: Role
  is_active?: boolean
  reason: string
}

export interface AuditEvent {
  id: string
  seq: number
  occurred_at: string
  actor_id: string | null
  actor_email: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  outcome: 'success' | 'failure' | string
  summary: string
  data: Record<string, unknown>
  request_id: string | null
  prev_hash: string
  entry_hash: string
}

export interface ChainVerification {
  valid: boolean
  checked: number
  first_invalid_seq: number | null
  reason: string | null
  head_hash: string | null
}

export interface Health {
  status: 'ok' | 'degraded'
  database: 'ok' | 'error'
  version: string
}

export interface Capability {
  key: string
  label: string
  available: boolean
  detail: string
}

export interface Capabilities {
  environment: string
  version: string
  ai_provider_configured: string
  ai_provider_active: string
  ai_enabled: boolean
  capabilities: Capability[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown }
}

// ---------------------------------------------------------------- applications & documents

export type ApplicationStatus = 'draft' | 'processing' | 'needs_review' | 'completed' | 'archived'
export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'needs_review' | 'failed'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type MemberRole = 'contributor' | 'viewer'
export type TransitionAction = 'complete' | 'approve' | 'return' | 'reopen' | 'archive' | 'restore'

export interface UserRef {
  id: string
  full_name: string
  email: string
}

export interface ApplicationSummary {
  id: string
  reference: string
  title: string
  applicant_name: string | null
  application_type: string
  status: ApplicationStatus
  review_stage: 'reviewer' | 'audit' | 'approved'
  owner: UserRef
  document_count: number
  created_at: string
  updated_at: string
  /** Created by the development-only seed-demo command. */
  is_synthetic?: boolean
  institution?: Institution | null
}

export interface ApplicationPermissions {
  can_edit: boolean
  can_upload: boolean
  can_manage_members: boolean
  allowed_actions: TransitionAction[]
}

export interface MemberOut {
  user: UserRef
  role: MemberRole
  created_at: string
}

export interface ApplicationDetail extends ApplicationSummary {
  description: string
  archived_at: string | null
  reviewer_completed_at?: string | null
  audited_at?: string | null
  audit_note?: string | null
  members: MemberOut[]
  document_status_counts: Partial<Record<DocumentStatus, number>>
  permissions: ApplicationPermissions
}

export interface ApplicationList {
  items: ApplicationSummary[]
  total: number
  limit: number
  offset: number
  application_types: string[]
  can_create: boolean
}

export interface ApplicationCreate {
  title: string
  application_type: string
  applicant_name?: string | null
  description?: string
}

export type ApplicationUpdate = Partial<ApplicationCreate>

export type ApplicationSort = 'updated_desc' | 'created_desc' | 'reference_asc' | 'title_asc'

export interface ApplicationListParams {
  status?: ApplicationStatus[]
  q?: string
  application_type?: string
  scope?: 'all' | 'mine'
  sort?: ApplicationSort
  limit?: number
  offset?: number
}

export interface Finding {
  severity: 'info' | 'warning'
  code: string
  message: string
}

export interface JobOut {
  id: string
  kind: string
  status: JobStatus
  attempt: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  result: { facts?: Record<string, unknown>; findings?: Finding[] }
}

export interface DocumentOut {
  id: string
  application_id: string
  original_filename: string
  document_type: string | null
  declared_mime: string | null
  detected_mime: string
  size_bytes: number
  sha256: string
  page_count: number | null
  status: DocumentStatus
  uploaded_by: UserRef
  created_at: string
  updated_at: string
  latest_job: JobOut | null
  can_retry: boolean
}

export interface DocumentDetail extends DocumentOut {
  jobs: JobOut[]
}

export interface UploadLimits {
  max_upload_bytes: number
  max_pdf_pages: number
  max_documents_per_application: number
  accepted: Record<string, string[]>
}

// ---------------------------------------------------------------- extraction (mirrors app/schemas/extraction.py)

export type FieldStatus = 'found' | 'missing' | 'invalid' | 'ambiguous'
export type TextSource = 'text_layer' | 'ocr' | 'none'
export type OcrStatus = 'not_needed' | 'completed' | 'low_confidence' | 'unavailable' | 'failed' | 'skipped_limit'

export interface ExtractionRunOut {
  id: string
  status: 'succeeded' | 'partial'
  is_current: boolean
  extractor: string
  extractor_version: string
  definitions_hash: string
  ocr_engine: string
  input_sha256: string
  idempotency_key: string
  job_id: string | null
  started_at: string
  finished_at: string
  summary: {
    pages?: number
    pages_without_text?: number[]
    pages_needing_attention?: number[]
    fields?: Partial<Record<FieldStatus, number>>
    fields_needing_attention?: string[]
  }
}

export interface PageWarning {
  code: string
  message: string
}

export interface PageOut {
  page_number: number
  width: number
  height: number
  rotation: number
  units: 'pt' | 'px'
  text_source: TextSource
  text_layer_quality: string
  ocr_status: OcrStatus
  ocr_confidence: number | null
  char_count: number
  warnings: PageWarning[]
}

export interface PageTextOut {
  page_number: number
  text_source: TextSource
  raw_text: string
  normalized_text: string
}

export interface CorrectionOut {
  id: string
  value: string
  normalized_value: string
  reason: string
  based_on_value: string | null
  based_on_field_id: string
  actor: UserRef
  created_at: string
}

export interface FieldAlternative {
  raw_value: string
  normalized_value: string | null
  page_number: number
  bbox: [number, number, number, number]
}

export interface FieldOut {
  id: string
  field_key: string
  field_type: 'name' | 'date' | 'identifier' | 'address' | 'document_number'
  label: string
  status: FieldStatus
  raw_value: string | null
  normalized_value: string | null
  normalized_data: Record<string, unknown> | null
  normalization_note: string | null
  method: 'text_layer_rule' | 'ocr_rule' | null
  matched_label: string | null
  page_number: number | null
  bbox: [number, number, number, number] | null
  confidence: number | null
  quality_flags: string[]
  alternatives: FieldAlternative[]
  corrections: CorrectionOut[]
  effective_value: string | null
  effective_source: 'correction' | 'normalized' | 'raw' | 'none'
  correction_based_on_other_value: boolean
}

export interface ExtractionView {
  document_id: string
  document_status: DocumentStatus
  detected_mime: string
  run: ExtractionRunOut
  extractor: { name: string; version: string; kind: 'deterministic_baseline' | 'ai'; limitations: string }
  pages: PageOut[]
  fields: FieldOut[]
  can_correct: boolean
  can_reprocess: boolean
  preview_supported: boolean
}

// ---------------------------------------------------------------- evidence (mirrors app/schemas/evidence.py)

export type Outcome = 'pass' | 'fail' | 'review' | 'insufficient'
export type EvidenceQuality = 'high' | 'medium' | 'low'
export type Severity = 'critical' | 'high' | 'medium' | 'low'

export interface EvidenceReference {
  id: string
  document_id: string
  document_name: string
  extraction_run_id: string | null
  extracted_field_id: string | null
  correction_id: string | null
  field_key: string
  field_label: string
  status: string
  raw_value: string | null
  normalized_value: string | null
  effective_value: string | null
  value_source: 'correction' | 'extracted' | 'none'
  method: string | null
  page_number: number | null
  bbox: [number, number, number, number] | null
  confidence: number | null
  quality_flags: string[]
  evidence_quality: EvidenceQuality
  usable: boolean
  page_width: number | null
  page_height: number | null
}

export interface FieldRelationship {
  id: string
  source_reference_id: string
  target_reference_id: string
  result: Outcome
  method: string
  reason: string
  details: Record<string, unknown>
  evidence_quality: EvidenceQuality | null
  explanation: string
}

export interface PriorityFactor {
  factor: 'severity' | 'outcome' | 'evidence_quality' | 'breadth' | 'impact' | string
  value: unknown
  contribution: number
  max: number
  explanation: string
}

export interface EvidenceFinding {
  id: string
  group_key: string
  group_label: string
  comparator: string
  severity: Severity
  outcome: Outcome
  evidence_quality: EvidenceQuality | null
  priority_score: number
  priority_factors: PriorityFactor[]
  coverage: Record<string, number>
  explanation: string
  references: EvidenceReference[]
  relationships: FieldRelationship[]
}

export interface AnalysisMeta {
  id: string
  is_current: boolean
  comparator_version: string
  config_version: string
  config_hash: string
  input_fingerprint: string
  document_count: number
  summary: Partial<Record<Outcome | 'highest_priority', number>>
  created_at: string
}

export interface EvidenceView {
  application_id: string
  analysis: AnalysisMeta
  stale: boolean
  reused: boolean
  can_analyze: boolean
  findings: EvidenceFinding[]
}

// ---------------------------------------------------------------- rules & validation (mirrors app/schemas/rules.py)

export type RuleOutcome = Outcome | 'not_applicable'
export type RuleVersionStatus = 'draft' | 'pending_approval' | 'published' | 'rejected' | 'retired'
export type ValueType = 'text' | 'date' | 'number' | 'outcome'
export type MissingDataPolicy = 'insufficient' | 'review' | 'fail' | 'pass'
export type LowConfidencePolicy = 'review' | 'insufficient' | 'evaluate'

export type LeafValue = string | number | (string | number)[] | null
export interface LeafNode {
  field: string
  op: string
  value?: LeafValue
  quantifier?: 'all' | 'any'
}
export type ConditionNode = LeafNode | { all: ConditionNode[] } | { any: ConditionNode[] } | { not: ConditionNode }

export interface RuleDefinition {
  condition: ConditionNode
  applies_when?: ConditionNode | null
  severity: Severity
  on_violation: 'fail' | 'review'
  missing_data_policy: MissingDataPolicy
  low_confidence_policy: LowConfidencePolicy
  pass_message?: string
  fail_message?: string
}

export interface CatalogField {
  ref: string
  type: ValueType
  label: string
  source: 'extracted' | 'evidence' | 'application'
  multi: boolean
  field_type?: string
}

/** Expected `value` shape for an operator: nothing, one value, a list, a [from, to] pair, or a whole number. */
export type ValueShape = 'none' | 'scalar' | 'list' | 'pair' | 'int'

export interface RuleCatalog {
  fields: CatalogField[]
  /** Allowlisted operators per value type, with the value shape each expects. */
  operators: Record<ValueType, Record<string, ValueShape>>
  all_operators: string[]
  outcomes: RuleOutcome[]
}

export interface DefinitionSummary {
  condition: string
  applies_when: string
  policies: string
}

export interface RuleVersion {
  id: string
  version_number: number
  status: RuleVersionStatus
  definition: RuleDefinition
  content_hash: string
  effective_from: string
  effective_to: string | null
  source_reference: string
  change_summary: string
  created_by: UserRef
  created_at: string
  submitted_by: UserRef | null
  submitted_at: string | null
  test_summary: { total: number; passed: number; failed: number } | null
  reviewed_by: UserRef | null
  reviewed_at: string | null
  review_note: string | null
  retired_by: UserRef | null
  retired_at: string | null
  retire_reason: string | null
  summary: DefinitionSummary
  in_force_today: boolean
}

export interface RuleTestCase {
  id: string
  name: string
  description: string
  case: Record<string, unknown>
  expected_outcome: RuleOutcome
  created_at: string
}

export interface RuleDetail {
  id: string
  key: string
  name: string
  description: string
  category: string
  owner: UserRef
  created_at: string
  updated_at: string
  /** Newest first. */
  versions: RuleVersion[]
  test_cases: RuleTestCase[]
  disclaimer: string
}

export interface RuleListItem {
  id: string
  key: string
  name: string
  category: string
  owner: UserRef
  in_force_version: number | null
  in_force_severity: Severity | null
  latest_version: number
  latest_status: RuleVersionStatus
  pending_approval: boolean
  has_draft: boolean
}

export interface RuleList {
  items: RuleListItem[]
  can_manage: boolean
  can_publish: boolean
  disclaimer: string
}

export interface RuleCreate {
  key: string
  name: string
  description?: string
  category: string
  owner_id?: string | null
  definition: RuleDefinition
  effective_from: string
  effective_to?: string | null
  source_reference?: string
  change_summary?: string
}

export interface DraftUpdate {
  definition?: RuleDefinition
  effective_from?: string
  effective_to?: string | null
  source_reference?: string
  change_summary?: string
}

export interface DefinitionCheck {
  valid: boolean
  errors: { loc: string; msg: string }[]
  summary: DefinitionSummary | null
}

export interface Observation {
  kind: 'extracted' | 'evidence' | 'application'
  value: string | number
  quality: EvidenceQuality
  satisfied?: boolean
  document_id?: string | null
  document_name?: string | null
  field_key?: string
  field_id?: string | null
  extraction_run_id?: string | null
  correction_id?: string | null
  raw_value?: string | null
  value_source?: string
  page_number?: number | null
  bbox?: number[] | null
  analysis_id?: string | null
  finding_id?: string | null
  group_key?: string
  stale?: boolean
  attribute?: string
}

export interface TraceEntry {
  path: string
  field: string
  op: string
  expected: LeafValue
  quantifier: 'all' | 'any'
  value_type: ValueType
  result: boolean | null
  observations: Observation[]
  low_confidence: boolean
  missing?: boolean
}

export interface TestResult {
  test_case_id: string
  name: string
  expected: RuleOutcome
  actual: RuleOutcome
  passed: boolean
  reason: string
  trace: TraceEntry[]
}

export interface TestRun {
  total: number
  passed: number
  failed: number
  results: TestResult[]
}

export interface VersionComparison {
  from: { id: string; version_number: number; status: RuleVersionStatus; summary: DefinitionSummary }
  to: { id: string; version_number: number; status: RuleVersionStatus; summary: DefinitionSummary }
  changes: { path: string; change: 'added' | 'removed' | 'changed'; before: unknown; after: unknown }[]
}

export interface Proposal {
  rule_id: string
  version_id?: string
  definition?: RuleDefinition
}

export type SimOutcome = RuleOutcome | 'not_in_force'

export interface SimulationRow {
  rule_id: string
  rule_key: string
  rule_name: string
  before: { version: number | null; outcome: SimOutcome; reason: string | null }
  after: { version: number | string | null; outcome: SimOutcome; reason: string | null; trace: TraceEntry[] }
  changed: boolean
}

export interface SimulationResult {
  evaluation_date: string
  side_effects: string
  applications: { application_id: string; reference: string; title: string; changed: number; rules: SimulationRow[] }[]
}

export interface RuleResult {
  id: string
  rule_id: string
  rule_version_id: string
  rule_key: string
  rule_name: string
  version_number: number
  outcome: RuleOutcome
  severity: Severity
  reason: string
  message: string
  low_confidence: boolean
  trace: TraceEntry[]
  details: { would_have_been?: RuleOutcome; missing_fields?: string[] } & Record<string, unknown>
}

export interface RuleVersionRecord {
  rule_id: string
  rule_key: string
  rule_name: string
  version_id: string
  version_number: number
  content_hash: string
  definition: RuleDefinition
  effective_from: string
  effective_to: string | null
  source_reference: string
  owner: string
  approved_by: string | null
  approved_at: string | null
}

export type RunTrigger = 'manual' | 'correction'

export interface ValidationRunSummary {
  id: string
  evaluation_date: string
  summary: Partial<Record<RuleOutcome, number>>
  created_by: UserRef
  created_at: string
  /** The application's latest run when this one was created. */
  previous_run_id: string | null
  trigger: RunTrigger
}

export interface ValidationRun extends ValidationRunSummary {
  application_id: string
  engine_version: string
  input_fingerprint: string
  ruleset_fingerprint: string
  rule_versions: RuleVersionRecord[]
  results: RuleResult[]
  trigger_data: { review_item_id?: string; correction_id?: string; action_id?: string }
  /** Runs created after this one (e.g. revalidations). */
  next_run_ids: string[]
  disclaimer: string
}

export interface Reproduction {
  run_id: string
  snapshot_intact: boolean
  identical: boolean
  differences: { rule_key: string; stored: RuleOutcome | null; recomputed: RuleOutcome }[]
  engine_version: string
  stored_engine_version: string
}

// ---------------------------------------------------------------- review center (mirrors app/schemas/review.py)

export type ReviewStatus = 'open' | 'awaiting_document' | 'escalated' | 'confirmed' | 'dismissed' | 'resolved'
export type ReviewCategory = 'failure' | 'uncertain' | 'missing'
export type ReviewActionType =
  | 'opened'
  | 'assigned'
  | 'unassigned'
  | 'commented'
  | 'escalated'
  | 'document_requested'
  | 'resumed'
  | 'confirmed'
  | 'dismissed'
  | 'reopened'
  | 'field_corrected'
  | 'revalidated'
export type SubmittableAction = Exclude<ReviewActionType, 'opened' | 'field_corrected' | 'revalidated'>

export interface ReviewItem {
  id: string
  application_id: string
  rule_id: string
  rule_key: string
  rule_name: string
  origin_result_id: string
  current_result_id: string
  current_run_id: string
  previous_item_id: string | null
  category: ReviewCategory
  outcome: RuleOutcome
  severity: Severity
  priority: number
  status: ReviewStatus
  assignee: UserRef | null
  document_request: { description: string; requested_by: string; requested_at: string } | null
  closed_by: UserRef | null
  closed_at: string | null
  /** Optimistic-lock version; send it back as expected_version. */
  version: number
  created_at: string
  updated_at: string
}

export interface AppRef {
  id: string
  reference: string
  title: string
  status: ApplicationStatus
}

export interface ReviewQueue {
  items: { item: ReviewItem; application: AppRef }[]
  total: number
  limit: number
  offset: number
  counts: { status: Partial<Record<ReviewStatus, number>>; category: Partial<Record<ReviewCategory, number>>; mine: number }
  can_act_anywhere: boolean
}

export interface ReviewQueueParams {
  status?: string
  category?: ReviewCategory | ''
  assignee?: string
  severity?: Severity | ''
  application_id?: string
  q?: string
  limit?: number
  offset?: number
}

export interface ReviewActionEntry {
  id: string
  sequence: number
  action: ReviewActionType
  actor: UserRef
  from_status: ReviewStatus | null
  to_status: ReviewStatus | null
  reason: string | null
  data: Record<string, unknown>
  request_id: string | null
  created_at: string
}

export interface ReviewField {
  field_id: string
  document_id: string
  document_name: string
  field_key: string
  label: string
  field_type: string
  status: FieldStatus
  raw_value: string | null
  normalized_value: string | null
  method: string | null
  confidence: number | null
  quality_flags: string[]
  page_number: number | null
  bbox: [number, number, number, number] | null
  page_width: number | null
  page_height: number | null
  is_current_extraction: boolean
  in_trace: boolean
  value_at_validation: string | number | null
  effective_value: string | null
  corrections: {
    id: string
    value: string
    normalized_value: string
    based_on_value: string | null
    reason: string
    actor: UserRef
    created_at: string
  }[]
}

export interface ReviewDetail {
  item: ReviewItem
  application: AppRef
  result: {
    id: string
    rule_version_id: string
    version_number: number
    outcome: RuleOutcome
    severity: Severity
    reason: string
    message: string
    low_confidence: boolean
    trace: TraceEntry[]
    details: { would_have_been?: RuleOutcome; missing_fields?: string[] } & Record<string, unknown>
  }
  run: { id: string; evaluation_date: string; created_at: string; trigger: RunTrigger; previous_run_id: string | null }
  rule: Partial<RuleVersionRecord> & { summary: DefinitionSummary | null }
  uncertainty: { code: string; message: string; field?: string; document_id?: string }[]
  fields: ReviewField[]
  evidence: { analysis_id: string | null; findings: EvidenceFinding[] }
  history: ReviewActionEntry[]
  previous_items: { id: string; status: ReviewStatus; outcome: RuleOutcome; created_at: string; closed_at: string | null }[]
  rule_runs: { run_id: string; created_at: string; evaluation_date: string; trigger: RunTrigger; previous_run_id: string | null; outcome: RuleOutcome; result_id: string; version_number: number }[]
  permissions: { can_act: boolean; can_correct: boolean; oversight: boolean; can_decide: boolean }
}

export interface ReviewActionIn {
  action: SubmittableAction
  expected_version: number
  request_id?: string
  reason?: string
  assignee_id?: string
  document_description?: string
}

export interface ReviewCorrectionIn {
  expected_version: number
  request_id?: string
  document_id: string
  field_id: string
  value: string
  reason: string
}

export interface ReviewActionResult {
  item: ReviewItem
  action: ReviewActionEntry
  replayed: boolean
  revalidation: {
    performed: boolean
    reason?: string
    affected_rules: string[]
    run_id?: string
    previous_run_id?: string | null
    summary?: Partial<Record<RuleOutcome, number>>
  } | null
}

// ---------------------------------------------------------------- trust center (mirrors app/schemas/trust.py)

/** Never collapse these: only "verified" may ever be shown as a positive (green) result. */
export type TrustState = 'verified' | 'failed' | 'unsupported' | 'inconclusive'
export type TrustDimension = 'file_integrity' | 'signature_integrity' | 'certificate_trust' | 'revocation' | 'timestamp' | 'external_registry'

export interface TrustCheck {
  dimension: TrustDimension
  key: string
  label: string
  state: TrustState
  code: string
  method: string
  summary: string
  establishes: string
  does_not_establish: string[]
  limitations: string[]
  evidence: Record<string, unknown>
  subject: string | null
  checked_at: string
}

export interface CertInfo {
  subject: string
  issuer: string
  serial_number: string
  not_before: string
  not_after: string
  sha256_fingerprint: string
  self_signed: boolean
}

export interface SignatureDetail {
  field_name: string
  sub_filter: string | null
  signer?: CertInfo
  digest_algorithm?: string
  signer_reported_time?: string | null
  coverage?: string | null
  modification_level?: string | null
  docmdp_ok?: boolean | null
  intact?: boolean
  cryptographically_valid?: boolean
  validation_time?: string | null
  timestamp?: { timestamp: string; tsa: string; intact: boolean; valid: boolean; indication: string | null }
  error?: string
}

export interface TrustVerificationSummary {
  id: string
  recorded_sha256: string
  observed_sha256: string | null
  summary: Partial<Record<TrustDimension, TrustState>>
  created_by: UserRef
  created_at: string
}

export interface TrustVerification extends TrustVerificationSummary {
  application_id: string
  document_id: string
  engine_version: string
  config: {
    trust_anchors: { subject: string; sha256: string; not_after: string }[]
    crls: { issuer: string; next_update: string | null }[]
    problems: string[]
    revocation_fetching: boolean
    registries: { key: string; name: string }[]
    fields_used: string[]
  }
  checks: TrustCheck[]
  signatures: SignatureDetail[]
}

export interface TrustDocRef {
  id: string
  application_id: string
  original_filename: string
  detected_mime: string
  size_bytes: number
  sha256: string
  created_at: string
}

export interface TrustHistory {
  application: AppRef
  document: TrustDocRef
  verifications: TrustVerificationSummary[]
  same_hash_documents: { document_id: string; application_id: string; reference: string; filename: string }[]
  can_verify: boolean
}

export interface TrustOverview {
  items: { document: TrustDocRef; application: AppRef; latest: TrustVerificationSummary | null }[]
  total: number
  limit: number
  offset: number
}

export interface TrustCapabilities {
  engine_version: string
  capabilities: {
    key: string
    label: string
    status: 'enabled' | 'disabled' | 'not_configured' | 'not_implemented'
    requires_external: boolean
    detail: string
  }[]
  trust_material: { trust_anchors: { subject: string; sha256: string; not_after: string }[]; crls: { issuer: string }[]; problems: string[] }
  registries: { key: string; name: string; requires_external: boolean }[]
  statement: string
}

// ---------------------------------------------------------------- AI assistance (Phase 9)

export type AiHealthState = 'unknown' | 'healthy' | 'degraded' | 'failing'
export type AiEgressPolicy = 'none' | 'extracted_values' | 'page_text'
export type AiInteractionStatus = 'succeeded' | 'partial' | 'rejected' | 'failed'

export interface AiProviderState {
  name: string
  configured_name: string
  enabled: boolean
  configured: boolean
  model: string | null
  detail: string
  health: {
    state: AiHealthState
    calls: number
    failures: number
    consecutive_failures: number
    last_success_at: string | null
    last_error_at: string | null
    last_error_code: string | null
    last_check_at: string | null
    last_check_ok: boolean | null
    last_check_detail: string | null
  }
}

export interface AiTaskAvailability {
  key: 'explanation' | 'classification' | 'field_suggestions'
  label: string
  available: boolean
  reason: string
}

export interface AiStatus {
  provider: AiProviderState
  egress: { policy: AiEgressPolicy; description: string; mask_identifiers: boolean; max_input_chars: number }
  limits: { timeout_seconds: number; max_retries: number; max_output_tokens: number; rate_limit_per_minute: number; user_rate_limit_per_hour: number }
  budget: { daily_usd: number; spent_today_usd: number; remaining_usd: number; input_usd_per_mtok: number; output_usd_per_mtok: number }
  tasks: AiTaskAvailability[]
  limitations: string[]
}

export interface AiCheck {
  ok: boolean
  detail: string
  error_code: string | null
  provider: AiProviderState
}

export interface AiError {
  code: string
  message: string
}

/** Where an evidence reference points. Built by the server from stored records, never from model text. */
export type AiEvidenceLink =
  | { type: 'field'; application_id: string; document_id: string | null; page_number: number | null; field_key: string | null }
  | { type: 'rule_result'; application_id: string; run_id: string }
  | { type: 'rule_version'; rule_id: string; version_id: string }
  | { type: 'finding'; application_id: string; finding_id: string }

export interface AiEvidenceRef {
  id: string
  kind: 'rule_result' | 'rule_version' | 'field' | 'correction' | 'finding' | 'evidence_ref' | 'unknown'
  label: string
  link: AiEvidenceLink | null
}

export interface AiStatement {
  text: string
  references: AiEvidenceRef[]
}

export interface AiEgressManifest {
  policy: AiEgressPolicy
  categories: string[]
  documents: string[]
  pages: { document_id: string; page_number: number; chars: number }[]
  masked_values: number
  withheld: string[]
  truncated: boolean
  chars_sent: number
  injection_signals: { where: string; signals: string[] }[]
}

export interface AiInteraction<O = Record<string, unknown>> {
  interaction_id: string
  status: AiInteractionStatus
  error: AiError | null
  output: O | null
  validation: Record<string, unknown>
  provider: string
  model: string | null
  prompt_version: string
  created_at: string
  created_by: { id: string; full_name: string }
  cached: boolean
  stale: boolean
  egress: AiEgressManifest
  usage: { input_tokens: number; output_tokens: number; cost_usd: number; attempts: number; duration_ms: number }
}

export interface AiExplanationOutput {
  statements: AiStatement[]
  limitations: string[]
}

export type AiSubjectType = 'review_item' | 'evidence_finding' | 'application'

export interface AiExplanation {
  subject: { type: AiSubjectType; id: string; application_id: string; application_reference: string }
  /** The deterministic result. Authoritative: AI output never changes it. */
  deterministic: {
    kind: 'rule_result' | 'evidence_finding'
    outcome: string
    severity: string
    reason?: string
    message?: string
    evidence_quality?: string | null
    group_label?: string
    rule?: { rule_id: string; key: string; name: string; version_id: string; version_number: number; source_reference: string | null }
    [key: string]: unknown
  }
  fallback: { statements: AiStatement[] }
  ai: AiInteraction<AiExplanationOutput> | null
  error: AiError | null
  provider: AiProviderState
  can_request: boolean
  limitations: string[]
}

export interface AiClassificationOutput {
  document_type: string
  document_type_label: string
  confidence: 'low' | 'medium' | 'high'
  rationale: string
  evidence_pages: number[]
  declared_type: string | null
  agrees_with_declared: boolean | null
}

export interface AiFieldSuggestion {
  field_key: string
  label: string
  value: string
  normalized_value: string | null
  normalization_status: string
  normalization_note: string | null
  page_number: number
  quoted_text: string
  comparison: 'matches_extraction' | 'differs_from_extraction' | 'not_extracted'
  current_value: string | null
  current_field_id: string | null
  link: Extract<AiEvidenceLink, { type: 'field' }>
}

export interface AiDocumentAssist {
  application_id: string
  document_id: string
  document_name: string
  fallback: { document_type: string | null; document_type_source: string | null; fields: string }
  provider: AiProviderState
  can_request: boolean
  egress_allows_page_text: boolean
  tasks: AiTaskAvailability[]
  limitations: string[]
  classification: AiInteraction<AiClassificationOutput> | null
  classification_error: AiError | null
  field_suggestions: AiInteraction<{ suggestions: AiFieldSuggestion[] }> | null
  field_suggestions_error: AiError | null
}

// ---------------------------------------------------------------- Governance & insights (Phase 10)

export interface MetricDefinition {
  key: string
  label: string
  group: string
  /** "current": state of records now (the window doesn't apply). "window": events inside the selected window. */
  basis: 'current' | 'window'
  definition: string
  source: string
  time_field: string | null
  dedup: string
  unit: 'count' | 'ratio'
}

export interface InsightsScope {
  date_from: string
  date_to: string
  application_type: string | null
  include_synthetic: boolean
  timezone: 'UTC'
}

export interface InsightsParams {
  from?: string
  to?: string
  application_type?: string
  include_synthetic?: boolean
}

export type Counts = Record<string, number>
export interface OutcomeSeverityCell { outcome: string; severity: string; count: number }

export interface InsightsOverview {
  scope: InsightsScope & { applications: number; synthetic_applications: number }
  generated_at: string
  current: {
    applications: { total: number; by_status: Counts; synthetic: number }
    documents: { total: number; by_status: Counts }
    findings: {
      applications_with_run: number
      applications_without_run: number
      by_outcome: Counts
      by_outcome_severity: OutcomeSeverityCell[]
      engine_failures: number
      review_required: number
      insufficient: number
      not_applicable: number
      rates: { denominator: number; uncertainty: number | null; insufficient: number | null }
    }
    evidence: { by_outcome: Counts; by_outcome_severity: OutcomeSeverityCell[] }
    human: { confirmed: number; dismissed: number }
    review: { backlog: number; by_status: Counts; backlog_by_category: Counts; backlog_by_severity: Counts; unassigned: number }
    extraction: {
      documents_with_current_run: number
      fields_by_status: Counts
      pages_by_text_source: Counts
      pages_by_ocr_status: Counts
      correction_rate: { corrected: number; eligible: number; rate: number | null }
    }
  }
  window: {
    applications_created: { total: number; by_day: { date: string; count: number }[] }
    processing: { finished: number; by_status: Counts; failure_rate: number | null }
    validation: {
      runs: number
      by_trigger: Counts
      by_day: { date: string; manual: number; correction: number }[]
      cases: { applications: number; by_outcome: Counts }
    }
    review: { opened: number; confirmed: number; dismissed: number }
    extraction: { corrections: number }
  }
}

export interface FalsePositiveRow {
  rule_id: string
  rule_key: string
  rule_name: string
  confirmed: number
  dismissed: number
  decisions: number
  false_positive_rate: number | null
}

export interface ReviewInsights {
  scope: InsightsScope
  backlog: {
    total: number
    by_status_category: { status: string; category: string; count: number }[]
    by_age: Record<'under_1_day' | '1_to_7_days' | '7_to_30_days' | 'over_30_days', number>
    unassigned: number
  }
  workload: { user_id: string | null; full_name: string | null; email: string | null; count: number; by_severity: Counts }[]
  false_positives: {
    decided_items: number
    confirmed: number
    dismissed: number
    rate: number | null
    reopened_excluded: number
    by_category: Record<string, { confirmed: number; dismissed: number; false_positive_rate: number | null }>
    by_rule: FalsePositiveRow[]
  }
}

export interface RuleVersionUsage {
  rule_id: string
  rule_key: string
  rule_name: string
  version_id: string
  version_number: number
  status: string
  effective_from: string
  effective_to: string | null
  runs: number
  applications: number
  latest_outcomes: Counts
}

export interface RunHistoryItem {
  run_id: string
  application_id: string
  application_reference: string
  created_at: string
  evaluation_date: string
  trigger: string
  previous_run_id: string | null
  summary: Counts
  rule_versions: number
  created_by: string
}

export interface RuleInsights {
  scope: InsightsScope
  version_usage: RuleVersionUsage[]
  runs: { total: number; limit: number; offset: number; items: RunHistoryItem[] }
}

export interface GovernanceEvent {
  rule_id: string
  rule_key: string
  rule_name: string
  version_id: string
  version_number: number
  current_status: string
  content_hash: string
  event: 'created' | 'submitted' | 'approved' | 'rejected' | 'retired'
  at: string
  actor: { id: string; full_name: string; email: string } | null
  detail: string | null
  four_eyes: boolean | null
}

export interface RuleGovernance {
  scope: InsightsScope
  total: number
  limit: number
  offset: number
  counts: Counts
  items: GovernanceEvent[]
  rules: { id: string; key: string; name: string }[]
}

export interface ExportDataset {
  key: string
  label: string
  description: string
  sensitive: boolean
  allowed: boolean
  can_include_document_values: boolean
  requires: string[]
}

export interface ExportRequest extends Omit<InsightsParams, 'from' | 'to'> {
  dataset: string
  format: 'csv' | 'json'
  date_from?: string
  date_to?: string
  include_document_values?: boolean
  reason?: string
  action?: string
  entity_type?: string
}

export interface AuditQuery {
  action?: string
  entity_type?: string
  actor_id?: string
  outcome?: 'success' | 'failure'
  from?: string
  to?: string
  q?: string
  limit?: number
  offset?: number
}
