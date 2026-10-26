import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { FileQuestion, Info, ListChecks, Sparkles } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { AiDocumentAssist, AiError, AiFieldSuggestion, AiInteraction } from '../../lib/types'
import { EgressDetails, InjectionWarning, ProviderBadge } from './AiParts'
import { DROP_REASON, INTERACTION_STATUS, countBy } from './aiMeta'

const COMPARISON: Record<AiFieldSuggestion['comparison'], { label: string; pill: 'pass' | 'review' | 'info' }> = {
  matches_extraction: { label: 'Matches extraction', pill: 'pass' },
  differs_from_extraction: { label: 'Differs from extraction', pill: 'review' },
  not_extracted: { label: 'Not extracted', pill: 'info' },
}

/**
 * AI suggestions for one document: a document type from a fixed list, and field values quoted from the page text.
 * Nothing here is applied: a reviewer who agrees with a suggestion corrects the field through the normal,
 * audited correction workflow.
 */
export function DocumentAssistPanel({
  applicationId,
  documentId,
  onShowField,
}: {
  applicationId: string
  documentId: string
  onShowField?: (fieldKey: string, page: number) => void
}) {
  const key = ['ai-document', documentId]
  const qc = useQueryClient()
  // An unexpected payload becomes an error state in this card instead of breaking the inspector around it.
  const q = useQuery({
    queryKey: key,
    queryFn: async () => {
      const data = await api.aiDocumentAssist(applicationId, documentId)
      if (!data?.provider || !data.fallback) throw new Error('Unexpected response from the AI assistance service')
      return data
    },
  })
  const onSuccess = (data: AiDocumentAssist) => {
    qc.setQueryData(key, data)
    qc.invalidateQueries({ queryKey: ['ai-status'] })
  }
  const classify = useMutation({ mutationFn: (refresh: boolean) => api.requestAiClassification(applicationId, documentId, refresh), onSuccess })
  const suggest = useMutation({ mutationFn: (refresh: boolean) => api.requestAiFieldSuggestions(applicationId, documentId, refresh), onSuccess })

  return (
    <Card>
      <CardHeader
        icon={<Sparkles className="size-4" />}
        title="AI suggestions"
        description="Advisory only. Suggestions are never applied; correct a field yourself if you agree."
        action={q.data && <ProviderBadge provider={q.data.provider} />}
      />
      <div className="space-y-5 p-4">
        {q.isPending ? (
          <LoadingRows rows={3} label="Loading AI suggestions" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
        ) : (
          <>
            {!q.data.provider.enabled ? (
              <p className="flex gap-2 text-[12.5px] text-ink-muted">
                <Info className="mt-0.5 size-4 shrink-0 text-ink-subtle" aria-hidden /> {q.data.provider.detail}
              </p>
            ) : (
              !q.data.egress_allows_page_text && (
                <p className="flex gap-2 rounded-lg bg-navy-50 px-3 py-2 text-[12.5px] text-ink-muted">
                  <Info className="mt-0.5 size-4 shrink-0 text-ink-subtle" aria-hidden />
                  These tasks need page text to leave this environment, and the data-egress policy doesn’t allow that. An administrator can
                  change VERIFYFLOW_AI_DOCUMENT_EGRESS.
                </p>
              )
            )}

            <Task
              title="Document type"
              icon={<FileQuestion className="size-4 text-violet-400" aria-hidden />}
              canRun={q.data.can_request && q.data.egress_allows_page_text}
              running={classify.isPending}
              hasResult={!!q.data.classification}
              onRun={(refresh) => classify.mutate(refresh)}
              error={classify.isError ? errorMessage(classify.error) : null}
              apiError={q.data.classification_error}
            >
              <p className="text-[12.5px] text-ink-muted">
                Declared at upload: <span className="font-medium text-ink">{q.data.fallback.document_type ?? 'not declared'}</span>
              </p>
              {q.data.classification && <Classification row={q.data.classification} />}
            </Task>

            <Task
              title="Field suggestions"
              icon={<ListChecks className="size-4 text-violet-400" aria-hidden />}
              canRun={q.data.can_request && q.data.egress_allows_page_text}
              running={suggest.isPending}
              hasResult={!!q.data.field_suggestions}
              onRun={(refresh) => suggest.mutate(refresh)}
              error={suggest.isError ? errorMessage(suggest.error) : null}
              apiError={q.data.field_suggestions_error}
            >
              {q.data.field_suggestions ? (
                <Suggestions row={q.data.field_suggestions} onShowField={onShowField} />
              ) : (
                <p className="text-[12.5px] text-ink-muted">{q.data.fallback.fields}</p>
              )}
            </Task>

            <details className="text-[12.5px]">
              <summary className="cursor-pointer font-medium text-ink-muted">Limitations</summary>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-ink-muted">
                {q.data.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      </div>
    </Card>
  )
}

function Task({
  title,
  icon,
  canRun,
  running,
  hasResult,
  onRun,
  error,
  apiError,
  children,
}: {
  title: string
  icon: ReactNode
  canRun: boolean
  running: boolean
  hasResult: boolean
  onRun: (refresh: boolean) => void
  error: string | null
  apiError: AiError | null
  children: ReactNode
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[13.5px] font-semibold">
          {icon} {title}
        </h3>
        {canRun && (
          <Button size="sm" variant="secondary" loading={running} onClick={() => onRun(hasResult)}>
            {hasResult ? 'Ask again' : 'Ask AI'}
          </Button>
        )}
      </div>
      {(error || apiError) && (
        <p role="status" className="rounded-lg bg-navy-50 px-3 py-2 text-[12.5px] text-ink-muted">
          {error ?? apiError?.message} {apiError && <span className="font-mono text-[11px] text-ink-subtle">{apiError.code}</span>}
        </p>
      )}
      {children}
    </section>
  )
}

function RowMeta({ row }: { row: AiInteraction<unknown> }) {
  const st = INTERACTION_STATUS[row.status]
  return (
    <p className="flex flex-wrap items-center gap-2 text-[11.5px] text-ink-subtle">
      <span title={st.detail}>
        <StatusPill status={st.pill}>{st.label.replace('All citations verified', 'Checked')}</StatusPill>
      </span>
      {row.model ?? row.provider} · {row.created_by.full_name} · {formatDateTime(row.created_at)}
      {row.cached ? ' · reused stored answer' : ''}
    </p>
  )
}

function Classification({ row }: { row: NonNullable<AiDocumentAssist['classification']> }) {
  const o = row.output
  return (
    <div className="space-y-2 rounded-lg border border-line px-3 py-2">
      <RowMeta row={row} />
      {row.error && <p className="text-[12.5px] text-ink-muted">{row.error.message}</p>}
      {o && (
        <>
          <p className="text-[13px]">
            Suggested type: <span className="font-semibold">{o.document_type_label}</span>{' '}
            <span className="text-ink-muted">({o.confidence} confidence)</span>
            {o.agrees_with_declared === false && <span className="text-review"> · differs from the declared type</span>}
          </p>
          {o.rationale && <p className="text-[12.5px] text-ink-muted">{o.rationale}</p>}
          {o.evidence_pages.length > 0 && <p className="text-[12px] text-ink-subtle">Based on page {o.evidence_pages.join(', ')}</p>}
          {Array.isArray(row.validation.rationale_dropped) && row.validation.rationale_dropped.length > 0 && (
            <p className="text-[12px] text-ink-muted">
              The model’s rationale was removed because it {(row.validation.rationale_dropped as string[]).map((r) => DROP_REASON[r] ?? r).join('; ')}.
            </p>
          )}
        </>
      )}
      <InjectionWarning egress={row.egress} />
      <EgressDetails egress={row.egress} />
    </div>
  )
}

function Suggestions({ row, onShowField }: { row: NonNullable<AiDocumentAssist['field_suggestions']>; onShowField?: (k: string, p: number) => void }) {
  const items = row.output?.suggestions ?? []
  const dropped = (row.validation.dropped_suggestions as { reason: string }[] | undefined) ?? []
  return (
    <div className="space-y-2">
      <RowMeta row={row} />
      {row.error && <p className="text-[12.5px] text-ink-muted">{row.error.message}</p>}
      <InjectionWarning egress={row.egress} />
      {row.output && items.length === 0 && <p className="text-[12.5px] text-ink-muted">The model found no values it could quote from the text.</p>}
      <ul className="space-y-2">
        {items.map((s, i) => (
          <li key={`${s.field_key}-${i}`} className="rounded-lg border border-line px-3 py-2 text-[12.5px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-[13px]">{s.label}</span>
              <StatusPill status={COMPARISON[s.comparison].pill}>{COMPARISON[s.comparison].label}</StatusPill>
            </div>
            <p className="mt-1">
              Suggested <span className="font-mono">{s.value}</span>
              {s.normalized_value && s.normalized_value !== s.value && <span className="text-ink-muted"> → <span className="font-mono">{s.normalized_value}</span></span>}
              {s.comparison === 'differs_from_extraction' && s.current_value && (
                <span className="text-ink-muted">
                  {' '}
                  · current <span className="font-mono">{s.current_value}</span>
                </span>
              )}
            </p>
            <p className="mt-0.5 text-ink-subtle">
              Quoted from page {s.page_number}: “{s.quoted_text}”
            </p>
            {s.normalization_note && <p className="mt-0.5 text-ink-subtle">{s.normalization_note}</p>}
            {onShowField && (
              <button type="button" className="mt-1 text-[12px] font-medium text-violet-700 hover:underline" onClick={() => onShowField(s.field_key, s.page_number)}>
                Show field and page
              </button>
            )}
          </li>
        ))}
      </ul>
      {dropped.length > 0 && (
        <p className="text-[12px] text-ink-muted">
          Removed {dropped.length} suggestion{dropped.length === 1 ? '' : 's'} that {countBy(dropped.map((d) => d.reason)).map(([r, n]) => `${DROP_REASON[r] ?? r}${n > 1 ? ` (${n})` : ''}`).join('; ')}.
        </p>
      )}
      <EgressDetails egress={row.egress} />
    </div>
  )
}
