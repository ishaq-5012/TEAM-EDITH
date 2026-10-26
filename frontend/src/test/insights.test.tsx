import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import { InsightsPanel } from '../features/insights/InsightsPanel'
import type { ExportDataset, InsightsOverview, MetricDefinition, Role, RuleGovernance, RuleInsights } from '../lib/types'
import { apiError, chooseOption, emptyOverview, json, makeMe, mockApi } from './fixtures'

const DEFS: MetricDefinition[] = [
  {
    key: 'findings.engine_failures', label: 'Rule failures (engine)', group: 'findings', basis: 'current',
    definition: "Latest-run rule results with outcome 'fail'.", source: 'rule_results.outcome', time_field: null,
    dedup: "Only each application's latest validation run counts.", unit: 'count',
  },
  {
    key: 'validation.runs', label: 'Validation runs', group: 'validation', basis: 'window', definition: 'Validation runs created in the window.',
    source: 'validation_runs', time_field: 'validation_runs.created_at', dedup: '', unit: 'count',
  },
]

function overview(): InsightsOverview {
  const o = emptyOverview({ applications: 4 })
  o.scope.synthetic_applications = 1
  o.current.applications = { total: 4, by_status: { needs_review: 2, draft: 2 }, synthetic: 1 }
  o.current.findings = {
    ...o.current.findings, applications_with_run: 3, applications_without_run: 1,
    by_outcome: { fail: 2, review: 1, insufficient: 1, pass: 4 },
    by_outcome_severity: [{ outcome: 'fail', severity: 'high', count: 2 }, { outcome: 'pass', severity: 'high', count: 4 }],
    engine_failures: 2, review_required: 1, insufficient: 1, rates: { denominator: 8, uncertainty: 0.125, insufficient: 0.125 },
  }
  o.current.review = { backlog: 4, by_status: { open: 4, confirmed: 1 }, backlog_by_category: { failure: 2, uncertain: 1, missing: 1 }, backlog_by_severity: { high: 4 }, unassigned: 3 }
  o.current.human = { confirmed: 1, dismissed: 2 }
  o.window.validation = {
    runs: 5, by_trigger: { manual: 4, correction: 1 },
    by_day: [{ date: '2026-10-22', manual: 1, correction: 0 }, { date: '2026-10-23', manual: 3, correction: 1 }],
    cases: { applications: 3, by_outcome: { fail: 2, pass: 1 } },
  }
  return o
}

interface Call { method: string; path: string; params: URLSearchParams; body: unknown }

