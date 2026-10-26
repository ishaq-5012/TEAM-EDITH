import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { getDefaultNormalizer, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { DocumentDetail, ExtractionView, FieldOut } from '../lib/types'
import { aiDocumentAssistOff, apiError, json, makeMe, mockApi } from './fixtures'

const user = { id: 'u1', full_name: 'Ada Example', email: 'reviewer@example.com' }

function field(over: Partial<FieldOut>): FieldOut {
  return {
    id: 'f1', field_key: 'full_name', field_type: 'name', label: 'Full name', status: 'found', raw_value: 'Test Person',
    normalized_value: 'Test Person', normalized_data: { full: 'Test Person' }, normalization_note: null, method: 'text_layer_rule',
    matched_label: 'Full name', page_number: 1, bbox: [119, 87, 238.5, 103.6], confidence: 0.9, quality_flags: [], alternatives: [],
    corrections: [], effective_value: 'Test Person', effective_source: 'normalized', correction_based_on_other_value: false, ...over,
  }
}

const doc: DocumentDetail = {
  id: 'd1', application_id: 'a1', original_filename: 'synthetic-statement.pdf', document_type: null, declared_mime: 'application/pdf',
  detected_mime: 'application/pdf', size_bytes: 2048, sha256: 'b'.repeat(64), page_count: 2, status: 'needs_review', uploaded_by: user,
  created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', latest_job: null, can_retry: false, jobs: [],
}

function makeView(over: Partial<ExtractionView> = {}): ExtractionView {
  return {
    document_id: 'd1', document_status: 'needs_review', detected_mime: 'application/pdf',
    run: {
      id: 'r1', status: 'partial', is_current: true, extractor: 'baseline-rules', extractor_version: '1.0', definitions_hash: 'h',
      ocr_engine: 'none', input_sha256: 'b'.repeat(64), idempotency_key: 'k', job_id: 'j1', started_at: '2026-10-01T10:00:00Z',
      finished_at: '2026-10-01T10:00:01Z',
      summary: { pages: 2, pages_without_text: [2], pages_needing_attention: [2], fields: { found: 1, missing: 1, invalid: 1 } },
    },
    extractor: { name: 'baseline-rules', version: '1.0', kind: 'deterministic_baseline', limitations: 'Rule-based baseline: finds a value only where a configured label is followed by ":".' },
    pages: [
      { page_number: 1, width: 595, height: 842, rotation: 0, units: 'pt', text_source: 'text_layer', text_layer_quality: 'good', ocr_status: 'not_needed', ocr_confidence: null, char_count: 120, warnings: [] },
      { page_number: 2, width: 842, height: 595, rotation: 90, units: 'pt', text_source: 'none', text_layer_quality: 'none', ocr_status: 'unavailable', ocr_confidence: null, char_count: 0, warnings: [{ code: 'ocr_unavailable', message: 'This page has no usable text layer and OCR is not available on this server.' }] },
    ],
    fields: [
      field({}),
      field({ id: 'f2', field_key: 'date_of_birth', field_type: 'date', label: 'Date of birth', status: 'invalid', raw_value: '31/02/2026', normalized_value: null, normalized_data: null, normalization_note: 'February 2026 has no day 31', effective_value: '31/02/2026', effective_source: 'raw', bbox: [150, 105, 210, 121], confidence: 0.45 }),
      field({ id: 'f3', field_key: 'address', field_type: 'address', label: 'Address', status: 'missing', raw_value: null, normalized_value: null, normalized_data: null, page_number: null, bbox: null, effective_value: null, effective_source: 'none', quality_flags: ['pages_without_text'], method: null, matched_label: null, confidence: null }),
    ],
    can_correct: true, can_reprocess: true, preview_supported: true, ...over,
  }
}

function inspector(view: ExtractionView | null, extra: Parameters<typeof mockApi>[0]['handlers'] = []) {
  const app = { id: 'a1', reference: 'APP-2026-ABC234', title: 'Case', applicant_name: null, application_type: 'kyc', status: 'needs_review', owner: user, document_count: 1, created_at: '', updated_at: '', description: '', archived_at: null, members: [], document_status_counts: {}, permissions: { can_edit: true, can_upload: true, can_manage_members: true, allowed_actions: [] } }
  return mockApi({
    me: makeMe('reviewer'),
    handlers: [
      ...(extra ?? []),
      (url) => (url.includes('/api/v1/ai/') ? json(200, aiDocumentAssistOff('a1', 'd1')) : undefined),
      (url) => (url.includes('/pages/') && url.includes('/image') ? new Response(new Blob(['png'], { type: 'image/png' }), { status: 200 }) : undefined),
      (url) => (url.includes('/pages/') && url.endsWith('/text') ? json(200, { page_number: 1, text_source: 'text_layer', raw_text: 'Full name:    Test   Person', normalized_text: 'Full name: Test Person' }) : undefined),
      (url) => (url.endsWith('/documents/d1/extraction') ? (view ? json(200, view) : apiError(404, 'not_extracted', 'This document has not been extracted yet')) : undefined),
      (url) => (url.endsWith('/documents/d1') ? json(200, doc) : undefined),
      (url) => (url.endsWith('/applications/a1') ? json(200, app) : undefined),
    ],
  })
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

describe('extraction inspector', () => {
  it('shows fields with status, baseline limitations and breadcrumb trail', async () => {
    inspector(makeView())
    renderAt('/applications/a1/documents/d1')
    expect(await screen.findByText('Test Person', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText(/Rule-based baseline/)).toBeInTheDocument()
    expect(screen.getByText('Invalid')).toBeInTheDocument()
    expect(screen.getByText('February 2026 has no day 31')).toBeInTheDocument()
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText('Some pages had no readable text')).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByRole('link', { name: 'APP-2026-ABC234' })).toHaveAttribute('href', '/applications/a1')
    expect(within(crumbs).getByText('synthetic-statement.pdf')).toHaveAttribute('aria-current', 'page')
  })

  it('stays fully usable when the AI service is off or broken', async () => {
    inspector(makeView(), [(url) => (url.includes('/api/v1/ai/') ? apiError(500, 'internal_error', 'Unexpected error') : undefined)])
    renderAt('/applications/a1/documents/d1')
    expect(await screen.findByText('Test Person', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Extracted fields' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'AI suggestions' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Ask AI/ })).not.toBeInTheDocument()
  })

  it('positions highlight boxes from stored coordinates as page percentages', async () => {
    inspector(makeView())
    renderAt('/applications/a1/documents/d1')
    const box = await screen.findByRole('button', { name: 'Full name: Test Person' })
    expect(box.style.left).toBe(`${(119 / 595) * 100}%`)
    expect(box.style.top).toBe(`${(87 / 842) * 100}%`)
    expect(box.style.width).toBe(`${((238.5 - 119) / 595) * 100}%`)
    await userEvent.click(box)
    expect(box).toHaveAttribute('aria-pressed', 'true')
  })

  it('compares raw and normalized values and navigates to the source page', async () => {
    inspector(makeView({ fields: [field({ raw_value: '03 March 1990', normalized_value: '1990-03-03', effective_value: '1990-03-03', field_key: 'date_of_birth', label: 'Date of birth', field_type: 'date', page_number: 2, bbox: [100, 100, 160, 115] })] }))
    renderAt('/applications/a1/documents/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'Show details for Date of birth' }))
    const table = screen.getByRole('table', { name: /Raw and normalized values/ })
    expect(within(table).getByText('03 March 1990')).toBeInTheDocument()
    expect(within(table).getByText('1990-03-03')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show Date of birth on page 2' }))
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    expect(screen.getByText('This page has no usable text layer and OCR is not available on this server.')).toBeInTheDocument()
    expect(screen.getByText('OCR unavailable')).toBeInTheDocument()
  })

  it('shows raw and normalized page text', async () => {
    inspector(makeView())
    renderAt('/applications/a1/documents/d1')
    expect(await screen.findByText('Full name: Test Person', { selector: 'pre' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'raw' }))
    // Raw text keeps the source's whitespace exactly; disable Testing Library's whitespace collapsing to prove it.
    const raw = screen.getByText('Full name:    Test   Person', {
      selector: 'pre',
      normalizer: getDefaultNormalizer({ collapseWhitespace: false, trim: false }),
    })
    expect(raw).toBeInTheDocument()
  })

  it('submits corrections and requires a reason', async () => {
    const spy = inspector(makeView(), [
      (url, init) => (url.includes('/corrections') && init.method === 'POST' ? json(201, { id: 'c1', value: 'Test Person A', normalized_value: 'Test Person A', reason: 'typo', based_on_value: 'Test Person', based_on_field_id: 'f1', actor: user, created_at: '2026-10-01T10:00:00Z' }) : undefined),
    ])
    renderAt('/applications/a1/documents/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'Show details for Full name' }))
    await userEvent.click(screen.getByRole('button', { name: 'Correct value' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save correction' }))
    expect(await within(dialog).findByText('Give a reason (at least 3 characters)')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Typo in source')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save correction' }))
    await waitFor(() => expect(spy.mock.calls.some(([u, i]) => String(u).includes('/extraction/fields/f1/corrections') && i?.method === 'POST')).toBe(true))
    const call = spy.mock.calls.find(([u]) => String(u).includes('/corrections'))!
    expect(JSON.parse(String(call[1]!.body))).toEqual({ value: 'Test Person', reason: 'Typo in source' })
  })

  it('hides correction and reprocess controls when not permitted', async () => {
    inspector(makeView({ can_correct: false, can_reprocess: false }))
    renderAt('/applications/a1/documents/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'Show details for Full name' }))
    expect(screen.queryByRole('button', { name: 'Correct value' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument()
  })

  it('offers extraction for documents processed before extraction existed', async () => {
    const spy = inspector(null, [
      (url, init) => (url.endsWith('/reprocess') && init.method === 'POST' ? json(202, { ...doc, status: 'queued' }) : undefined),
    ])
    renderAt('/applications/a1/documents/d1')
    expect(await screen.findByText('Not extracted yet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reprocess' }))
    await waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).endsWith('/reprocess'))
      expect(call && JSON.parse(String(call[1]!.body))).toEqual({ force: false })
    })
  })

  it('honours deep links to a page and field (used by evidence findings)', async () => {
    inspector(makeView())
    renderAt('/applications/a1/documents/d1?page=2&field=date_of_birth')
    expect(await screen.findByText('Page 2 of 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Select Date of birth' })).toHaveAttribute('aria-pressed', 'true')
  })
})
