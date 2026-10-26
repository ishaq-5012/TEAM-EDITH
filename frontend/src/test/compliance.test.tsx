import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { RuleCatalog, RuleDefinition, RuleDetail, RuleVersion, ValidationRun } from '../lib/types'
import { apiError, chooseOption, json, makeMe, mockApi, optionNames } from './fixtures'

const me = { id: 'u1', full_name: 'Ada Example', email: 'admin@example.com' }
const other = { id: 'u2', full_name: 'Bo Approver', email: 'approver@example.com' }

const CATALOG: RuleCatalog = {
  fields: [
    { ref: 'extracted.full_name', type: 'text', label: 'Full name', source: 'extracted', multi: true, field_type: 'name' },
    { ref: 'extracted.date_of_birth', type: 'date', label: 'Date of birth', source: 'extracted', multi: true, field_type: 'date' },
    { ref: 'evidence.person_name.outcome', type: 'outcome', label: 'Evidence: Person name', source: 'evidence', multi: false },
    { ref: 'application.application_type', type: 'text', label: 'Application type', source: 'application', multi: false },
  ],
  operators: {
    text: { eq: 'scalar', ne: 'scalar', in: 'list', not_in: 'list', contains: 'scalar', starts_with: 'scalar', ends_with: 'scalar', exists: 'none', not_exists: 'none' },
    date: { eq: 'scalar', before: 'scalar', between: 'pair', age_years_at_least: 'int', age_years_at_most: 'int', exists: 'none', not_exists: 'none' },
    number: { eq: 'scalar', gt: 'scalar', exists: 'none', not_exists: 'none' },
    outcome: { eq: 'scalar', in: 'list', exists: 'none', not_exists: 'none' },
  },
  all_operators: [],
  outcomes: ['pass', 'fail', 'review', 'insufficient', 'not_applicable'],
}

const ADULT: RuleDefinition = {
  condition: { field: 'extracted.date_of_birth', op: 'age_years_at_least', value: 18, quantifier: 'all' },
  severity: 'high', on_violation: 'fail', missing_data_policy: 'insufficient', low_confidence_policy: 'review', pass_message: '', fail_message: '',
}
const SUMMARY = {
  condition: 'Date of birth (every document with a value) is at least 18 years before the evaluation date',
  applies_when: 'Always applies',
  policies: 'Violation → fail; missing data → insufficient; low-confidence input → review; severity high.',
}
const DISCLAIMER = 'A passing rule is not a legal or regulatory determination.'

function version(over: Partial<RuleVersion> = {}): RuleVersion {
  return {
    id: 'v1', version_number: 1, status: 'published', definition: ADULT, content_hash: 'a'.repeat(64), effective_from: '2026-01-01', effective_to: null,
    source_reference: 'Synthetic policy SYN-1 §2', change_summary: 'Initial version', created_by: me, created_at: '2026-01-01T00:00:00Z',
    submitted_by: me, submitted_at: '2026-01-01T00:00:00Z', test_summary: { total: 0, passed: 0, failed: 0 }, reviewed_by: other,
    reviewed_at: '2026-01-02T00:00:00Z', review_note: 'Checked', retired_by: null, retired_at: null, retire_reason: null, summary: SUMMARY,
    in_force_today: true, ...over,
  }
}

function rule(versions: RuleVersion[], over: Partial<RuleDetail> = {}): RuleDetail {
  return {
    id: 'r1', key: 'adult_applicant', name: 'Applicant is an adult', description: '', category: 'eligibility', owner: me,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', versions, test_cases: [], disclaimer: DISCLAIMER, ...over,
  }
}

type Call = { url: string; method: string; body: unknown }

