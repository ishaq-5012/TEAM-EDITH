import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import type { ApplicationDetail, DocumentOut, Role } from '../lib/types'
import { aiProviderOff, apiError, json, makeMe, mockApi } from './fixtures'

const owner = { id: 'u1', full_name: 'Ada Example', email: 'reviewer@example.com' }

function makeApp(overrides: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    review_stage: 'reviewer',
    id: 'a1', reference: 'APP-2026-ABC234', title: 'Synthetic onboarding case', applicant_name: 'Test Applicant',
    application_type: 'onboarding', status: 'draft', owner, document_count: 0,
    created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', description: '', archived_at: null,
    members: [], document_status_counts: {},
    permissions: { can_edit: true, can_upload: true, can_manage_members: true, allowed_actions: ['archive'] },
    ...overrides,
  }
}

function makeDoc(overrides: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: 'd1', application_id: 'a1', original_filename: 'synthetic-statement.pdf', document_type: null,
    declared_mime: 'application/pdf', detected_mime: 'application/pdf', size_bytes: 2048, sha256: 'a'.repeat(64),
    page_count: 2, status: 'ready', uploaded_by: owner, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z',
    latest_job: null, can_retry: false, ...overrides,
  }
}

const limits = { max_upload_bytes: 1_000_000, max_pdf_pages: 500, max_documents_per_application: 200, accepted: { 'application/pdf': ['.pdf'], 'image/png': ['.png'] } }

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

function aiSummaryOff() {
  return {
    subject: { type: 'application', id: 'a1', application_id: 'a1', application_reference: 'APP-2026-AAA111' },
    deterministic: { kind: 'application', outcome: 'not_validated', severity: null },
    fallback: { statements: [{ text: 'No validation run exists for this application yet, so no rule has been evaluated.', references: [] }] },
    ai: null,
    error: null,
    provider: aiProviderOff(),
    can_request: false,
    limitations: ['AI output is advisory.'],
  }
}

function workspace(role: Role, app = makeApp(), docs: DocumentOut[] = []) {
  return mockApi({
    me: makeMe(role),
    handlers: [
      // The application page shows an AI summary panel; with AI off it only offers the deterministic summary.
      (url) => (url.includes('/ai/explanations') ? json(200, aiSummaryOff()) : undefined),
      (url) => (url.endsWith('/applications/upload-limits') ? json(200, limits) : undefined),
      (url) => (url.endsWith('/applications/a1/documents') ? json(200, docs) : undefined),
      (url) => (url.endsWith('/applications/a1') ? json(200, app) : undefined),
    ],
  })
}

/** Minimal XHR double that emits real-looking upload progress, then responds. */
class FakeXHR {
  static instances: FakeXHR[] = []
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  status = 0
  responseText = ''
  headers: Record<string, string> = {}
  method = ''
  url = ''
  body: FormData | null = null
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v
  }
  getResponseHeader() {
    return null
  }
  send(body: FormData) {
    this.body = body
    FakeXHR.instances.push(this)
  }
  abort() {
    this.onabort?.()
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total })
  }
  respond(status: number, body: unknown) {
    this.status = status
    this.responseText = JSON.stringify(body)
    this.onload?.()
  }
}

afterEach(() => {
  FakeXHR.instances = []
  vi.unstubAllGlobals()
})

