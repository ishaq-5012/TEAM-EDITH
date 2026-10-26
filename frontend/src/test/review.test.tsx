import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { ReviewDetail, ReviewItem, ReviewQueue } from '../lib/types'
import { chooseOption, json, makeMe, mockApi } from './fixtures'

const me = { id: 'u1', full_name: 'Ada Example', email: 'reviewer@example.com' }
const other = { id: 'u2', full_name: 'Bo Manager', email: 'manager@example.com' }
const appRef = { id: 'a1', reference: 'APP-2026-AAA111', title: 'Synthetic case', status: 'needs_review' as const }

function item(over: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 'i1', application_id: 'a1', rule_id: 'r1', rule_key: 'adult_applicant', rule_name: 'Applicant is an adult', origin_result_id: 'res1',
    current_result_id: 'res1', current_run_id: 'run1', previous_item_id: null, category: 'failure', outcome: 'fail', severity: 'high', priority: 60,
    status: 'open', assignee: null, document_request: null, closed_by: null, closed_at: null, version: 1, created_at: '2026-10-23T00:00:00Z',
    updated_at: '2026-10-23T00:00:00Z', ...over,
  }
}

function detail(over: Partial<ReviewDetail> = {}, itemOver: Partial<ReviewItem> = {}): ReviewDetail {
  return {
    item: item(itemOver),
    application: appRef,
    result: {
      id: 'res1', rule_version_id: 'v1', version_number: 1, outcome: 'fail', severity: 'high', reason: 'condition_not_met', message: 'Applicant under 18', low_confidence: false, details: {},
      trace: [{ path: 'condition', field: 'extracted.date_of_birth', op: 'age_years_at_least', expected: 18, quantifier: 'all', value_type: 'date', result: false, low_confidence: false,
        observations: [{ kind: 'extracted', document_id: 'd2', document_name: 'minor.pdf', field_key: 'date_of_birth', field_id: 'f2', value: '2015-01-01', raw_value: '01 January 2015', value_source: 'extracted', quality: 'high', page_number: 1, bbox: [1, 2, 3, 4], satisfied: false }] }],
    },
    run: { id: 'run1', evaluation_date: '2026-10-23', created_at: '2026-10-23T00:00:00Z', trigger: 'manual', previous_run_id: null },
    rule: { version_number: 1, source_reference: 'Synthetic SYN-1', owner: 'author@example.com', approved_by: 'manager@example.com',
      summary: { condition: 'Date of birth (every document with a value) is at least 18 years before the evaluation date', applies_when: 'Always applies', policies: 'Violation → fail' } },
    uncertainty: [{ code: 'condition_not_met', message: 'minor.pdf: “2015-01-01” does not satisfy the rule.' }],
    fields: [{
      field_id: 'f2', document_id: 'd2', document_name: 'minor.pdf', field_key: 'date_of_birth', label: 'Date of birth', field_type: 'date', status: 'found',
      raw_value: '01 January 2015', normalized_value: '2015-01-01', method: 'text_layer_rule', confidence: 0.9, quality_flags: [], page_number: null, bbox: null,
      page_width: null, page_height: null, is_current_extraction: true, in_trace: true, value_at_validation: '2015-01-01', effective_value: '2015-01-01', corrections: [],
    }],
    evidence: { analysis_id: null, findings: [] },
    history: [{ id: 'h1', sequence: 1, action: 'opened', actor: me, from_status: null, to_status: 'open', reason: null, data: {}, request_id: null, created_at: '2026-10-23T00:00:00Z' }],
    previous_items: [],
    rule_runs: [{ run_id: 'run1', created_at: '2026-10-23T00:00:00Z', evaluation_date: '2026-10-23', trigger: 'manual', previous_run_id: null, outcome: 'fail', result_id: 'res1', version_number: 1 }],
    permissions: { can_act: true, can_correct: true, oversight: false, can_decide: true },
    ...over,
  }
}

type Call = { path: string; method: string; body: Record<string, unknown> | undefined }

