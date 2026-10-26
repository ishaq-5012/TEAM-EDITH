import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../features/auth/AuthProvider'
import { TrustBadge } from '../features/trust/TrustBadge'
import type { TrustCheck, TrustHistory, TrustState, TrustVerification } from '../lib/types'
import { json, makeMe, mockApi } from './fixtures'

const me = { id: 'u1', full_name: 'Ada Example', email: 'reviewer@example.com' }
const SHA = 'a'.repeat(64)
const appRef = { id: 'a1', reference: 'APP-2026-AAA111', title: 'Synthetic case', status: 'needs_review' as const }
const doc = { id: 'd1', application_id: 'a1', original_filename: 'signed.pdf', detected_mime: 'application/pdf', size_bytes: 7000, sha256: SHA, created_at: '2026-10-23T00:00:00Z' }

function check(over: Partial<TrustCheck>): TrustCheck {
  return {
    dimension: 'file_integrity', key: 'file_integrity', label: 'Stored file integrity', state: 'verified', code: 'hash_match',
    method: 'SHA-256 of the stored bytes', summary: 'The stored file matches the SHA-256 recorded at upload.',
    establishes: 'The stored file is byte-for-byte the file that was uploaded.',
    does_not_establish: ['who created or issued the document', "that the document's contents are true"], limitations: [],
    evidence: { recorded_sha256: SHA, observed_sha256: SHA }, subject: null, checked_at: '2026-10-23T00:00:00Z', ...over,
  }
}

function run(over: Partial<TrustVerification> = {}): TrustVerification {
  return {
    id: 'v1', application_id: 'a1', document_id: 'd1', recorded_sha256: SHA, observed_sha256: SHA, engine_version: 'verifyflow-trust/1.0 pyHanko/0.38.0',
    created_by: me, created_at: '2026-10-23T00:00:00Z',
    summary: { file_integrity: 'verified', signature_integrity: 'verified', certificate_trust: 'inconclusive', revocation: 'unsupported', timestamp: 'inconclusive', external_registry: 'unsupported' },
    config: { trust_anchors: [], crls: [], problems: [], revocation_fetching: false, registries: [], fields_used: [] },
    checks: [
      check({}),
      check({ dimension: 'signature_integrity', key: 'signature_integrity:Signature1', label: 'Signature “Signature1”', code: 'intact_entire_file', summary: 'The signature is intact and covers the entire file.', establishes: 'The signed bytes are exactly the bytes that were signed.', evidence: { coverage: 'ENTIRE_FILE', intact: true } }),
      check({ dimension: 'certificate_trust', key: 'certificate_trust:Signature1', label: 'Signer certificate of “Signature1”', state: 'inconclusive', code: 'no_trust_anchors_configured', summary: 'No trust anchors are configured, so the signer’s identity can’t be confirmed.', establishes: '' }),
      check({ dimension: 'revocation', key: 'revocation:Signature1', label: 'Revocation status', state: 'unsupported', code: 'revocation_not_configured', summary: 'Whether the certificate was revoked is unknown.', establishes: '' }),
    ],
    signatures: [{ field_name: 'Signature1', sub_filter: '/adbe.pkcs7.detached', signer: { subject: 'Common Name: Synthetic Signer', issuer: 'Common Name: SYNTHETIC TEST ROOT', serial_number: 'ab', not_before: '2026-01-01T00:00:00Z', not_after: '2027-01-01T00:00:00Z', sha256_fingerprint: 'b'.repeat(64), self_signed: false } }],
    ...over,
  }
}

function history(over: Partial<TrustHistory> = {}): TrustHistory {
  const r = run()
  return { application: appRef, document: doc, verifications: [{ id: r.id, recorded_sha256: SHA, observed_sha256: SHA, summary: r.summary, created_by: me, created_at: r.created_at }], same_hash_documents: [], can_verify: true, ...over }
}