function setup(role: Role, routes: Record<string, (c: Call) => Response | undefined>) {
  const calls: Call[] = []
  mockApi({
    me: makeMe(role),
    handlers: [
      (url, init) => {
        const u = new URL(url, 'http://localhost')
        const path = u.pathname.replace(/^\/api\/v1/, '')
        const call = { method: (init.method ?? 'GET').toUpperCase(), path, params: u.searchParams, body: init.body ? JSON.parse(String(init.body)) : undefined }
        calls.push(call)
        return routes[`${call.method} ${path}`]?.(call)
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

describe('Command Center', () => {
  it('shows scoped current-state tiles that link to filtered lists, and labels synthetic data', async () => {
    const calls = setup('reviewer', {
      'GET /insights/overview': () => json(200, overview()),
      'GET /insights/definitions': () => json(200, DEFS),
    })
    renderAt('/')
    // First render in this file loads the lazy Command Center and charting chunks cold.
    const failures = await screen.findByRole('link', { name: /Rule failures \(engine\)/ }, { timeout: 30_000 })
    expect(failures).toHaveAttribute('href', '/review?category=failure')
    expect(within(failures).getByText('2')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Review required \(engine\)/ })).toHaveTextContent('uncertainty 13%')
    expect(screen.getByRole('link', { name: /Confirmed failures \(human\)/ })).toHaveAttribute('href', '/review?status=confirmed')
    expect(screen.getByRole('link', { name: /^Applications/ })).toHaveAttribute('href', '/applications?status=needs_review')
    expect(screen.getByText(/Includes 1 synthetic demo application/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Rule findings by outcome' })).toHaveTextContent('Rule failed')
    expect(screen.getByRole('figure', { name: /Validation runs per day/ })).toHaveTextContent('After a correction')
    // The reviewer's request carries a 30-day window; scoping happens on the server.
    const req = calls.find((c) => c.path === '/insights/overview')!
    expect(req.params.get('from')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(screen.queryByRole('link', { name: /Governance & Insights/, hidden: false })).toBeNull()
  }, 20_000) // the first test in this file pays for loading the lazy page and chart chunks

  it('explains a metric on demand', async () => {
    setup('auditor', { 'GET /insights/overview': () => json(200, overview()), 'GET /insights/definitions': () => json(200, DEFS) })
    const user = userEvent.setup()
    renderAt('/')
    await user.click(await screen.findByRole('button', { name: 'About “Rule failures (engine)”' }))
    const note = screen.getByText(/Latest-run rule results with outcome 'fail'/).closest('[role="note"]') as HTMLElement
    expect(note).toHaveTextContent("Only each application's latest validation run counts.")
    expect(note).toHaveTextContent('current state (the window does not apply)')
  })

  it('shows an honest empty state and an error state', async () => {
    setup('reviewer', {})
    const view = renderAt('/')
    expect(await screen.findByText('No applications yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Rule failures/ })).not.toBeInTheDocument()
    view.unmount()
    setup('reviewer', { 'GET /insights/overview': () => apiError(500, 'internal_error', 'Unexpected error') })
    renderAt('/')
    expect(await screen.findByText('Unexpected error')).toBeInTheDocument()
  })
})

describe('Governance & Insights', () => {
  it('sends window and synthetic filters to the server and keeps them in the URL', async () => {
    const calls = setup('auditor', { 'GET /insights/overview': () => json(200, overview()) })
    const user = userEvent.setup()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={['/governance?tab=insights&from=2026-10-01&to=2026-10-23']}><InsightsPanel /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText(/window 2026-09-24 to 2026-10-23/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/insights/overview')!.params.get('from')).toBe('2026-10-01')
    await user.click(screen.getByRole('checkbox', { name: /Include test records/ }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/insights/overview').at(-1)!.params.get('include_synthetic')).toBe('false'))
    await user.click(screen.getByRole('button', { name: '7 days' }))
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/insights/overview').at(-1)!
      const span = (Date.parse(last.params.get('to')!) - Date.parse(last.params.get('from')!)) / 86_400_000
      expect(span).toBe(6)
    })
    const matrix = screen.getByRole('table', { name: 'Rule findings by outcome and severity' })
    expect(within(matrix).getByRole('link', { name: '2 fail findings with high severity' })).toHaveAttribute('href', '/review?category=failure&severity=high')
  })

  it('pages through validation history and rule governance events', async () => {
    const run = (i: number) => ({
      run_id: `r${i}`, application_id: 'a1', application_reference: 'APP-1', created_at: '2026-10-23T10:00:00Z', evaluation_date: '2026-10-23',
      trigger: 'manual', previous_run_id: null, summary: { fail: 1 }, rule_versions: 1, created_by: 'Ada',
    })
    const rules = (offset: number): RuleInsights => ({
      scope: overview().scope,
      version_usage: [{ rule_id: 'rule1', rule_key: 'adult', rule_name: 'Applicant is an adult', version_id: 'v1', version_number: 1, status: 'published', effective_from: '2026-01-01', effective_to: null, runs: 12, applications: 3, latest_outcomes: { fail: 2, pass: 1 } }],
      runs: { total: 12, limit: 10, offset, items: Array.from({ length: offset ? 2 : 10 }, (_, i) => run(i + offset)) },
    })
    const gov: RuleGovernance = {
      scope: overview().scope, total: 1, limit: 15, offset: 0, counts: { approved: 1 }, rules: [{ id: 'rule1', key: 'adult', name: 'Applicant is an adult' }],
      items: [{ rule_id: 'rule1', rule_key: 'adult', rule_name: 'Applicant is an adult', version_id: 'v1', version_number: 1, current_status: 'published', content_hash: 'c'.repeat(64), event: 'approved', at: '2026-10-20T10:00:00Z', actor: { id: 'm', full_name: 'Manager M', email: 'm@example.org' }, detail: 'ok', four_eyes: true }],
    }
    const calls = setup('auditor', {
      'GET /insights/rules': (c) => json(200, rules(Number(c.params.get('offset') ?? 0))),
      'GET /insights/rule-governance': () => json(200, gov),
    })
    const user = userEvent.setup()
    renderAt('/governance?tab=rules')
    expect(await screen.findByRole('table', { name: 'Rule-version usage' })).toHaveTextContent('Rule failed: 2')
    expect(await screen.findByText('Four-eyes')).toBeInTheDocument()
    const pager = screen.getByRole('navigation', { name: 'Validation history pages' })
    expect(pager).toHaveTextContent('1–10 of 12')
    await user.click(within(pager).getByRole('button', { name: /Next/ }))
    await waitFor(() => expect(screen.getByRole('navigation', { name: 'Validation history pages' })).toHaveTextContent('11–12 of 12'))
    expect(calls.filter((c) => c.path === '/insights/rules').at(-1)!.params.get('offset')).toBe('10')
  })

  it('filters audit history by action group, outcome and dates', async () => {
    const calls = setup('auditor', {
      'GET /audit/actions': () => json(200, ['export.created', 'rule.created']),
      'GET /audit/events': () => json(200, { items: [], total: 0, limit: 25, offset: 0 }),
    })
    const user = userEvent.setup()
    renderAt('/governance?tab=audit')
    const form = await screen.findByRole('form', { name: 'Audit filters' })
    await user.click(within(form).getByLabelText('Action'))
    await user.click(await screen.findByRole('option', { name: /export\.\* \(all export actions\)/ }))
    await chooseOption(within(form).getByLabelText('Outcome'), 'Failure')
    await user.type(within(form).getByLabelText('From (UTC)'), '2026-10-01')
    await user.click(within(form).getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      const p = calls.filter((c) => c.path === '/audit/events').at(-1)!.params
      expect([p.get('action'), p.get('outcome'), p.get('from')]).toEqual(['export.', 'failure', '2026-10-01'])
    })
    expect(await screen.findByText('No events match these filters')).toBeInTheDocument()
  })
})

const DATASETS = (role: 'auditor' | 'compliance_manager'): ExportDataset[] => [
  { key: 'review_items', label: 'Review items', description: 'No document values.', sensitive: false, allowed: true, can_include_document_values: role !== 'auditor', requires: ['exports:create'] },
  { key: 'extracted_fields', label: 'Extracted field values', description: 'Contains document content.', sensitive: true, allowed: role !== 'auditor', can_include_document_values: role !== 'auditor', requires: ['exports:create', 'exports:sensitive'] },
]

describe('Exports', () => {
  it('locks sensitive datasets for roles without exports:sensitive', async () => {
    setup('auditor', { 'GET /exports/datasets': () => json(200, DATASETS('auditor')) })
    renderAt('/governance?tab=exports')
    expect(await screen.findByText(/Your role can’t export this dataset \(needs exports:create and exports:sensitive\)/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Export CSV/ })).toHaveLength(1)
  })

  it('requires a reason before exporting document values and sends the explicit opt-in', async () => {
    const calls = setup('compliance_manager', {
      'GET /exports/datasets': () => json(200, DATASETS('compliance_manager')),
      'POST /exports': () => new Response('a,b\r\n1,2\r\n', { status: 200, headers: { 'Content-Disposition': 'attachment; filename="verifyflow-extracted_fields.csv"', 'X-Export-Rows': '1', 'X-Export-Truncated': 'false' } }),
    })
    const user = userEvent.setup()
    renderAt('/governance?tab=exports')
    const card = (await screen.findByText('Extracted field values')).closest('div.rounded-\\[var\\(--radius-card\\)\\]') as HTMLElement
    const button = within(card).getByRole('button', { name: /Export CSV/ })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(/at least 10 characters/)
    await user.type(within(card).getByLabelText(/Reason for exporting document values/), 'Quarterly quality review')
    expect(button).not.toHaveAttribute('aria-disabled')
    await user.click(button)
    expect(await within(card).findByText(/Downloaded verifyflow-extracted_fields.csv: 1 row\. Recorded in the audit history\./)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/exports')!.body).toMatchObject({
      dataset: 'extracted_fields', format: 'csv', include_document_values: true, reason: 'Quarterly quality review',
    })
  })

  it('shows the server refusal', async () => {
    setup('compliance_manager', {
      'GET /exports/datasets': () => json(200, DATASETS('compliance_manager')),
      'POST /exports': () => apiError(403, 'export_forbidden', "Your role can't export document values"),
    })
    const user = userEvent.setup()
    renderAt('/governance?tab=exports')
    const card = (await screen.findByText('Review items')).closest('div.rounded-\\[var\\(--radius-card\\)\\]') as HTMLElement
    await user.click(within(card).getByRole('button', { name: /Export CSV/ }))
    expect(await within(card).findByRole('alert')).toHaveTextContent("Your role can't export document values")
  })
})
