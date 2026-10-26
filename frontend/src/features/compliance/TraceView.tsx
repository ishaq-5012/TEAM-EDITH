import { CheckCircle2, CircleDashed, ExternalLink, FileText, Network, PencilLine, ScanSearch, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '../../components/ui/cn'
import type { Observation, TraceEntry } from '../../lib/types'
import { useRuleCatalog } from './queries'
import { formatValue, opPhrase } from './ruleMeta'

function ResultIcon({ result }: { result: boolean | null | undefined }) {
  if (result === true) return <CheckCircle2 className="size-3.5 text-pass" aria-label="holds" />
  if (result === false) return <XCircle className="size-3.5 text-fail" aria-label="does not hold" />
  return <CircleDashed className="size-3.5 text-missing" aria-label="unknown: no usable data" />
}

/**
 * Rule-to-evidence trace: each leaf condition with the exact observations it was evaluated on.
 * For real applications every extracted value links back to its document, page and field.
 */
export function TraceView({ trace, applicationId }: { trace: TraceEntry[]; applicationId?: string }) {
  const catalog = useRuleCatalog()
  const label = (ref: string) => catalog.data?.fields.find((f) => f.ref === ref)?.label ?? ref
  if (!trace.length) return <p className="text-[13px] text-ink-subtle">No conditions were evaluated.</p>
  return (
    <ol className="space-y-2">
      {trace.map((t, i) => (
        <li key={`${t.path}-${i}`} className="rounded-lg border border-line bg-surface">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-3 py-2 text-[13px]">
            <ResultIcon result={t.result} />
            <span className="font-medium">{label(t.field)}</span>
            {t.field.startsWith('extracted.') && <span className="text-ink-subtle">({t.quantifier === 'any' ? 'at least one document' : 'every document'})</span>}
            <span className="text-ink-muted">{opPhrase(t.op, t.expected)}</span>
            <code className="ml-auto font-mono text-[11px] text-ink-subtle">{t.path}</code>
          </div>
          {t.missing || t.observations.length === 0 ? (
            <p className="px-3 py-2 text-[12.5px] text-ink-muted">
              {t.op === 'exists' || t.op === 'not_exists' ? 'No usable value found in any document.' : 'No usable value: treated as missing data, not as a mismatch.'}
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {t.observations.map((o, j) => (
                <ObservationRow key={j} o={o} applicationId={applicationId} />
              ))}
            </ul>
          )}
          {t.low_confidence && <p className="border-t border-line bg-review-bg/50 px-3 py-1.5 text-[12px] text-review">At least one input is low confidence.</p>}
        </li>
      ))}
    </ol>
  )
}

function ObservationRow({ o, applicationId }: { o: Observation; applicationId?: string }) {
  const satisfied = o.satisfied
  const synthetic = !!o.document_id?.startsWith('synthetic-')
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[12.5px]">
      {satisfied !== undefined && <ResultIcon result={satisfied} />}
      {o.kind === 'extracted' ? (
        <>
          <span className="inline-flex items-center gap-1 text-ink-muted">
            <FileText className="size-3.5" aria-hidden />
            {o.document_name ?? 'Document'}
            {synthetic && <span className="rounded bg-info-bg px-1 text-[10.5px] font-semibold uppercase text-info">test</span>}
          </span>
          <span className="font-mono text-ink">{formatValue(o.value)}</span>
          {o.raw_value && o.raw_value !== o.value && <span className="text-ink-subtle">raw “{o.raw_value}”</span>}
          {o.value_source === 'correction' && (
            <span className="inline-flex items-center gap-0.5 text-violet-700">
              <PencilLine className="size-3" aria-hidden /> human-corrected
            </span>
          )}
          {o.page_number && <span className="text-ink-subtle">page {o.page_number}</span>}
          <QualityTag q={o.quality} />
          {applicationId && o.document_id && !synthetic && (
            <Link
              to={`/applications/${applicationId}/documents/${o.document_id}?${new URLSearchParams({ page: String(o.page_number ?? 1), field: o.field_key ?? '' })}`}
              className="ml-auto inline-flex items-center gap-1 font-medium text-violet-700 hover:underline"
              aria-label={`Open source: ${o.document_name ?? 'document'}, page ${o.page_number ?? 1}${o.field_key ? `, ${o.field_key}` : ''}`}
            >
              <ScanSearch className="size-3.5" aria-hidden /> Open source
            </Link>
          )}
        </>
      ) : o.kind === 'evidence' ? (
        <>
          <span className="inline-flex items-center gap-1 text-ink-muted">
            <Network className="size-3.5" aria-hidden /> Evidence finding
          </span>
          <span className="font-mono">{formatValue(o.value)}</span>
          {o.stale && <span className="text-review">analysis is stale</span>}
          <QualityTag q={o.quality} />
          {applicationId && o.finding_id && (
            <Link to={`/applications/${applicationId}/evidence`} className="ml-auto inline-flex items-center gap-1 font-medium text-violet-700 hover:underline">
              <ExternalLink className="size-3.5" aria-hidden /> Evidence graph
            </Link>
          )}
        </>
      ) : (
        <>
          <span className="text-ink-muted">Application {o.attribute?.replace(/_/g, ' ')}</span>
          <span className="font-mono">{formatValue(o.value)}</span>
        </>
      )}
    </li>
  )
}

function QualityTag({ q }: { q: string }) {
  return (
    <span className={cn('rounded px-1.5 py-px text-[11px] font-medium', q === 'low' ? 'bg-review-bg text-review' : 'bg-navy-50 text-ink-muted')}>
      {q} quality
    </span>
  )
}