function setup(role: 'reviewer' | 'auditor', routes: Record<string, (n: number) => Response>) {
  const calls: { method: string; path: string }[] = []
  const counts: Record<string, number> = {}
  mockApi({
    me: makeMe(role),
    handlers: [
      (url, init) => {
        const path = url.replace(/^.*\/api\/v1/, '').split('?')[0]
        const method = (init.method ?? 'GET').toUpperCase()
        calls.push({ method, path })
        const key = `${method} ${path}`
        counts[key] = (counts[key] ?? 0) + 1
        return routes[key]?.(counts[key])
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

const DOC_URL = '/applications/a1/documents/d1/verifications'

describe('trust badge', () => {
  it.each<[TrustState, boolean]>([
    ['verified', true],
    ['failed', false],
    ['inconclusive', false],
    ['unsupported', false],
  ])('%s is green only when verified', (state, green) => {
    const { container } = render(<TrustBadge state={state} dimension="certificate_trust" />)
    expect(container.innerHTML.includes('bg-pass')).toBe(green)
    if (state === 'unsupported') expect(container).toHaveTextContent('not checked')
  })

  it('shows not applicable when a dimension has no check', () => {
    const { container } = render(<TrustBadge state={undefined} dimension="timestamp" />)
    expect(container).toHaveTextContent('Timestamp: n/a')
    expect(container.innerHTML.includes('bg-pass')).toBe(false)
  })
})

describe('trust center', () => {
  it('separates implemented capabilities from those needing external infrastructure', async () => {
    setup('reviewer', {
      'GET /trust/capabilities': () =>
        json(200, {
          engine_version: 'verifyflow-trust/1.0', statement: 'A matching hash means the stored file is unchanged since upload, not that its issuer is authentic.',
          trust_material: { trust_anchors: [], crls: [], problems: ['roots.pem: not a valid X.509 certificate'] }, registries: [],
          capabilities: [
            { key: 'file_integrity', label: 'SHA-256 file integrity', status: 'enabled', requires_external: false, detail: 'Re-hashes the stored file.' },
            { key: 'certificate_trust', label: 'Certificate chain to configured trust anchors', status: 'not_configured', requires_external: true, detail: 'No trust anchors configured.' },
            { key: 'ltv', label: 'Long-term validation', status: 'not_implemented', requires_external: true, detail: 'Not implemented.' },
          ],
        }),
      'GET /trust/documents': () => json(200, { items: [{ document: doc, application: appRef, latest: null }], total: 1, limit: 100, offset: 0 }),
    })
    renderAt('/trust')
    expect(await screen.findByText(/not that its issuer is authentic/)).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.getByText('Not implemented')).toBeInTheDocument()
    expect(screen.getAllByText('needs external infrastructure')).toHaveLength(2)
    expect(screen.getByRole('alert')).toHaveTextContent('not a valid X.509 certificate')
    expect(await screen.findByText('Never verified')).toBeInTheDocument()
  })
})

describe('document verification', () => {
  it('shows the timeline, each dimension separately, and what remains unknown', async () => {
    setup('reviewer', { [`GET ${DOC_URL}`]: () => json(200, history()), [`GET ${DOC_URL}/v1`]: () => json(200, run()) })
    renderAt('/applications/a1/documents/d1/trust')
    expect(await screen.findByText(/there is no overall “authentic” verdict/)).toBeInTheDocument()
    const unknown = screen.getByRole('region', { name: 'What remains unknown' })
    expect(unknown).toHaveTextContent('signer’s identity can’t be confirmed')
    expect(unknown).toHaveTextContent('Whether the certificate was revoked is unknown')
    expect(unknown).toHaveTextContent("Not established by any check here: that the document's contents are true.")
    // "Establishes" is stated only for verified checks.
    const trust = screen.getByRole('article', { name: 'Signer certificate of “Signature1”' })
    expect(within(trust).queryByText('Establishes')).not.toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Stored file integrity' })).getByText('Establishes')).toBeInTheDocument()
    expect(screen.getByText('Common Name: Synthetic Signer')).toBeInTheDocument()
    expect(screen.getAllByText(SHA).length).toBeGreaterThan(0)
  })

  it('runs a verification and shows the new run; flags a stored file that differs from the upload', async () => {
    const altered = run({
      id: 'v2', observed_sha256: 'c'.repeat(64), summary: { file_integrity: 'failed', signature_integrity: 'inconclusive', external_registry: 'unsupported' },
      checks: [check({ state: 'failed', code: 'hash_mismatch', summary: 'The stored file no longer matches the hash recorded at upload.', establishes: '' })], signatures: [],
    })
    const calls = setup('reviewer', {
      [`GET ${DOC_URL}`]: (n) =>
        json(200, n === 1 ? history({ verifications: [] }) : history({ verifications: [{ id: 'v2', recorded_sha256: SHA, observed_sha256: 'c'.repeat(64), summary: altered.summary, created_by: me, created_at: '2026-10-23T01:00:00Z' }] })),
      [`POST ${DOC_URL}`]: () => json(201, altered),
    })
    renderAt('/applications/a1/documents/d1/trust')
    await userEvent.click(await screen.findByRole('button', { name: 'Run verification' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1))
    expect(await screen.findByText('Stored file differed from the upload')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Verify again' })).toBeInTheDocument())
  })

  it('is read-only for auditors', async () => {
    setup('auditor', { [`GET ${DOC_URL}`]: () => json(200, history({ can_verify: false })), [`GET ${DOC_URL}/v1`]: () => json(200, run()) })
    renderAt('/applications/a1/documents/d1/trust')
    expect(await screen.findByText(/there is no overall/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Verify again|Run verification/ })).not.toBeInTheDocument()
  })
})
