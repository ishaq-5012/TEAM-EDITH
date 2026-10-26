import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleHelp, Copy, FileSignature, Fingerprint, History, KeyRound, Settings2, ShieldQuestion } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useBreadcrumbTrail } from '../../components/layout/crumbStore'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { api, errorMessage } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { CertInfo, TrustCheck, TrustDimension, TrustVerification } from '../../lib/types'
import { TrustBadge } from './TrustBadge'
import { DIMENSION, DIMENSIONS, EVIDENCE_LABEL, TRUST_STATE } from './trustMeta'

export function DocumentTrustPage() {
  const { id = '', docId = '' } = useParams()
  const qc = useQueryClient()
  const history = useQuery({ queryKey: ['trust-history', docId], queryFn: () => api.trustHistory(id, docId) })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? history.data?.verifications[0]?.id ?? null
  const detail = useQuery({
    queryKey: ['trust-verification', current],
    queryFn: () => api.trustVerification(id, docId, current as string),
    enabled: !!current,
  })
  const verify = useMutation({
    mutationFn: () => api.verifyDocument(id, docId),
    onSuccess: (v) => {
      qc.setQueryData(['trust-verification', v.id], v)
      qc.invalidateQueries({ queryKey: ['trust-history', docId] })
      qc.invalidateQueries({ queryKey: ['trust-documents'] })
      setSelected(v.id)
    },
  })
  useBreadcrumbTrail(
    history.data
      ? [{ label: history.data.application.reference, to: `/applications/${id}` }, { label: history.data.document.original_filename }, { label: 'Trust' }]
      : undefined,
  )
  if (history.isPending) return <LoadingRows rows={6} label="Loading verification history" />
  if (history.isError) return <ErrorState error={history.error} onRetry={() => history.refetch()} />
  const h = history.data
  return (
    <PageContainer
      eyebrow={`Trust & Authentication · ${h.application.reference}`}
      title={h.document.original_filename}
      documentTitle={`Trust · ${h.document.original_filename}`}
      description={<HashLine label="SHA-256 recorded at upload" value={h.document.sha256} />}
      actions={
        h.can_verify && (
          <Button icon={<ShieldQuestion className="size-4" aria-hidden />} onClick={() => verify.mutate()} loading={verify.isPending}>
            {h.verifications.length ? 'Verify again' : 'Run verification'}
          </Button>
        )
      }
    >
      {verify.isError && (
        <p role="alert" className="rounded-xl bg-fail-bg/60 px-4 py-2.5 text-[13px] font-medium text-fail">
          {errorMessage(verify.error)}
        </p>
      )}
      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card>
            <CardHeader icon={<History className="size-4" />} title="Verification timeline" description="Every run is kept unchanged, linked to the upload hash." />
            {h.verifications.length === 0 ? (
              <p className="px-5 py-6 text-[13px] text-ink-muted">Not verified yet.{h.can_verify ? ' Run a verification to see what can and can’t be established.' : ''}</p>
            ) : (
              <ol className="relative space-y-1 p-3" aria-label="Verification runs, newest first">
                {h.verifications.map((v, i) => {
                  const active = v.id === current
                  const changed = v.observed_sha256 !== v.recorded_sha256
                  return (
                    <li key={v.id} className="relative pl-5">
                      <span aria-hidden className={cn('absolute top-3 left-1.5 size-2.5 rounded-full ring-4 ring-surface', active ? 'bg-violet-600' : 'bg-line-strong')} />
                      {i < h.verifications.length - 1 && <span aria-hidden className="absolute top-6 bottom-[-10px] left-[9px] w-px bg-line" />}
                      <button
                        type="button"
                        aria-current={active || undefined}
                        onClick={() => setSelected(v.id)}
                        className={cn('w-full rounded-lg border px-3 py-2 text-left', active ? 'border-violet-300 bg-violet-50/70' : 'border-transparent hover:bg-navy-50')}
                      >
                        <span className="block text-[13px] font-medium">{formatDateTime(v.created_at)}</span>
                        <span className="block text-[11.5px] text-ink-subtle">by {v.created_by.full_name}</span>
                        <span className="mt-1.5 flex flex-wrap gap-1">
                          {DIMENSIONS.filter((k) => v.summary[k]).map((k) => (
                            <StateDot key={k} dimension={k} state={v.summary[k]!} />
                          ))}
                        </span>
                        {changed && <span className="mt-1 block text-[11.5px] font-medium text-fail">Stored file differed from the upload</span>}
                      </button>
                    </li>
                  )
                })}
              </ol>
            )}
          </Card>
          {h.same_hash_documents.length > 0 && (
            <Card>
              <CardHeader icon={<Fingerprint className="size-4" />} title="Same file elsewhere" description="Other uploads with this exact SHA-256 (applications you can see)." />
              <ul className="space-y-1 p-4 text-[12.5px]">
                {h.same_hash_documents.map((d) => (
                  <li key={d.document_id}>
                    <Link to={`/applications/${d.application_id}/documents/${d.document_id}/trust`} className="text-violet-700 hover:underline">
                      {d.reference} · {d.filename}
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className="min-w-0">
          {!current ? (
            <Card>
              <EmptyState icon={<ShieldQuestion className="size-6" />} title="No verification yet">
                Verification checks the stored file’s SHA-256, any embedded PDF signatures, the signer’s certificate against configured trust anchors, and configured registries. Results stay in the timeline.
              </EmptyState>
            </Card>
          ) : detail.isPending ? (
            <Card>
              <LoadingRows rows={6} label="Loading verification" />
            </Card>
          ) : detail.isError ? (
            <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
          ) : (
            <VerificationDetails v={detail.data} />
          )}
        </div>
      </div>
    </PageContainer>
  )
}

function StateDot({ dimension, state }: { dimension: TrustDimension; state: keyof typeof TRUST_STATE }) {
  const color = { verified: 'bg-pass', failed: 'bg-fail', inconclusive: 'bg-review', unsupported: 'bg-missing/50' }[state]
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-line px-1.5 py-px text-[10.5px] text-ink-muted" title={`${DIMENSION[dimension].label}: ${TRUST_STATE[state].label}`}>
      <span aria-hidden className={cn('size-1.5 rounded-full', color)} />
      {DIMENSION[dimension].short}
      <span className="sr-only">: {TRUST_STATE[state].label}</span>
    </span>
  )
}

function HashLine({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1500)
    return () => clearTimeout(t)
  }, [copied])
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>{label}:</span>
      <code className="font-mono text-[12px] break-all text-white">{value}</code>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-cyan-400 hover:bg-white/10"
        onClick={() => navigator.clipboard?.writeText(value).then(() => setCopied(true), () => undefined)}
      >
        <Copy className="size-3" aria-hidden /> {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

function VerificationDetails({ v }: { v: TrustVerification }) {
  const byDim = (d: TrustDimension) => v.checks.filter((c) => c.dimension === d)
  const unknowns = [...new Set(v.checks.flatMap((c) => c.does_not_establish))]
  const open = v.checks.filter((c) => c.state === 'inconclusive' || c.state === 'unsupported')
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={`Verification of ${formatDateTime(v.created_at)}`} description={`Run by ${v.created_by.full_name}. Each question below is answered independently; there is no overall “authentic” verdict.`} />
        <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-3">
          {DIMENSIONS.map((d) => (
            <a key={d} href={`#dim-${d}`} className="block bg-surface px-4 py-3 hover:bg-navy-50/50">
              <TrustBadge state={v.summary[d]} dimension={d} />
              <span className="mt-1.5 block text-[12px] leading-5 text-ink-muted">{DIMENSION[d].question}</span>
            </a>
          ))}
        </div>
      </Card>

      <section aria-labelledby="unknowns" className="rounded-[var(--radius-card)] border border-review/30 bg-review-bg/40 p-4">
        <h2 id="unknowns" className="mb-2 flex items-center gap-2 text-[14px] font-semibold text-review">
          <CircleHelp className="size-4" aria-hidden /> What remains unknown
        </h2>
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink">
          {open.map((c) => (
            <li key={c.key}>
              <span className="font-medium">{c.label}:</span> {c.summary}
            </li>
          ))}
          {unknowns.map((u) => (
            <li key={u}>Not established by any check here: {u}.</li>
          ))}
        </ul>
      </section>

      {DIMENSIONS.map((d) => {
        const checks = byDim(d)
        return (
          <Card key={d} id={`dim-${d}`} className="scroll-mt-20">
            <CardHeader title={DIMENSION[d].label} description={DIMENSION[d].question} action={<TrustBadge state={v.summary[d]} />} />
            <div className="space-y-4 p-5">
              {checks.length === 0 ? (
                <p className="text-[13px] text-ink-muted">Not applicable to this file (for example, there is no signature to evaluate).</p>
              ) : (
                checks.map((c) => <CheckBlock key={c.key} c={c} />)
              )}
            </div>
          </Card>
        )
      })}

      {v.signatures.length > 0 && (
        <Card>
          <CardHeader icon={<FileSignature className="size-4" />} title="Embedded signatures" description="As read from the file. Certificate fields are claims made by the certificate unless certificate trust is verified." />
          <div className="space-y-4 p-5">
            {v.signatures.map((s) => (
              <div key={s.field_name} className="rounded-lg border border-line p-3 text-[13px]">
                <p className="mb-2 font-medium">
                  {s.field_name} <span className="font-normal text-ink-subtle">· {s.sub_filter ?? 'unknown format'}</span>
                </p>
                {s.signer ? <CertTable cert={s.signer} /> : <p className="text-fail">Could not be read ({s.error}).</p>}
                {s.signer_reported_time && <p className="mt-2 text-[12.5px] text-ink-muted">Signing time claimed by the signer: {formatDateTime(s.signer_reported_time)} (unverified unless a trusted timestamp is present)</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <CardHeader icon={<Settings2 className="size-4" />} title="Configuration used" description="Recorded with the run, so the result can be understood later even if configuration changes." />
        <dl className="grid grid-cols-[190px_minmax(0,1fr)] gap-x-3 gap-y-2 p-5 text-[12.5px]">
          <dt className="text-ink-subtle">Trust anchors</dt>
          <dd>{v.config.trust_anchors.length ? v.config.trust_anchors.map((a) => `${a.subject} (${shortHash(a.sha256, 12)})`).join('; ') : 'None configured'}</dd>
          <dt className="text-ink-subtle">Offline CRLs</dt>
          <dd>{v.config.crls.length || 'None'}</dd>
          <dt className="text-ink-subtle">Online revocation</dt>
          <dd>{v.config.revocation_fetching ? 'Enabled' : 'Disabled'}</dd>
          <dt className="text-ink-subtle">Registries</dt>
          <dd>{v.config.registries.length ? v.config.registries.map((r) => r.name).join('; ') : 'None configured'}</dd>
          <dt className="text-ink-subtle">Extracted fields used</dt>
          <dd>{v.config.fields_used.join(', ') || '—'}</dd>
          <dt className="text-ink-subtle">Engine</dt>
          <dd className="font-mono">{v.engine_version}</dd>
        </dl>
      </Card>
    </div>
  )
}

function CheckBlock({ c }: { c: TrustCheck }) {
  return (
    <article className={cn('rounded-xl border p-4', c.state === 'failed' ? 'border-fail/30' : 'border-line')} aria-label={c.label}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[14px] font-semibold">{c.label}</h3>
        <TrustBadge state={c.state} />
        <code className="font-mono text-[11px] text-ink-subtle">{c.code}</code>
      </div>
      <p className="mt-1.5 text-[13.5px] leading-6">{c.summary}</p>
      <dl className="mt-3 grid gap-x-4 gap-y-2.5 text-[12.5px] md:grid-cols-[150px_minmax(0,1fr)]">
        <dt className="text-ink-subtle">Method</dt>
        <dd>{c.method}</dd>
        <dt className="text-ink-subtle">Checked at</dt>
        <dd>{formatDateTime(c.checked_at)}</dd>
        {c.state === 'verified' && c.establishes && (
          <>
            <dt className="text-ink-subtle">Establishes</dt>
            <dd className="text-pass">{c.establishes}</dd>
          </>
        )}
        <dt className="text-ink-subtle">Does not establish</dt>
        <dd>
          <ul className="list-disc pl-4">
            {c.does_not_establish.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </dd>
        {c.limitations.length > 0 && (
          <>
            <dt className="text-ink-subtle">Limitations</dt>
            <dd>
              <ul className="list-disc pl-4">
                {c.limitations.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {Object.keys(c.evidence).length > 0 && (
          <>
            <dt className="text-ink-subtle">Evidence</dt>
            <dd>
              <Evidence data={c.evidence} />
            </dd>
          </>
        )}
      </dl>
    </article>
  )
}

function Evidence({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg bg-navy-50/60 p-2.5">
      {Object.entries(data).map(([k, val]) => (
        <EvidenceRow key={k} k={k} val={val} />
      ))}
    </dl>
  )
}

function EvidenceRow({ k, val }: { k: string; val: unknown }) {
  let shown: ReactNode
  if (val === null || val === undefined || val === '') shown = <span className="text-ink-subtle">—</span>
  else if (typeof val === 'boolean') shown = val ? 'yes' : 'no'
  else if (Array.isArray(val)) shown = val.length ? val.map(String).join(' → ') : <span className="text-ink-subtle">none</span>
  else if (typeof val === 'object') {
    const o = val as Record<string, unknown>
    shown = 'subject' in o && 'serial_number' in o ? <CertTable cert={o as unknown as CertInfo} /> : <Evidence data={o} />
  } else shown = <span className={cn(/sha256|fingerprint/.test(k) && 'font-mono break-all')}>{String(val)}</span>
  return (
    <>
      <dt className="text-ink-subtle">{EVIDENCE_LABEL[k] ?? k.replace(/_/g, ' ')}</dt>
      <dd className="min-w-0">{shown}</dd>
    </>
  )
}

function CertTable({ cert }: { cert: CertInfo }) {
  return (
    <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[12px]">
      <dt className="text-ink-subtle">
        <KeyRound className="mr-1 inline size-3" aria-hidden />
        Subject
      </dt>
      <dd className="break-words">{cert.subject}</dd>
      <dt className="text-ink-subtle">Issuer</dt>
      <dd className="break-words">{cert.issuer}</dd>
      <dt className="text-ink-subtle">Valid</dt>
      <dd>
        {formatDateTime(cert.not_before)} → {formatDateTime(cert.not_after)}
      </dd>
      <dt className="text-ink-subtle">Serial</dt>
      <dd className="font-mono break-all">{cert.serial_number}</dd>
      <dt className="text-ink-subtle">SHA-256</dt>
      <dd className="font-mono break-all">{cert.sha256_fingerprint}</dd>
      {cert.self_signed && (
        <>
          <dt className="text-ink-subtle">Note</dt>
          <dd className="text-review">Self-signed: anyone can create such a certificate.</dd>
        </>
      )}
    </dl>
  )
}
