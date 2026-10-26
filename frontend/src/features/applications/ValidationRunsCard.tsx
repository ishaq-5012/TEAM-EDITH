import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ListChecks, Play, RefreshCcwDot, ShieldCheck, ShieldX } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import { ApiError, api, errorMessage } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { RuleOutcome, ValidationRun } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'
import { RESULT_REASON, RULE_OUTCOME } from '../compliance/ruleMeta'
import { TraceView } from '../compliance/TraceView'
import { SEVERITY } from '../evidence/evidenceMeta'

const ORDER: RuleOutcome[] = ['fail', 'review', 'insufficient', 'pass', 'not_applicable']

/**
 * Validation runs evaluate every published rule version in force on the evaluation date against
 * a frozen snapshot of this application's extracted fields and evidence. Each run stores the
 * exact rule versions and inputs used, so it can be re-checked later.
 */
export function ValidationRunsCard({ applicationId, canEdit }: { applicationId: string; canEdit: boolean }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const canRun = can('validation:run') && canEdit
  const runs = useQuery({ queryKey: ['validation-runs', applicationId], queryFn: () => api.validationRuns(applicationId) })
  const [selected, setSelected] = useState<string | null>(null)
  const [date, setDate] = useState('')
  const dateId = useId()
  const current = selected ?? runs.data?.[0]?.id ?? null
  const run = useQuery({
    queryKey: ['validation-run', applicationId, current],
    queryFn: () => api.validationRun(applicationId, current as string),
    enabled: !!current,
  })
  const start = useMutation({
    mutationFn: () => api.runValidation(applicationId, date || null),
    onSuccess: (r) => {
      qc.setQueryData(['validation-run', applicationId, r.id], r)
      qc.invalidateQueries({ queryKey: ['validation-runs', applicationId] })
      setSelected(r.id)
    },
  })

  return (
    <Card>
      <CardHeader
        icon={<ListChecks className="size-4" />}
        title="Rule validation"
        description="Configured rules evaluated against extracted evidence. Results support human review; they are not legal determinations."
        action={
          canRun && (
            <div className="flex items-end gap-2">
              <label htmlFor={dateId} className="sr-only">
                Evaluation date (optional)
              </label>
              <input
                id={dateId}
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                title="Evaluation date (defaults to today)"
                className="h-8 rounded-lg border border-line-strong bg-surface px-2 text-[12.5px]"
              />
              <Button size="sm" icon={<Play className="size-3.5" aria-hidden />} onClick={() => start.mutate()} loading={start.isPending}>
                Run rules
              </Button>
            </div>
          )
        }
      />
      {start.isError && (
        <p role="alert" className="border-b border-line bg-fail-bg/50 px-5 py-2.5 text-[13px] font-medium text-fail">
          {errorMessage(start.error)}
          {start.error instanceof ApiError && start.error.code === 'no_rules_in_force' && (
            <>
              {' '}
              <Link to="/compliance" className="underline">
                Open Compliance Studio
              </Link>
            </>
          )}
        </p>
      )}
      {runs.isPending ? (
        <LoadingRows rows={2} label="Loading validation runs" />
      ) : runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
      ) : runs.data.length === 0 ? (
        <EmptyState icon={<ListChecks className="size-6" />} title="No validation runs yet">
          {canRun ? 'Run the published rules to see which pass, fail or need review, with the evidence behind each result.' : 'No one has run the rules for this application yet.'}
        </EmptyState>
      ) : (
        <div className="space-y-4 p-5">
          {runs.data.length > 1 && (
            <div className="flex flex-wrap gap-1.5" role="list" aria-label="Previous runs">
              {runs.data.map((r) => (
                <button
                  key={r.id}
                  role="listitem"
                  type="button"
                  aria-current={r.id === current || undefined}
                  onClick={() => setSelected(r.id)}
                  className={cn('rounded-lg border px-2.5 py-1 text-[12px]', r.id === current ? 'border-violet-400 bg-violet-50 text-violet-700' : 'border-line hover:bg-navy-50')}
                >
                  {formatDateTime(r.created_at)} · for {r.evaluation_date}
                </button>
              ))}
            </div>
          )}
          {run.isPending ? (
            <LoadingRows rows={3} label="Loading run" />
          ) : run.isError ? (
            <ErrorState error={run.error} onRetry={() => run.refetch()} compact />
          ) : (
            <RunView run={run.data} applicationId={applicationId} onSelect={setSelected} />
          )}
        </div>
      )}
    </Card>
  )
}