function setup(role: 'reviewer' | 'auditor' | 'compliance_manager', routes: Record<string, (c: Call, n: number) => Response | Promise<Response>>) {
  const calls: Call[] = []
  const counts: Record<string, number> = {}
  mockApi({
    me: makeMe(role, { id: 'u1' }),
    handlers: [
      (url, init) => {
        const path = url.replace(/^.*\/api\/v1/, '')
        const method = (init.method ?? 'GET').toUpperCase()
        const call = { path, method, body: init.body ? JSON.parse(String(init.body)) : undefined }
        calls.push(call)
        const key = `${method} ${path.split('?')[0]}`
        counts[key] = (counts[key] ?? 0) + 1
        return routes[key]?.(call, counts[key])
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

const queue = (items: ReviewItem[]): ReviewQueue => ({
  items: items.map((i) => ({ item: i, application: appRef })),
  total: items.length,
  limit: 100,
  offset: 0,
  counts: { status: { open: items.length }, category: { failure: items.length }, mine: 0 },
  can_act_anywhere: true,
})

describe('review queue', () => {
  it('opens the compliance manager on escalated findings', async () => {
    const calls = setup('compliance_manager', {
      'GET /reviews': () => json(200, queue([item({ status: 'escalated' })])),
    })
    renderAt('/review')
    expect(await screen.findByText('Applicant is an adult')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Escalated' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText(/Compliance review is conditional/)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/reviews?') && c.path.includes('status=escalated'))).toBe(true)
  })

  it('lists items by priority, filters through the API and supports arrow-key navigation', async () => {
    const calls = setup('reviewer', {
      'GET /reviews': () => json(200, queue([item(), item({ id: 'i2', rule_name: 'Name present', category: 'missing', outcome: 'insufficient', severity: 'medium', priority: 30 })])),
    })
    renderAt('/review')
    const links = await screen.findAllByRole('link', { name: /Applicant is an adult|Name present/ })
    expect(links).toHaveLength(2)
    links[0].focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(links[1]).toHaveFocus()
    await userEvent.keyboard('{ArrowUp}')
    expect(links[0]).toHaveFocus()
    await chooseOption(screen.getByLabelText('Category'), /^Missing evidence/)
    await chooseOption(screen.getByLabelText('Assignee'), /^Assigned to me/)
    await waitFor(() => expect(calls.some((c) => c.path.includes('category=missing') && c.path.includes('assignee=me'))).toBe(true))
    await userEvent.click(screen.getByRole('tab', { name: /Escalated/ }))
    await waitFor(() => expect(calls.some((c) => c.path.includes('status=escalated'))).toBe(true))
  })

  it('shows an honest empty state', async () => {
    setup('reviewer', { 'GET /reviews': () => json(200, queue([])) })
    renderAt('/review')
    expect(await screen.findByText('Nothing needs review')).toBeInTheDocument()
  })
})

describe('review item', () => {
  it('shows the split pane: document, extracted field, rule, uncertainty and history', async () => {
    setup('reviewer', { 'GET /reviews/i1': () => json(200, detail()) })
    renderAt('/review/i1')
    expect(await screen.findByRole('heading', { name: 'Applicant is an adult' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Original document' })).toHaveTextContent('was not found on any page')
    const field = screen.getByRole('region', { name: /Extracted field/ })
    expect(field).toHaveTextContent('01 January 2015')
    expect(field).toHaveTextContent('2015-01-01')
    expect(screen.getByRole('region', { name: 'Why this needs review' })).toHaveTextContent('does not satisfy the rule')
    expect(screen.getByRole('region', { name: 'Applicable rule' })).toHaveTextContent('approved by manager@example.com')
    expect(screen.getByRole('region', { name: 'History' })).toHaveTextContent('Opened by validation')
  })

  it('is read-only for auditors', async () => {
    setup('auditor', { 'GET /reviews/i1': () => json(200, detail({ permissions: { can_act: false, can_correct: false, oversight: true, can_decide: false } })) })
    renderAt('/review/i1')
    expect(await screen.findByText(/Read-only/)).toBeInTheDocument()
    expect(screen.queryByRole('toolbar', { name: 'Review actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Correct value' })).not.toBeInTheDocument()
  })

  it('explains escalation and hides decisions from reviewers without oversight', async () => {
    setup('reviewer', { 'GET /reviews/i1': () => json(200, detail({ permissions: { can_act: true, can_correct: true, oversight: false, can_decide: false } }, { status: 'escalated' })) })
    renderAt('/review/i1')
    expect(await screen.findByText(/only a compliance manager can decide/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm finding' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument()
  })

  it('requires a reason to dismiss and sends the version and an idempotency key', async () => {
    const calls = setup('reviewer', {
      'GET /reviews/i1': () => json(200, detail()),
      'POST /reviews/i1/actions': () =>
        json(200, { item: item({ status: 'dismissed', version: 2 }), action: { ...detail().history[0], id: 'h2', action: 'dismissed' }, replayed: false, revalidation: null }),
    })
    renderAt('/review/i1')
    await userEvent.click(await screen.findByRole('button', { name: 'Dismiss…' }))
    const dialog = await screen.findByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Dismiss finding' })
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'too short')
    expect(submit).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Reason/), ' — dependant document')
    await userEvent.click(submit)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const body = calls.find((c) => c.method === 'POST')!.body!
    expect(body).toMatchObject({ action: 'dismissed', expected_version: 1, reason: 'too short — dependant document' })
    expect(String(body.request_id)).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  })

  it('recovers from a conflicting decision without losing the typed reason', async () => {
    const calls = setup('reviewer', {
      'GET /reviews/i1': (_c, n) =>
        json(200, n === 1 ? detail() : detail({ history: [...detail().history, { ...detail().history[0], id: 'h9', sequence: 2, action: 'commented', actor: other, reason: 'Manager note' }] }, { version: 2 })),
      'POST /reviews/i1/actions': (_c, n) =>
        n === 1
          ? json(409, { error: { code: 'stale_item', message: 'Someone else updated this item', details: { current_version: 2 } } })
          : json(200, { item: item({ status: 'confirmed', version: 3 }), action: { ...detail().history[0], id: 'h3', action: 'confirmed' }, replayed: false, revalidation: null }),
    })
    renderAt('/review/i1')
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm finding' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Future date of birth')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finding' }))
    expect(await within(dialog).findByText('Someone else updated this item.')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Reason')).toHaveValue('Future date of birth')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Load latest' }))
    expect(await screen.findByText('Manager note')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm finding' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts.map((p) => p.body!.expected_version)).toEqual([1, 2])
    expect(posts[0].body!.request_id).toBe(posts[1].body!.request_id) // same submission, retried
  })

  it('shows a comment immediately and removes it if the server rejects it', async () => {
    let release: (r: Response) => void = () => undefined
    setup('reviewer', {
      'GET /reviews/i1': () => json(200, detail()),
      'POST /reviews/i1/actions': () => new Promise<Response>((r) => (release = r)),
    })
    renderAt('/review/i1')
    await userEvent.click(await screen.findByRole('button', { name: 'Comment' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Comment'), 'Checked both IDs')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add comment' }))
    const history = screen.getByRole('region', { name: 'History' })
    expect(await within(history).findByText('Checked both IDs')).toBeInTheDocument()
    expect(within(history).getByText('sending…')).toBeInTheDocument()
    release(json(500, { error: { code: 'internal_error', message: 'Server unavailable', details: null } }))
    expect(await within(dialog).findByText('Server unavailable')).toBeInTheDocument()
    await waitFor(() => expect(within(history).queryByText('Checked both IDs')).not.toBeInTheDocument())
  })

  it('corrects a value with before/after preview and reports revalidation', async () => {
    const calls = setup('reviewer', {
      'GET /reviews/i1': () => json(200, detail()),
      'POST /reviews/i1/corrections': () =>
        json(200, {
          item: item({ status: 'resolved', version: 3 }),
          action: { ...detail().history[0], id: 'h4', action: 'field_corrected' },
          replayed: false,
          revalidation: { performed: true, affected_rules: ['adult_applicant'], run_id: 'run2', previous_run_id: 'run1', summary: { pass: 1 } },
        }),
    })
    renderAt('/review/i1')
    await userEvent.click(await screen.findByRole('button', { name: 'Correct value' }))
    const dialog = await screen.findByRole('dialog')
    const value = within(dialog).getByLabelText('Corrected value')
    await userEvent.clear(value)
    await userEvent.type(value, '1990-03-03')
    expect(dialog).toHaveTextContent('Original extraction01 January 2015')
    expect(dialog).toHaveTextContent('New value1990-03-03')
    const save = within(dialog).getByRole('button', { name: 'Save correction' })
    expect(save).toBeDisabled() // reason required
    await userEvent.type(within(dialog).getByLabelText('Reason (required)'), 'OCR misread the year')
    await userEvent.click(save)
    expect(await screen.findByText(/Revalidated:/)).toHaveTextContent('1 pass')
    expect(calls.find((c) => c.path.endsWith('/corrections'))!.body).toMatchObject({ document_id: 'd2', field_id: 'f2', value: '1990-03-03', expected_version: 1 })
  })
})