function setup(role: 'admin' | 'auditor' | 'compliance_manager' | 'second_approver' | 'reviewer', routes: Record<string, (c: Call) => Response>) {
  const calls: Call[] = []
  mockApi({
    me: makeMe(role),
    handlers: [
      (url, init) => {
        const path = url.replace(/^.*\/api\/v1/, '')
        const method = (init.method ?? 'GET').toUpperCase()
        const body = init.body ? JSON.parse(String(init.body)) : undefined
        const call = { url: path, method, body }
        calls.push(call)
        if (path === '/rules/catalog') return json(200, CATALOG)
        const key = `${method} ${path.split('?')[0]}`
        return routes[key]?.(call)
      },
    ],
  })
  return calls
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const listBody = (can: boolean) => ({
  can_manage: can,
  can_publish: can,
  disclaimer: DISCLAIMER,
  items: [
    { id: 'r1', key: 'adult_applicant', name: 'Applicant is an adult', category: 'eligibility', owner: me, in_force_version: 1, in_force_severity: 'high', latest_version: 2, latest_status: 'pending_approval', pending_approval: true, has_draft: false },
    { id: 'r2', key: 'name_present', name: 'Name is present', category: 'identity', owner: other, in_force_version: null, in_force_severity: null, latest_version: 1, latest_status: 'draft', pending_approval: false, has_draft: true },
  ],
})

describe('compliance studio register', () => {
  it('lists rules with the version in force, pending work and the non-legal disclaimer', async () => {
    setup('compliance_manager', { 'GET /rules': () => json(200, listBody(true)) })
    renderAt('/compliance')
    expect(await screen.findByText('Applicant is an adult')).toBeInTheDocument()
    expect(screen.getByText(/v1 in force · High/)).toBeInTheDocument()
    expect(screen.getByText(/v2 pending approval/)).toBeInTheDocument()
    expect(screen.getByText('Not in force')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('not a legal or regulatory determination')
    expect(screen.getByRole('button', { name: 'New rule' })).toBeInTheDocument()
  })

  it('hides authoring controls from read-only roles (the server enforces it too)', async () => {
    setup('auditor', { 'GET /rules': () => json(200, listBody(false)) })
    renderAt('/compliance')
    expect(await screen.findByText('Applicant is an adult')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New rule' })).not.toBeInTheDocument()
  })

  it('shows a retryable error state', async () => {
    setup('compliance_manager', { 'GET /rules': () => apiError(500, 'internal_error', 'Server unavailable') })
    renderAt('/compliance')
    expect(await screen.findByText('Server unavailable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})

describe('rule lifecycle', () => {
  it('enforces four-eyes in the UI: the author sees no approve action on their own pending version', async () => {
    setup('second_approver', { 'GET /rules/r1': () => json(200, rule([version({ id: 'v2', version_number: 2, status: 'pending_approval', in_force_today: false, reviewed_by: null })])) })
    renderAt('/compliance/rules/r1')
    expect(await screen.findByText(/Four-eyes rule/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  })

  it('lets a different publisher approve with a review note', async () => {
    const pending = version({ id: 'v2', version_number: 2, status: 'pending_approval', in_force_today: false, reviewed_by: null, created_by: other, submitted_by: other })
    const calls = setup('second_approver', {
      'GET /rules/r1': () => json(200, rule([pending])),
      'POST /rules/r1/versions/v2/approve': () => json(200, rule([{ ...pending, status: 'published', reviewed_by: makeMeRef(), in_force_today: true }])),
    })
    renderAt('/compliance/rules/r1')
    await userEvent.click(await screen.findByRole('button', { name: /Approve & publish/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Review note'), 'Checked source clause')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Approve & publish' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/approve'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/approve'))?.body).toEqual({ note: 'Checked source clause' })
    expect(await screen.findByText('In force today')).toBeInTheDocument()
  })

  it('reports failing synthetic tests when submission is refused', async () => {
    setup('compliance_manager', {
      'GET /rules/r1': () => json(200, rule([version({ status: 'draft', submitted_by: null, reviewed_by: null, in_force_today: false })])),
      'POST /rules/validate': () => json(200, { valid: true, errors: [], summary: SUMMARY }),
      'POST /rules/r1/versions/v1/submit': () =>
        json(409, { error: { code: 'tests_failing', message: '1 synthetic test case does not match', details: [{ name: 'Minor fails', expected: 'fail', actual: 'pass' }] } }),
    })
    renderAt('/compliance/rules/r1')
    await userEvent.click(await screen.findByRole('button', { name: 'Submit for approval' }))
    expect(await screen.findByText('Minor fails: expected fail, got pass')).toBeInTheDocument()
  })
})

const makeMeRef = () => ({ ...other })

describe('rule editor', () => {
  it('builds conditions from the allowlisted catalog and saves a declarative definition', async () => {
    const draft = version({ status: 'draft', submitted_by: null, reviewed_by: null, in_force_today: false })
    const calls = setup('compliance_manager', {
      'GET /rules/r1': () => json(200, rule([draft])),
      'POST /rules/validate': (c) => {
        const op = (c.body as { definition: RuleDefinition }).definition.condition
        return json(200, { valid: true, errors: [], summary: { ...SUMMARY, condition: `checked ${JSON.stringify(op)}` } })
      },
      'PATCH /rules/r1/versions/v1': (c) => json(200, rule([{ ...draft, definition: (c.body as { definition: RuleDefinition }).definition }])),
    })
    renderAt('/compliance/rules/r1')
    const op = await screen.findByLabelText('Condition: operator')
    // Only operators allowed for the field's type are offered.
    await userEvent.click(op)
    expect(optionNames()).toHaveLength(Object.keys(CATALOG.operators.date).length)
    await userEvent.click(screen.getByRole('option', { name: 'is before' }))
    await userEvent.type(screen.getByLabelText('Condition: value'), '2008-10-23')
    await waitFor(() => expect(screen.getByText(/checked .*"op":"before"/)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const saved = calls.find((c) => c.method === 'PATCH')?.body as { definition: RuleDefinition }
    expect(saved.definition.condition).toEqual({ field: 'extracted.date_of_birth', op: 'before', value: '2008-10-23', quantifier: 'all' })
  })

  it('shows server validation errors and blocks saving an invalid definition', async () => {
    const draft = version({ status: 'draft', submitted_by: null, reviewed_by: null, in_force_today: false })
    const calls = setup('compliance_manager', {
      'GET /rules/r1': () => json(200, rule([draft])),
      'POST /rules/validate': (c) =>
        (c.body as { definition: RuleDefinition }).definition.severity === 'high'
          ? json(200, { valid: true, errors: [], summary: SUMMARY })
          : json(200, { valid: false, errors: [{ loc: 'condition', msg: "operator 'gt' is not allowed for date fields" }], summary: null }),
    })
    renderAt('/compliance/rules/r1')
    await chooseOption(await screen.findByLabelText('Severity'), 'Low')
    expect(await screen.findByText("operator 'gt' is not allowed for date fields")).toBeInTheDocument()
    // Unavailable but still focusable, so keyboard and screen-reader users can learn why.
    const save = screen.getByRole('button', { name: 'Save draft' })
    expect(save).toHaveAttribute('aria-disabled', 'true')
    expect(save).toHaveAccessibleDescription(/validation errors/)
    await userEvent.click(save)
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })
})

describe('what-if simulation', () => {
  it('shows before/after outcomes and sends the unsaved edit, never a publish', async () => {
    const draft = version({ id: 'v2', version_number: 2, status: 'draft', submitted_by: null, reviewed_by: null, in_force_today: false })
    const calls = setup('compliance_manager', {
      'GET /rules/r1': () => json(200, rule([draft, version()])),
      'POST /rules/validate': () => json(200, { valid: true, errors: [], summary: SUMMARY }),
      'POST /rules/simulate': () =>
        json(200, {
          evaluation_date: '2026-10-23',
          side_effects: 'None: no rules, versions or validation runs were created or modified.',
          applications: [
            {
              application_id: 'a1', reference: 'APP-2026-AAA111', title: 'Synthetic case', changed: 1,
              rules: [{ rule_id: 'r1', rule_key: 'adult_applicant', rule_name: 'Applicant is an adult', before: { version: 1, outcome: 'fail', reason: 'condition_not_met' }, after: { version: 'unsaved edit', outcome: 'pass', reason: 'condition_met', trace: [] }, changed: true }],
            },
          ],
        }),
    })
    renderAt('/compliance/rules/r1')
    await chooseOption(await screen.findByLabelText('Condition: which documents'), 'in at least one document')
    await userEvent.click(screen.getByRole('tab', { name: 'What-if simulation' }))
    await userEvent.click(screen.getByRole('button', { name: 'Run simulation' }))
    const results = await screen.findByRole('region', { name: 'Simulation results' })
    expect(within(results).getByText('Rule failed')).toBeInTheDocument()
    expect(within(results).getByText('Rule passed')).toBeInTheDocument()
    expect(within(results).getByText('1 outcome would change')).toBeInTheDocument()
    expect(within(results).getByText(/Side effects: None/)).toBeInTheDocument()
    const sim = calls.find((c) => c.url === '/rules/simulate')?.body as { proposals: { definition?: RuleDefinition; version_id?: string }[] }
    expect(sim.proposals[0].definition?.condition).toMatchObject({ quantifier: 'any' })
    expect(calls.some((c) => /approve|submit|retire/.test(c.url))).toBe(false)
    // Unsaved edits survive switching tabs.
    await userEvent.click(screen.getByRole('tab', { name: 'Editor' }))
    expect(screen.getByLabelText('Condition: which documents')).toHaveTextContent('in at least one document')
  })
})

describe('validation runs', () => {
  const run: ValidationRun = {
    id: 'run1', application_id: 'a1', evaluation_date: '2026-10-23', engine_version: 'rules-engine/1.0', input_fingerprint: 'f'.repeat(64),
    ruleset_fingerprint: 'e'.repeat(64), summary: { fail: 1 }, created_by: me, created_at: '2026-10-23T00:00:00Z', disclaimer: DISCLAIMER,
    previous_run_id: null, trigger: 'manual', trigger_data: {}, next_run_ids: [],
    rule_versions: [{ rule_id: 'r1', rule_key: 'adult_applicant', rule_name: 'Applicant is an adult', version_id: 'v1', version_number: 1, content_hash: 'a', definition: ADULT, effective_from: '2026-01-01', effective_to: null, source_reference: 'Synthetic policy SYN-1 §2', owner: 'admin@example.com', approved_by: 'approver@example.com', approved_at: null }],
    results: [
      {
        id: 'res1', rule_id: 'r1', rule_version_id: 'v1', rule_key: 'adult_applicant', rule_name: 'Applicant is an adult', version_number: 1, outcome: 'fail', severity: 'high',
        reason: 'condition_not_met', message: 'Applicant under 18 (synthetic rule)', low_confidence: false, details: {},
        trace: [{ path: 'condition', field: 'extracted.date_of_birth', op: 'age_years_at_least', expected: 18, quantifier: 'all', value_type: 'date', result: false, low_confidence: false,
          observations: [{ kind: 'extracted', document_id: 'd9', document_name: 'id.pdf', field_key: 'date_of_birth', field_id: 'f1', value: '2015-01-01', raw_value: '01 Jan 2015', value_source: 'extracted', quality: 'high', page_number: 2, bbox: [1, 2, 3, 4], satisfied: false }] }],
      },
    ],
  }
  const appDetail = {
    id: 'a1', reference: 'APP-2026-AAA111', title: 'Synthetic case', applicant_name: null, application_type: 'kyc', status: 'needs_review', owner: me,
    document_count: 1, created_at: '', updated_at: '', description: '', archived_at: null, members: [], document_status_counts: {},
    permissions: { can_edit: true, can_upload: false, can_manage_members: false, allowed_actions: [] },
  }

  it('shows results with traces back to the source page and checks reproducibility', async () => {
    setup('reviewer', {
      'GET /applications/a1': () => json(200, appDetail),
      'GET /applications/a1/documents': () => json(200, []),
      'GET /applications/a1/validation-runs': () => json(200, [run]),
      'GET /applications/a1/validation-runs/run1': () => json(200, run),
      'GET /applications/a1/validation-runs/run1/reproduction': () =>
        json(200, { run_id: 'run1', snapshot_intact: true, identical: true, differences: [], engine_version: 'rules-engine/1.0', stored_engine_version: 'rules-engine/1.0' }),
    })
    renderAt('/applications/a1')
    expect(await screen.findByText('Applicant under 18 (synthetic rule)')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Evidence trace'))
    expect(screen.getByText(/approved by approver@example.com/)).toBeInTheDocument()
    expect(screen.getByText('is at least 18 years before the evaluation date')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open source/ })).toHaveAttribute('href', '/applications/a1/documents/d9?page=2&field=date_of_birth')
    await userEvent.click(screen.getByRole('button', { name: 'Check reproducibility' }))
    expect(await screen.findByText(/gives identical results/)).toBeInTheDocument()
  })

  it('explains when no rules are in force', async () => {
    setup('reviewer', {
      'GET /applications/a1': () => json(200, appDetail),
      'GET /applications/a1/documents': () => json(200, []),
      'GET /applications/a1/validation-runs': () => json(200, []),
      'POST /applications/a1/validation-runs': () => apiError(409, 'no_rules_in_force', 'No published rule versions are in force on 2026-10-23'),
    })
    renderAt('/applications/a1')
    await userEvent.click(await screen.findByRole('button', { name: 'Run rules' }))
    expect(await screen.findByText(/No published rule versions are in force/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Compliance Studio' })).toHaveAttribute('href', '/compliance')
  })
})