function RunView({ run, applicationId, onSelect }: { run: ValidationRun; applicationId: string; onSelect: (id: string) => void }) {
  const repro = useMutation({ mutationFn: () => api.reproduceRun(applicationId, run.id) })
  const results = [...run.results].sort((a, b) => ORDER.indexOf(a.outcome) - ORDER.indexOf(b.outcome))
  const versions = new Map(run.rule_versions.map((v) => [v.version_id, v]))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {ORDER.filter((o) => run.summary[o]).map((o) => (
          <StatusPill key={o} status={RULE_OUTCOME[o].pill}>
            {run.summary[o]} {RULE_OUTCOME[o].label.toLowerCase()}
          </StatusPill>
        ))}
        <span className="text-[12px] text-ink-subtle">
          Evaluated for {run.evaluation_date} by {run.created_by.full_name} · {formatDateTime(run.created_at)}
          {run.trigger === 'correction' && ' · revalidation after a correction'}
        </span>
        {(run.summary.fail || run.summary.review || run.summary.insufficient) ? (
          <Link to={`/review?application_id=${applicationId}`} className="ml-auto text-[12.5px] font-medium text-violet-700 hover:underline">
            Open in review queue
          </Link>
        ) : null}
      </div>
      {(run.previous_run_id || run.next_run_ids.length > 0) && (
        <p className="text-[12px] text-ink-muted">
          Run lineage:{' '}
          {run.previous_run_id ? (
            <button type="button" onClick={() => onSelect(run.previous_run_id!)} className="text-violet-700 hover:underline">
              ← previous run
            </button>
          ) : (
            'first run'
          )}
          {run.next_run_ids.map((id, i) => (
            <span key={id}>
              {' · '}
              <button type="button" onClick={() => onSelect(id)} className="text-violet-700 hover:underline">
                {run.next_run_ids.length > 1 ? `later run ${i + 1} →` : 'later run →'}
              </button>
            </span>
          ))}
        </p>
      )}
      <p className="text-[12.5px] leading-5 text-ink-muted">{run.disclaimer}</p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {results.map((r) => {
          const v = versions.get(r.rule_version_id)
          return (
            <li key={r.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <StatusPill status={RULE_OUTCOME[r.outcome].pill}>{RULE_OUTCOME[r.outcome].label}</StatusPill>
                <span className="min-w-0 flex-1 text-sm font-medium">
                  <Link to={`/compliance/rules/${r.rule_id}`} className="hover:text-violet-700 hover:underline">
                    {r.rule_name}
                  </Link>{' '}
                  <span className="font-mono text-[11.5px] font-normal text-ink-subtle">
                    {r.rule_key} v{r.version_number}
                  </span>
                </span>
                <span className="text-[12px] text-ink-muted">{SEVERITY[r.severity]} severity</span>
              </div>
              {r.message && <p className="mt-1 text-[13px]">{r.message}</p>}
              <p className="mt-0.5 text-[12px] text-ink-muted">
                {RESULT_REASON[r.reason] ?? r.reason}
                {r.details.would_have_been && ` · would have been “${RULE_OUTCOME[r.details.would_have_been].label.toLowerCase()}” with confident inputs`}
                {r.details.missing_fields?.length ? ` · missing: ${r.details.missing_fields.join(', ')}` : ''}
              </p>
              <details className="group mt-1.5">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] font-medium text-violet-700">
                  <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden /> Evidence trace
                </summary>
                <div className="mt-2 space-y-2">
                  {v && (
                    <p className="text-[12px] text-ink-muted">
                      Source: {v.source_reference || '—'} · owner {v.owner} · approved by {v.approved_by ?? '—'}
                    </p>
                  )}
                  <TraceView trace={r.trace} applicationId={applicationId} />
                </div>
              </details>
            </li>
          )
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-3 rounded-xl bg-navy-50/60 px-4 py-3 text-[12px] text-ink-muted">
        <span>
          Engine <code className="font-mono">{run.engine_version}</code>
        </span>
        <span title={run.input_fingerprint}>
          Input <code className="font-mono">{shortHash(run.input_fingerprint)}</code>
        </span>
        <span title={run.ruleset_fingerprint}>
          Rule set <code className="font-mono">{shortHash(run.ruleset_fingerprint)}</code>
        </span>
        <Button size="sm" variant="secondary" className="ml-auto" icon={<RefreshCcwDot className="size-3.5" aria-hidden />} onClick={() => repro.mutate()} loading={repro.isPending}>
          Check reproducibility
        </Button>
        {repro.isError && <span className="w-full font-medium text-fail">{errorMessage(repro.error)}</span>}
        {repro.data && (
          <span role="status" className={cn('inline-flex w-full items-center gap-1.5 font-medium', repro.data.identical ? 'text-pass' : 'text-fail')}>
            {repro.data.identical ? <ShieldCheck className="size-4" aria-hidden /> : <ShieldX className="size-4" aria-hidden />}
            {repro.data.identical
              ? 'Re-evaluating the stored snapshot with the stored rule versions gives identical results.'
              : !repro.data.snapshot_intact
                ? 'The stored snapshot or rule set no longer matches its fingerprint.'
                : `Re-evaluation differs for: ${repro.data.differences.map((d) => d.rule_key).join(', ')} (engine ${repro.data.stored_engine_version} → ${repro.data.engine_version}).`}
          </span>
        )}
      </div>
    </div>
  )
}
