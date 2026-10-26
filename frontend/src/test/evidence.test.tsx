import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { EvidenceFinding, EvidenceReference, EvidenceView } from '../lib/types'
import { apiError, json, makeMe, mockApi } from './fixtures'

const user = { id: 'u1', full_name: 'Ada Example', email: 'reviewer@example.com' }
const appDetail = {
  id: 'a1', reference: 'APP-2026-ABC234', title: 'Case', applicant_name: null, application_type: 'kyc', status: 'needs_review', owner: user,
  document_count: 2, created_at: '', updated_at: '', description: '', archived_at: null, members: [], document_status_counts: {},
  permissions: { can_edit: true, can_upload: true, can_manage_members: true, allowed_actions: [] },
}

function ref(id: string, doc: string, name: string, over: Partial<EvidenceReference> = {}): EvidenceReference {
  return {
    id, document_id: doc, document_name: name, extraction_run_id: `run-${doc}`, extracted_field_id: `f-${id}`, correction_id: null,
    field_key: 'date_of_birth', field_label: 'Date of birth', status: 'found', raw_value: '03 March 1990', normalized_value: '1990-03-03',
    effective_value: '1990-03-03', value_source: 'extracted', method: 'text_layer_rule', page_number: 1, bbox: [100, 90, 180, 104],
    confidence: 0.9, quality_flags: [], evidence_quality: 'high', usable: true, page_width: 595, page_height: 842, ...over,
  }
}

const dob: EvidenceFinding = {
  id: 'fd', group_key: 'date_of_birth', group_label: 'Date of birth', comparator: 'date', severity: 'critical', outcome: 'fail', evidence_quality: 'high',
  priority_score: 85,
  priority_factors: [
    { factor: 'severity', value: 'critical', contribution: 40, max: 40, explanation: 'The date of birth check is configured as critical severity.' },
    { factor: 'outcome', value: 'fail', contribution: 30, max: 30, explanation: 'The finding outcome is “fail”.' },
    { factor: 'evidence_quality', value: 'high', contribution: 10, max: 10, explanation: 'Stronger evidence makes the finding more actionable.' },
    { factor: 'breadth', value: 2, contribution: 5, max: 10, explanation: '2 document(s) involved in a disagreement.' },
    { factor: 'impact', value: [], contribution: 0, max: 10, explanation: 'No downstream decisions are configured for this check.' },
  ],
  coverage: { documents: 2, with_value: 2, missing: 0, invalid: 0, not_extracted: 0, min_values: 2 },
  explanation: 'Date of birth: contradiction.',
  references: [
    ref('r1', 'd1', 'passport.pdf'),
    ref('r2', 'd2', 'form.pdf', { raw_value: '04 April 1985', normalized_value: '1985-04-04', effective_value: '1985-04-04', page_number: 2 }),
  ],
  relationships: [
    { id: 'rel1', source_reference_id: 'r1', target_reference_id: 'r2', result: 'fail', method: 'exact', reason: 'different_values', details: { difference_days: 1794 }, evidence_quality: 'high', explanation: 'Contradiction — Date of birth: “passport.pdf” (page 1): “1990-03-03” vs “form.pdf” (page 2): “1985-04-04”. The values differ.' },
  ],
}

const address: EvidenceFinding = {
  ...dob, id: 'fa', group_key: 'address', group_label: 'Address', comparator: 'address', severity: 'medium', outcome: 'insufficient', evidence_quality: 'high',
  priority_score: 36, explanation: 'Address: insufficient evidence.',
  coverage: { documents: 2, with_value: 1, missing: 1, invalid: 0, not_extracted: 0, min_values: 2 },
  references: [
    ref('a1', 'd1', 'passport.pdf', { field_key: 'address', field_label: 'Address', effective_value: '1 Synthetic Street' }),
    ref('a2', 'd2', 'form.pdf', { field_key: 'address', field_label: 'Address', status: 'missing', raw_value: null, normalized_value: null, effective_value: null, value_source: 'none', usable: false, bbox: null, page_number: null }),
  ],
  relationships: [{ id: 'rel2', source_reference_id: 'a1', target_reference_id: 'a2', result: 'insufficient', method: 'none', reason: 'missing_value', details: { missing_side: 'd2' }, evidence_quality: null, explanation: 'Insufficient evidence — Address.' }],
}

function view(over: Partial<EvidenceView> = {}): EvidenceView {
  return {
    application_id: 'a1',
    analysis: { id: 'an1', is_current: true, comparator_version: 'evidence-comparators/1.0', config_version: '2026.10-baseline', config_hash: 'c', input_fingerprint: 'f'.repeat(64), document_count: 2, summary: { fail: 1, insufficient: 1, pass: 0, review: 0 }, created_at: '2026-10-23T10:00:00Z' },
    stale: false, reused: false, can_analyze: true, findings: [dob, address], ...over,
  }
}

