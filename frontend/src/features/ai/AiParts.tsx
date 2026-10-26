import { ExternalLink, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusPill } from '../../components/ui/StatusPill'
import type { AiEgressManifest, AiEvidenceRef, AiProviderState, AiStatement } from '../../lib/types'
import { CATEGORY_LABEL, REF_KIND, SIGNAL_LABEL, evidenceHref, providerSummary } from './aiMeta'

export function ProviderBadge({ provider }: { provider: AiProviderState }) {
  const s = providerSummary(provider)
  return (
    <span title={provider.detail}>
      <StatusPill status={s.pill}>{s.label}</StatusPill>
    </span>
  )
}

export function EvidenceChip({ r }: { r: AiEvidenceRef }) {
  const href = evidenceHref(r.link)
  const body = (
    <>
      <span className="text-ink-subtle">{REF_KIND[r.kind]}:</span> {r.label}
    </>
  )
  const cls = 'inline-flex max-w-full items-center gap-1 truncate rounded-md border border-line bg-navy-50/60 px-1.5 py-0.5 text-[11.5px]'
  return href ? (
    <Link to={href} className={`${cls} text-violet-700 hover:border-violet-300 hover:underline`} title={`${REF_KIND[r.kind]} ${r.id}`}>
      {body}
      <ExternalLink className="size-3 shrink-0" aria-hidden />
    </Link>
  ) : (
    <span className={cls} title={r.id}>
      {body}
    </span>
  )
}

export function StatementList({ statements, label }: { statements: AiStatement[]; label: string }) {
  return (
    <ol aria-label={label} className="space-y-2">
      {statements.map((s, i) => (
        <li key={i} className="rounded-lg border border-line px-3 py-2">
          <p className="text-[13px] leading-6">{s.text}</p>
          <p className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Evidence">
            {s.references.map((r) => (
              <EvidenceChip key={r.id} r={r} />
            ))}
          </p>
        </li>
      ))}
    </ol>
  )
}

/** What left the environment for one request. */
export function EgressDetails({ egress }: { egress: AiEgressManifest }) {
  const withheld = egress.withheld.filter((w) => !egress.categories.includes(w))
  return (
    <details className="text-[12.5px]">
      <summary className="cursor-pointer font-medium text-violet-700">What was sent to the AI provider</summary>
      <dl className="mt-2 grid grid-cols-[130px_minmax(0,1fr)] gap-x-3 gap-y-1 text-ink-muted">
        <dt className="text-ink-subtle">Egress policy</dt>
        <dd className="font-mono">{egress.policy}</dd>
        <dt className="text-ink-subtle">Sent</dt>
        <dd>{egress.categories.map((c) => CATEGORY_LABEL[c] ?? c).join(', ') || '—'}</dd>
        <dt className="text-ink-subtle">Withheld</dt>
        <dd>{withheld.map((c) => CATEGORY_LABEL[c] ?? c).join(', ') || 'nothing'}</dd>
        <dt className="text-ink-subtle">Size</dt>
        <dd>
          {egress.chars_sent.toLocaleString()} characters{egress.truncated ? ' (cut to the configured limit)' : ''}
          {egress.pages.length > 0 && ` · pages ${egress.pages.map((p) => p.page_number).join(', ')}`}
        </dd>
        {egress.masked_values > 0 && (
          <>
            <dt className="text-ink-subtle">Masked</dt>
            <dd>{egress.masked_values} identifier value(s), last 4 characters kept</dd>
          </>
        )}
      </dl>
    </details>
  )
}

export function InjectionWarning({ egress }: { egress: AiEgressManifest }) {
  if (!egress.injection_signals.length) return null
  const signals = [...new Set(egress.injection_signals.flatMap((s) => s.signals))]
  return (
    <div role="note" className="flex gap-2 rounded-lg border border-review/25 bg-review-bg px-3 py-2 text-[12.5px] text-review">
      <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p>
        Text in the source looks like instructions aimed at an AI ({signals.map((s) => SIGNAL_LABEL[s] ?? s).join('; ')}). It was sent as data
        only: the model has no tools, its answer must match a fixed schema, and every citation and value is checked here. Treat this document
        with extra care.
      </p>
    </div>
  )
}
