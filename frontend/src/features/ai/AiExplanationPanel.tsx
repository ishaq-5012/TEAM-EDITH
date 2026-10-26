import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Info, RefreshCw, Scale, Sparkles } from 'lucide-react'
import { useId } from 'react'
import { Button } from '../../components/ui/Button'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { AiExplanation, AiSubjectType } from '../../lib/types'
import { RULE_OUTCOME } from '../compliance/ruleMeta'
import { OUTCOME, SEVERITY } from '../evidence/evidenceMeta'
import { EgressDetails, InjectionWarning, ProviderBadge, StatementList } from './AiParts'
import { DROP_REASON, INTERACTION_STATUS, REF_REJECTION, countBy, usd } from './aiMeta'

/**
 * Plain-language explanation of a result VerifyFlow already computed. The deterministic result is always shown
 * first and labelled as the one that counts; AI text, when present, is advisory and every statement links to the
 * stored evidence it cites. With AI off or failing, the deterministic explanation is shown instead.
 */
export function AiExplanationPanel({
  subjectType,
  subjectId,
  title = 'Explanation',
}: {
  subjectType: AiSubjectType
  subjectId: string
  title?: string
}) {
  const key = ['ai-explanation', subjectType, subjectId]
  const qc = useQueryClient()
  // An unexpected payload becomes an error state in this card instead of breaking the page around it.
  const q = useQuery({
    queryKey: key,
    queryFn: async () => {
      const data = await api.aiExplanation(subjectType, subjectId)
      if (!data?.deterministic || !data.provider || !data.fallback) throw new Error('Unexpected response from the AI assistance service')
      return data
    },
  })
  const ask = useMutation({
    mutationFn: (refresh: boolean) => api.requestAiExplanation(subjectType, subjectId, refresh),
    onSuccess: (data) => {
      qc.setQueryData(key, data)
      qc.invalidateQueries({ queryKey: ['ai-status'] })
    },
  })
  const titleId = useId()

  return (
    <section aria-labelledby={titleId} className="rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 id={titleId} className="flex items-center gap-2 text-[14px] font-semibold">
          <Sparkles className="size-4 text-violet-400" aria-hidden />
          {title}
        </h2>
        {q.data && (
          <div className="flex items-center gap-2">
            <ProviderBadge provider={q.data.provider} />
            {q.data.can_request && (
              <Button
                size="sm"
                variant="secondary"
                loading={ask.isPending}
                icon={q.data.ai ? <RefreshCw className="size-3.5" aria-hidden /> : <Sparkles className="size-3.5" aria-hidden />}
                onClick={() => ask.mutate(!!q.data.ai && q.data.ai.status !== 'failed')}
              >
                {q.data.ai ? 'Regenerate' : 'Explain with AI'}
              </Button>
            )}
          </div>
        )}
      </div>
      <div className="space-y-4 p-4">
        {q.isPending ? (
          <LoadingRows rows={3} label="Loading explanation" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
        ) : (
          <ExplanationBody data={q.data} />
        )}
        {ask.isError && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
            {errorMessage(ask.error)}
          </p>
        )}
      </div>
    </section>
  )
}

function Deterministic({ data }: { data: AiExplanation }) {
  const d = data.deterministic
  const pill = d.kind === 'rule_result' ? RULE_OUTCOME[d.outcome as keyof typeof RULE_OUTCOME] : OUTCOME[d.outcome as keyof typeof OUTCOME]
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/50 px-3 py-2.5 text-[13px]">
      <p className="mb-1 flex items-center gap-1.5 text-[11.5px] font-semibold tracking-[0.08em] text-violet-700 uppercase">
        <Scale className="size-3.5" aria-hidden /> Result · authoritative
      </p>
      <p className="flex flex-wrap items-center gap-2">
        {pill ? <StatusPill status={pill.pill}>{pill.label}</StatusPill> : <span className="font-mono">{d.outcome}</span>}
        <span>{SEVERITY[d.severity as keyof typeof SEVERITY] ?? d.severity} severity</span>
        {d.rule && (
          <span className="text-ink-muted">
            · {d.rule.name} v{d.rule.version_number}
            {d.rule.source_reference ? ` · source ${d.rule.source_reference}` : ''}
          </span>
        )}
        {d.group_label && <span className="text-ink-muted">· {d.group_label}</span>}
      </p>
      <p className="mt-1 text-[12px] text-ink-muted">Computed by VerifyFlow’s deterministic checks. AI never changes this result.</p>
    </div>
  )
}

