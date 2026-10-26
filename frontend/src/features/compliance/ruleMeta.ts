import type { Status } from '../../components/ui/StatusPill'
import type {
  CatalogField,
  ConditionNode,
  LeafNode,
  LeafValue,
  LowConfidencePolicy,
  MissingDataPolicy,
  RuleCatalog,
  RuleDefinition,
  RuleVersionStatus,
  SimOutcome,
  ValueShape,
} from '../../lib/types'

export const VERSION_STATUS: Record<RuleVersionStatus, { label: string; pill: Status; hint: string }> = {
  draft: { label: 'Draft', pill: 'info', hint: 'Editable. Not evaluated against applications.' },
  pending_approval: { label: 'Pending approval', pill: 'review', hint: 'Frozen. Awaiting review by a second person with publish rights.' },
  published: { label: 'Published', pill: 'pass', hint: 'Approved. Evaluated on dates inside its effective window.' },
  rejected: { label: 'Rejected', pill: 'fail', hint: 'Not approved. Kept for history; create a new version to try again.' },
  retired: { label: 'Retired', pill: 'missing', hint: 'Withdrawn. No longer evaluated; kept for reproducibility.' },
}

/** Rule outcomes. These describe what a configured rule produced, never a legal determination. */
export const RULE_OUTCOME: Record<SimOutcome, { label: string; pill: Status }> = {
  pass: { label: 'Rule passed', pill: 'pass' },
  fail: { label: 'Rule failed', pill: 'fail' },
  review: { label: 'Needs review', pill: 'review' },
  insufficient: { label: 'Insufficient data', pill: 'missing' },
  not_applicable: { label: 'Not applicable', pill: 'unknown' },
  not_in_force: { label: 'Not in force', pill: 'unknown' },
}

export const RESULT_REASON: Record<string, string> = {
  condition_met: 'Condition met',
  condition_not_met: 'Condition not met',
  missing_data: 'Required data missing',
  low_confidence_input: 'Low-confidence input',
  not_applicable: 'Applicability condition not met',
}

/** Mirrors backend app/rules/summary.py OP_TEXT so the editor reads like the stored summaries. */
export const OP_LABEL: Record<string, string> = {
  eq: 'is',
  ne: 'is not',
  in: 'is one of',
  not_in: 'is not one of',
  contains: 'contains',
  starts_with: 'starts with',
  ends_with: 'ends with',
  exists: 'is present',
  not_exists: 'is absent',
  before: 'is before',
  after: 'is after',
  on_or_before: 'is on or before',
  on_or_after: 'is on or after',
  between: 'is between',
  gt: 'is greater than',
  gte: 'is at least',
  lt: 'is less than',
  lte: 'is at most',
  before_evaluation_date: 'is before the evaluation date (± days)',
  after_evaluation_date: 'is after the evaluation date (± days)',
  age_years_at_least: 'is at least N years before the evaluation date',
  age_years_at_most: 'is at most N years before the evaluation date',
}

export const MISSING_POLICY: Record<MissingDataPolicy, string> = {
  insufficient: 'Mark as insufficient data',
  review: 'Send to human review',
  fail: 'Treat as a violation',
  pass: 'Treat as passed',
}

export const LOW_CONFIDENCE_POLICY: Record<LowConfidencePolicy, string> = {
  review: 'Send to human review',
  insufficient: 'Mark as insufficient data',
  evaluate: 'Evaluate anyway',
}

export const DEFAULT_DEFINITION: RuleDefinition = {
  condition: { field: 'extracted.full_name', op: 'exists' },
  applies_when: null,
  severity: 'medium',
  on_violation: 'fail',
  missing_data_policy: 'insufficient',
  low_confidence_policy: 'review',
  pass_message: '',
  fail_message: '',
}

