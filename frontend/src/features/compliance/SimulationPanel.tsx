import { useMutation } from '@tanstack/react-query'
import { ArrowRight, ChevronDown, FlaskRound, ShieldCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import { api, errorMessage } from '../../lib/api'
import type { Proposal, RuleDefinition, RuleDetail, RuleVersion, SimOutcome, SimulationResult } from '../../lib/types'
import { RESULT_REASON, RULE_OUTCOME, todayIso } from './ruleMeta'
import { TraceView } from './TraceView'
import { Tooltip } from '../../components/ui/Tooltip'
import { controlClass } from '../../components/ui/controlClass'

function Outcome({ o }: { o: SimOutcome }) {
  return <StatusPill status={RULE_OUTCOME[o].pill}>{RULE_OUTCOME[o].label}</StatusPill>
}

/**
 * Before/after what-if: compares the rules in force with a proposed version or an unsaved edit
 * across applications you can see. The server evaluates in memory; it never creates or changes
 * rules, versions or validation runs.
 */
export function SimulationPanel({ rule, version, unsaved }: { rule: RuleDetail; version: RuleVersion; unsaved?: RuleDefinition | null }) {
  const [source, setSource] = useState<'version' | 'unsaved'>(unsaved ? 'unsaved' : 'version')
  const [date, setDate] = useState(todayIso())
  const [onlyChanged, setOnlyChanged] = useState(false)
  const ids = { date: useId(), src: useId() }
  const sim = useMutation({
    mutationFn: () => {
      const proposal: Proposal = source === 'unsaved' && unsaved ? { rule_id: rule.id, definition: unsaved } : { rule_id: rule.id, version_id: version.id }
      return api.simulate({ proposals: [proposal], evaluation_date: date || null })
    },
  })
  const data: SimulationResult | undefined = sim.data
  const rows = data?.applications.flatMap((a) => a.rules.filter((r) => r.rule_id === rule.id).map((r) => ({ app: a, r }))) ?? []
  const changed = rows.filter((x) => x.r.changed).length
  const shown = onlyChanged ? rows.filter((x) => x.r.changed) : rows

  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-xl border border-pass/20 bg-pass-bg/50 px-4 py-3 text-[13px] text-ink-muted">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-pass" aria-hidden />
        Simulation is read-only: it never publishes, edits or retires a rule and never creates validation runs. Only the fact that you ran it is recorded in the audit log.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <span id={ids.src} className="block text-[12px] font-medium text-ink-muted">
            Proposal
          </span>
          <div role="radiogroup" aria-labelledby={ids.src} className="inline-flex rounded-lg border border-line-strong bg-surface p-0.5">
            <button type="button" role="radio" aria-checked={source === 'version'} onClick={() => setSource('version')} className={cn('rounded-md px-3 py-1.5 text-[13px] font-medium', source === 'version' ? 'bg-navy-900 text-white' : 'text-ink-muted')}>
              Stored v{version.version_number}
            </button>
            <Tooltip content={unsaved ? 'Simulate the edit currently in the editor, without saving it.' : 'There are no unsaved edits in the editor to simulate.'}>
              <button
                type="button"
                role="radio"
                aria-checked={source === 'unsaved'}
                aria-disabled={!unsaved || undefined}
                onClick={() => unsaved && setSource('unsaved')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors aria-disabled:cursor-not-allowed aria-disabled:opacity-50',
                  source === 'unsaved' ? 'bg-navy-900 text-white' : 'text-ink-muted hover:text-ink',
                )}
              >
                Unsaved edit
              </button>
            </Tooltip>
          </div>
        </div>
        <div className="space-y-1">
          <label htmlFor={ids.date} className="block text-[12px] font-medium text-ink-muted">
            Evaluation date
          </label>
          <input id={ids.date} type="date" value={date} onChange={(e) => setDate(e.target.value)} className={controlClass({ size: 'sm', full: false })} />
        </div>
        <Button icon={<FlaskRound className="size-4" aria-hidden />} onClick={() => sim.mutate()} loading={sim.isPending}>
          Run simulation
        </Button>
      </div>
      {sim.isError && (
        <p role="alert" className="text-[13px] font-medium text-fail">
          {errorMessage(sim.error)}
        </p>
      )}
      {data && (
        <section aria-label="Simulation results" className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-navy-50/50 px-4 py-3 text-[13px]">
            <span>
              <strong className="tabular-nums">{rows.length}</strong> application{rows.length === 1 ? '' : 's'} evaluated on {data.evaluation_date}
            </span>
            <span className={cn('font-semibold', changed ? 'text-review' : 'text-pass')}>
              {changed} outcome{changed === 1 ? '' : 's'} would change
            </span>
            <span className="text-ink-subtle">Side effects: {data.side_effects}</span>
            <label className="ml-auto inline-flex items-center gap-1.5 text-[12.5px]">
              <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> Only changes
            </label>
          </div>
          {shown.length === 0 ? (
            <EmptyState icon={<FlaskRound className="size-6" />} title={rows.length ? 'No outcome changes' : 'No applications to simulate'}>
              {rows.length ? 'The proposal produces the same outcome as the rules in force for every application.' : 'There are no applications visible to you.'}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {shown.map(({ app, r }) => (
                <li key={app.application_id} className={cn('px-4 py-3', r.changed && 'bg-review-bg/25')}>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <span className="min-w-48 flex-1">
                      <span className="block text-sm font-medium">{app.title}</span>
                      <span className="font-mono text-[11.5px] text-ink-subtle">{app.reference}</span>
                    </span>
                    <span className="inline-flex flex-wrap items-center gap-2">
                      <span className="text-[11.5px] text-ink-subtle">Before{r.before.version ? ` (v${r.before.version})` : ''}</span>
                      <Outcome o={r.before.outcome} />
                      <ArrowRight className="size-3.5 text-ink-subtle" aria-hidden />
                      <span className="text-[11.5px] text-ink-subtle">After ({String(r.after.version)})</span>
                      <Outcome o={r.after.outcome} />
                    </span>
                    {r.changed && <span className="rounded bg-review-bg px-1.5 py-0.5 text-[11px] font-semibold uppercase text-review">changed</span>}
                  </div>
                  {r.after.trace.length > 0 && (
                    <details className="group mt-1.5">
                      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] font-medium text-violet-700">
                        <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
                        Why: {r.after.reason ? (RESULT_REASON[r.after.reason] ?? r.after.reason) : '—'}
                      </summary>
                      <div className="mt-2">
                        <TraceView trace={r.after.trace} applicationId={app.application_id} />
                      </div>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}