function setup(v: EvidenceView | null, extra: Parameters<typeof mockApi>[0]['handlers'] = []) {
  return mockApi({
    me: makeMe('reviewer'),
    handlers: [
      ...(extra ?? []),
      (url) => (url.includes('/pages/') && url.includes('/image') ? new Response(new Blob(['png'], { type: 'image/png' }), { status: 200 }) : undefined),
      (url) => (url.endsWith('/applications/a1/evidence') ? (v ? json(200, v) : apiError(404, 'not_analyzed', 'No evidence analysis has been run')) : undefined),
      (url) => (url.endsWith('/applications/a1') ? json(200, appDetail) : undefined),
    ],
  })
}

/** The Matrix view: every check against every document (the former default graph). */
async function openMatrix({ comparisons = false } = {}) {
  await userEvent.click(await screen.findByRole('radio', { name: 'Matrix' }))
  if (comparisons) for (const b of await screen.findAllByRole('button', { name: /^Show comparisons for/ })) await userEvent.click(b)
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

describe('evidence graph', () => {
  it('draws only stored relationships and references, with accessible labels', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await openMatrix({ comparisons: true })
    const graph = await screen.findByRole('group', { name: /Evidence graph: 2 checks across 2 documents/ })
    const edges = within(graph).getAllByRole('button', { name: /versus/ })
    expect(edges).toHaveLength(2) // exactly the two stored relationships
    expect(within(graph).getByRole('button', { name: 'Date of birth: passport.pdf versus form.pdf: Contradiction' })).toBeInTheDocument()
    expect(within(graph).getByRole('button', { name: 'Address: passport.pdf versus form.pdf: Insufficient evidence' })).toBeInTheDocument()
    expect(within(graph).getByRole('button', { name: 'Address in form.pdf: missing' })).toBeInTheDocument()
  })

  it('collapses and expands document nodes', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await openMatrix()
    const doc = await screen.findByRole('button', { name: /Document form.pdf/ })
    expect(doc).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(doc)
    expect(screen.getByRole('button', { name: /Document form.pdf/ })).toHaveAttribute('aria-expanded', 'false')
    // Values are still reachable (as compact nodes) when collapsed.
    expect(screen.getByRole('button', { name: 'Date of birth in form.pdf: 1985-04-04' })).toBeInTheDocument()
  })

  it('shows a side-by-side comparison with provenance and inspector deep links', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await openMatrix({ comparisons: true })
    await userEvent.click(await screen.findByRole('button', { name: 'Date of birth: passport.pdf versus form.pdf: Contradiction' }))
    const source = screen.getByRole('region', { name: 'Source' })
    const target = screen.getByRole('region', { name: 'Target' })
    expect(within(source).getByText('passport.pdf')).toBeInTheDocument()
    expect(within(target).getByText('04 April 1985')).toBeInTheDocument()
    expect(within(target).getByRole('link', { name: /Inspect/ })).toHaveAttribute('href', '/applications/a1/documents/d2?page=2&field=date_of_birth')
    expect(screen.getByText(/The values differ\./)).toBeInTheDocument()
    expect(await within(target).findByRole('img', { name: /Excerpt of page 2 of form.pdf/ })).toBeInTheDocument()
  })

  it('explains priority with every factor and its contribution', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await userEvent.click(await screen.findByRole('button', { name: /Date of birth: Contradiction, priority 85/ }))
    expect(screen.getByText('Priority 85/100')).toBeInTheDocument()
    expect(screen.getByText('Deterministic ordering aid, not a compliance decision')).toBeInTheDocument()
    for (const [label, points] of [['Severity', '+40 / 40'], ['Outcome', '+30 / 30'], ['Documents involved', '+5 / 10']]) {
      const row = screen.getByText(label).closest('li')!
      expect(within(row).getByText(points)).toBeInTheDocument()
    }
  })

  it('offers an accessible list alternative ordered by priority', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await userEvent.click(await screen.findByRole('radio', { name: 'List' }))
    const list = screen.getByRole('list', { name: 'Findings ordered by priority' })
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Date of birth')
    expect(within(items[1]).getByText('(missing)')).toBeInTheDocument()
    await userEvent.click(within(items[0]).getByRole('button', { name: 'Compare passport.pdf and form.pdf for Date of birth' }))
    expect(screen.getByRole('region', { name: 'Target' })).toBeInTheDocument()
  })

  it('warns when the analysis is stale', async () => {
    setup(view({ stale: true }))
    renderAt('/applications/a1/evidence')
    expect(await screen.findByText(/have changed since this analysis/)).toBeInTheDocument()
  })

  it('runs the first analysis and reports reuse honestly', async () => {
    const spy = setup(null, [
      (url, init) => (url.endsWith('/evidence/analyses') && init.method === 'POST' ? json(200, view({ reused: true })) : undefined),
    ])
    renderAt('/applications/a1/evidence')
    expect(await screen.findByText('No analysis yet')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Run analysis' })[0])
    expect(await screen.findByText(/so it was reused/)).toBeInTheDocument()
    const call = spy.mock.calls.find(([u]) => String(u).endsWith('/evidence/analyses'))!
    expect(JSON.parse(String(call[1]!.body))).toEqual({ force: false })
  })

  it('hides analysis actions from read-only users', async () => {
    setup(view({ can_analyze: false }))
    renderAt('/applications/a1/evidence')
    await screen.findByRole('heading', { name: 'Date of birth' })
    expect(screen.queryByRole('button', { name: /Re-run analysis/ })).not.toBeInTheDocument()
  })

  it('colours matrix cells by agreement and lists comparisons on demand', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await openMatrix()
    expect(screen.queryByRole('button', { name: /versus/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Date of birth in form.pdf: 1985-04-04' })).toHaveAttribute('title', expect.stringContaining('differs'))
    await userEvent.click(screen.getByRole('button', { name: 'Show comparisons for Date of birth' }))
    expect(screen.getAllByRole('button', { name: /versus/ })).toHaveLength(1)
    // Only documents with a difference: both documents differ here, so both columns stay.
    await userEvent.click(screen.getByRole('checkbox', { name: /Only documents with differences/ }))
    expect(screen.getByRole('button', { name: /Document form.pdf/ })).toBeInTheDocument()
  })

  it('groups documents by the value they hold, so a contradiction shows as two values', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    const card = (await screen.findByRole('heading', { name: 'Date of birth' })).closest('article')!
    expect(within(card).getByText('2 different values across documents.')).toBeInTheDocument()
    const values = within(within(card).getByRole('list', { name: 'Values for Date of birth' })).getAllByRole('listitem')
    expect(values.map((v) => v.textContent)).toEqual([expect.stringContaining('1990-03-03'), expect.stringContaining('1985-04-04')])
    // A value chip opens that document's evidence in the drawer.
    await userEvent.click(within(card).getByRole('button', { name: 'Date of birth in form.pdf: 1985-04-04' }))
    const drawer = await screen.findByRole('dialog', { name: 'Date of birth: form.pdf' })
    expect(within(drawer).getByText('04 April 1985')).toBeInTheDocument()
  })

  it('opens evidence in a drawer that closes on Escape and returns focus', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    const open = await screen.findByRole('button', { name: /Date of birth: Contradiction, priority 85. Open evidence/ })
    await userEvent.click(open)
    expect(await screen.findByRole('dialog', { name: 'Date of birth' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(open).toHaveFocus()
  })

  it('filters checks by outcome from the summary tiles', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await screen.findByRole('heading', { name: 'Address' })
    const tiles = screen.getByRole('region', { name: 'Filter checks by outcome' })
    await userEvent.click(within(tiles).getByRole('button', { name: /Contradiction/ }))
    expect(within(tiles).getByRole('button', { name: /Contradiction/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: 'Date of birth' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Address' })).not.toBeInTheDocument())
    await userEvent.click(within(tiles).getByRole('button', { name: /Consistent/ }))
    expect(screen.getByText(/No checks with this outcome/)).toBeInTheDocument()
  })

  it('draws one check at a time in the network view, from stored comparisons only', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    await userEvent.click(await screen.findByRole('radio', { name: 'Network' }))
    const net = await screen.findByRole('group', { name: 'Network for Date of birth: 2 documents, 1 comparisons' })
    expect(within(net).getAllByRole('button', { name: /versus/ })).toHaveLength(1)
    await userEvent.click(screen.getByRole('radio', { name: /Address/ }))
    const address = await screen.findByRole('group', { name: /Network for Address/ })
    expect(within(address).getByRole('button', { name: 'Address in form.pdf: missing' })).toBeInTheDocument()
  })

  it('shows a first-page thumbnail for every document', async () => {
    setup(view())
    renderAt('/applications/a1/evidence')
    const rail = await screen.findByRole('list', { name: 'Documents' })
    expect(await within(rail).findByRole('img', { name: 'First page of passport.pdf' })).toBeInTheDocument()
    expect(await within(rail).findByRole('img', { name: 'First page of form.pdf' })).toBeInTheDocument()
  })
})