export const isLeaf = (n: ConditionNode): n is LeafNode => 'field' in n
export const groupKind = (n: ConditionNode): 'all' | 'any' | 'not' | 'leaf' =>
  isLeaf(n) ? 'leaf' : 'all' in n ? 'all' : 'any' in n ? 'any' : 'not'

export function fieldOf(catalog: RuleCatalog, ref: string): CatalogField | undefined {
  return catalog.fields.find((f) => f.ref === ref)
}

export function shapeOf(catalog: RuleCatalog, leaf: LeafNode): ValueShape | undefined {
  const f = fieldOf(catalog, leaf.field)
  return f ? catalog.operators[f.type]?.[leaf.op] : undefined
}

/** A sensible starting value when the operator (and so the value shape) changes. */
export function defaultValue(shape: ValueShape | undefined, type: string | undefined): LeafValue | undefined {
  switch (shape) {
    case 'none':
      return undefined
    case 'int':
      return type === 'date' ? 18 : 0
    case 'list':
      return type === 'outcome' ? ['pass'] : []
    case 'pair':
      return type === 'number' ? [0, 1] : ['2000-01-01', '2000-12-31']
    case 'scalar':
      return type === 'outcome' ? 'pass' : type === 'number' ? 0 : ''
    default:
      return undefined
  }
}

export function newLeaf(catalog: RuleCatalog, ref?: string): LeafNode {
  const f = ref ? fieldOf(catalog, ref) : catalog.fields[0]
  if (!f) return { field: '', op: 'exists' }
  const op = Object.keys(catalog.operators[f.type])[0]
  const leaf: LeafNode = { field: f.ref, op }
  const v = defaultValue(catalog.operators[f.type][op], f.type)
  if (v !== undefined) leaf.value = v
  return leaf
}

/** Drop optional keys the server would reject or that only restate defaults, for a clean JSON view. */
export function cleanDefinition(d: RuleDefinition): RuleDefinition {
  const out: RuleDefinition = { ...d }
  if (!out.applies_when) delete out.applies_when
  if (!out.pass_message) delete out.pass_message
  if (!out.fail_message) delete out.fail_message
  return out
}

export const versionLabel = (v: { version_number: number }) => `v${v.version_number}`

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.map((x) => String(x)).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** A synthetic test case skeleton. Every case must declare itself synthetic; the server rejects anything else. */
export function synthCaseTemplate(today: string): string {
  return JSON.stringify(
    {
      synthetic: true,
      evaluation_date: today,
      application: { application_type: 'synthetic' },
      documents: [{ name: 'Test record', fields: { full_name: { value: 'Test Person Alpha' } } }],
    },
    null,
    2,
  )
}

export const todayIso = () => new Date().toISOString().slice(0, 10)

/** Error locations arrive as a dotted string (rule checks) or a list (request validation). */
export const locText = (loc: unknown): string =>
  Array.isArray(loc) ? loc.filter((p) => p !== 'body').join('.') : typeof loc === 'string' ? loc : ''

/** Readable "operator + expected value" phrase, matching the server's stored summaries. */
export function opPhrase(op: string, expected: unknown): string {
  const n = typeof expected === 'number' ? expected : 0
  const offset = n ? ` ${n > 0 ? '+' : '−'} ${Math.abs(n)} day${Math.abs(n) === 1 ? '' : 's'}` : ''
  switch (op) {
    case 'age_years_at_least':
      return `is at least ${n} years before the evaluation date`
    case 'age_years_at_most':
      return `is at most ${n} years before the evaluation date`
    case 'before_evaluation_date':
      return `is before the evaluation date${offset}`
    case 'after_evaluation_date':
      return `is after the evaluation date${offset}`
    case 'exists':
    case 'not_exists':
      return OP_LABEL[op]
    case 'between':
      return Array.isArray(expected) ? `is between ${expected[0]} and ${expected[1]}` : OP_LABEL[op]
    default:
      return `${OP_LABEL[op] ?? op} ${formatValue(expected)}`
  }
}