describe('applications list', () => {
  it('shows applications, and filters by status through the API', async () => {
    const spy = mockApi({
      me: makeMe('reviewer'),
      handlers: [(url) => (url.includes('/applications?') ? json(200, { items: [makeApp({ document_count: 3 })], total: 1, limit: 20, offset: 0, application_types: ['onboarding'], can_create: true }) : undefined)],
    })
    renderAt('/applications')
    expect(await screen.findByRole('link', { name: /Synthetic onboarding case/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Needs review', pressed: false }))
    await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes('status=needs_review'))).toBe(true))
  })

  it('validates the create form before calling the API', async () => {
    const spy = mockApi({
      me: makeMe('reviewer'),
      handlers: [(url) => (url.includes('/applications?') ? json(200, { items: [], total: 0, limit: 20, offset: 0, application_types: [], can_create: true }) : undefined)],
    })
    renderAt('/applications')
    await userEvent.click(await screen.findByRole('button', { name: 'New application' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create application' }))
    expect(await within(dialog).findByText('Title must be at least 3 characters')).toBeInTheDocument()
    expect(spy.mock.calls.some(([u, init]) => String(u).endsWith('/applications') && init?.method === 'POST')).toBe(false)
  })

  it('offers no create action to read-only roles', async () => {
    mockApi({
      me: makeMe('auditor'),
      handlers: [(url) => (url.includes('/applications?') ? json(200, { items: [], total: 0, limit: 20, offset: 0, application_types: [], can_create: false }) : undefined)],
    })
    renderAt('/applications')
    expect(await screen.findByText('No applications yet')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New application/ })).not.toBeInTheDocument()
  })
})

describe('application workspace', () => {
  it('renders details, breadcrumb reference and server-computed actions', async () => {
    workspace('reviewer')
    renderAt('/applications/a1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Synthetic onboarding case' })).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByText('APP-2026-ABC234')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark completed' })).not.toBeInTheDocument()
    expect(screen.getByText(/Drag files here/)).toBeInTheDocument()
  })

  it('shows the application summary with its deterministic fallback and the institution', async () => {
    workspace('reviewer', makeApp({ institution: { id: 'i1', name: 'Synthetic College A', code: 'COLLEGE-A' } }))
    renderAt('/applications/a1')
    expect(await screen.findByRole('heading', { name: 'Application summary' })).toBeInTheDocument()
    expect(await screen.findByText(/No validation run exists for this application yet/)).toBeInTheDocument()
    expect(screen.getByText('Synthetic College A')).toBeInTheDocument()
    // AI is off: nothing to request, and the page says what is deterministic rather than inventing a summary.
    expect(screen.queryByRole('button', { name: /Explain with AI/ })).not.toBeInTheDocument()
  })

  it('hides upload and edit controls when the server says the user cannot edit', async () => {
    workspace('auditor', makeApp({ permissions: { can_edit: false, can_upload: false, can_manage_members: false, allowed_actions: [] }, status: 'needs_review' }))
    renderAt('/applications/a1')
    expect(await screen.findByText('You have read-only access to this application.')).toBeInTheDocument()
    expect(screen.queryByText(/Drag files here/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('shows a not-found state for applications the user cannot see', async () => {
    mockApi({ me: makeMe('reviewer'), handlers: [(url) => (url.endsWith('/applications/zz') ? apiError(404, 'not_found', 'Application not found') : undefined)] })
    renderAt('/applications/zz')
    expect(await screen.findByRole('heading', { name: 'Application not found' })).toBeInTheDocument()
  })

  it('lists documents with status, offers retry for failures, and explains missing previews', async () => {
    const failed = makeDoc({ id: 'd2', original_filename: 'broken.pdf', status: 'failed', can_retry: true })
    const tiff = makeDoc({ id: 'd3', original_filename: 'scan.tiff', detected_mime: 'image/tiff', page_count: null })
    workspace('reviewer', makeApp(), [makeDoc(), failed, tiff])
    renderAt('/applications/a1')
    expect(await screen.findByText('synthetic-statement.pdf')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Retry' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Preview scan.tiff' }))
    expect(await screen.findByText('Preview isn’t available for this format')).toBeInTheDocument()
  })

  it('keeps the auditor decision clear and filters the document inventory', async () => {
    workspace('auditor', makeApp({ status: 'completed', review_stage: 'approved', permissions: { can_edit: false, can_upload: false, can_manage_members: false, allowed_actions: [] } }), [
      makeDoc({ id: 'd1', original_filename: 'approval.pdf', status: 'needs_review' }),
      makeDoc({ id: 'd2', original_filename: 'faculty.pdf', status: 'ready' }),
    ])
    renderAt('/applications/a1')
    expect(await screen.findByText('approval.pdf')).toBeInTheDocument()
    expect(screen.getAllByText('Case approved by auditor')).toHaveLength(2)
    expect(screen.queryByText('2 need review')).not.toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Find a document' }), 'faculty')
    expect(screen.queryByText('approval.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('faculty.pdf')).toBeInTheDocument()
  })
})

describe('uploads', () => {
  it('reports real progress, sends the CSRF header, and refreshes the inventory on success', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    document.cookie = 'vf_csrf=csrf-xyz; path=/'
    const spy = workspace('reviewer')
    renderAt('/applications/a1')
    await screen.findByText(/Drag files here/)
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['%PDF-1.7 synthetic'], 'statement.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))
    const xhr = FakeXHR.instances[0]
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/v1/applications/a1/documents')
    expect(xhr.headers['X-CSRF-Token']).toBe('csrf-xyz')
    expect((xhr.body!.get('file') as File).name).toBe('statement.pdf')

    act(() => xhr.progress(512, 2048))
    expect(screen.getByRole('progressbar', { name: 'Uploading statement.pdf' })).toHaveAttribute('aria-valuenow', '25')
    act(() => xhr.progress(2048, 2048))
    expect(screen.getByText('Verifying on server…')).toBeInTheDocument()

    const docCallsBefore = spy.mock.calls.filter(([u]) => String(u).endsWith('/documents')).length
    act(() => xhr.respond(201, makeDoc()))
    expect(await screen.findByText('Uploaded')).toBeInTheDocument()
    await waitFor(() => expect(spy.mock.calls.filter(([u]) => String(u).endsWith('/documents')).length).toBeGreaterThan(docCallsBefore))
    document.cookie = 'vf_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  })

  it('shows server rejections; validation errors are final, transient errors can be retried', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    workspace('reviewer')
    renderAt('/applications/a1')
    await screen.findByText(/Drag files here/)
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['%PDF'], 'renamed.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(1))
    act(() => FakeXHR.instances[0].respond(415, { error: { code: 'extension_mismatch', message: 'The file extension “.pdf” does not match the file’s actual content (image/png).', details: null } }))
    expect(await screen.findByText(/does not match the file’s actual content/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()

    await userEvent.upload(input, new File(['%PDF'], 'second.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(2))
    act(() => FakeXHR.instances[1].respond(503, { error: { code: 'storage_unavailable', message: 'Document storage is unavailable. Nothing was saved; please retry.', details: null } }))
    expect(await screen.findByText(/Document storage is unavailable/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(FakeXHR.instances).toHaveLength(3))
  })

  it('rejects unsupported files locally without sending them', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    workspace('reviewer')
    renderAt('/applications/a1')
    await screen.findByText(/Drag files here/)
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['MZ'], 'tool.exe', { type: 'application/x-msdownload' }), { applyAccept: false })
    expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument()
    expect(FakeXHR.instances).toHaveLength(0)
  })
})