function ExplanationBody({ data }: { data: AiExplanation }) {
  const ai = data.ai
  const output = ai?.output && (ai.status === 'succeeded' || ai.status === 'partial') ? ai.output : null
  const problem = data.error ?? (ai && !output ? ai.error : null)
  return (
    <>
      <Deterministic data={data} />

      {problem && (
        <p role="status" className="flex gap-2 rounded-lg bg-navy-50 px-3 py-2 text-[12.5px] text-ink-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-ink-subtle" aria-hidden />
          <span>
            {problem.message} <span className="font-mono text-[11px] text-ink-subtle">{problem.code}</span>
          </span>
        </p>
      )}
      {!data.provider.enabled && !problem && (
        <p className="text-[12.5px] text-ink-muted">{data.provider.detail}</p>
      )}

      {output && ai ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="font-semibold">AI explanation</span>
            <span title={INTERACTION_STATUS[ai.status].detail}>
              <StatusPill status={INTERACTION_STATUS[ai.status].pill}>{INTERACTION_STATUS[ai.status].label}</StatusPill>
            </span>
            {ai.stale && (
              <StatusPill status="review" icon={<AlertTriangle className="size-3.5" aria-hidden />}>
                Records changed since
              </StatusPill>
            )}
            <span className="text-ink-subtle">advisory · not a determination</span>
          </div>
          <InjectionWarning egress={ai.egress} />
          <StatementList statements={output.statements} label="AI explanation statements" />
          {output.limitations.length > 0 && (
            <div className="text-[12.5px]">
              <p className="font-medium text-ink-muted">The model noted:</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-muted">
                {output.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          )}
          <ValidationNotes validation={ai.validation} />
          <p className="text-[11.5px] text-ink-subtle">
            {ai.model ?? ai.provider} · requested by {ai.created_by.full_name} · {formatDateTime(ai.created_at)}
            {ai.cached ? ' · reused stored answer' : ''} · {ai.usage.input_tokens + ai.usage.output_tokens} tokens · {usd(ai.usage.cost_usd)}
          </p>
          <EgressDetails egress={ai.egress} />
          <details className="text-[12.5px]">
            <summary className="cursor-pointer font-medium text-violet-700">Deterministic explanation</summary>
            <div className="mt-2">
              <StatementList statements={data.fallback.statements} label="Deterministic explanation" />
            </div>
          </details>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[12.5px] font-semibold">Deterministic explanation</p>
          <StatementList statements={data.fallback.statements} label="Deterministic explanation" />
          {ai && !output && <ValidationNotes validation={ai.validation} />}
        </div>
      )}

      <details className="text-[12.5px]">
        <summary className="cursor-pointer font-medium text-ink-muted">Limitations</summary>
        <ul className="mt-1.5 list-disc space-y-1 pl-5 text-ink-muted">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </>
  )
}

function ValidationNotes({ validation }: { validation: Record<string, unknown> }) {
  const dropped = (validation.dropped_statements as { reasons: string[] }[] | undefined) ?? []
  const rejected = (validation.rejected_references as { ref: string; reason: string }[] | undefined) ?? []
  const droppedLimits = Number(validation.dropped_limitations ?? 0)
  if (!dropped.length && !rejected.length && !droppedLimits) return null
  const reasons = countBy(dropped.flatMap((d) => d.reasons))
  return (
    <div className="rounded-lg border border-line bg-navy-50/50 px-3 py-2 text-[12.5px] text-ink-muted">
      {dropped.length > 0 && (
        <p>
          Removed {dropped.length} statement{dropped.length === 1 ? '' : 's'} that{' '}
          {reasons.map(([r, n]) => `${DROP_REASON[r] ?? r}${n > 1 ? ` (${n})` : ''}`).join('; ')}.
        </p>
      )}
      {droppedLimits > 0 && <p>Removed {droppedLimits} caveat(s) that failed the content checks.</p>}
      {rejected.length > 0 && (
        <p>
          Citations rejected: {countBy(rejected.map((r) => r.reason)).map(([r, n]) => `${n} ${REF_REJECTION[r] ?? r}`).join(', ')}.
        </p>
      )}
    </div>
  )
}
