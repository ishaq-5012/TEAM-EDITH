import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FlaskConical, Play, Plus, Trash2 } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Select, TextField } from '../../components/ui/Field'
import { EmptyState } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import { ApiError, api, errorMessage } from '../../lib/api'
import type { RuleDefinition, RuleDetail, RuleOutcome, RuleVersion, TestRun } from '../../lib/types'
import { locText, RESULT_REASON, RULE_OUTCOME, synthCaseTemplate, todayIso, versionLabel } from './ruleMeta'
import { TraceView } from './TraceView'

const OUTCOMES: RuleOutcome[] = ['pass', 'fail', 'review', 'insufficient', 'not_applicable']

/**
 * Synthetic test cases: invented inputs with an expected outcome. Every case must declare
 * `"synthetic": true`, and a version cannot be submitted for approval while any case fails.
 */
export function TestCasesPanel({
  rule,
  version,
  canManage,
  unsaved,
}: {
  rule: RuleDetail
  version: RuleVersion
  canManage: boolean
  /** The editor's current definition when it differs from the stored draft. */
  unsaved?: RuleDefinition | null
}) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [run, setRun] = useState<{ label: string; result: TestRun } | null>(null)
  const runStored = useMutation({
    mutationFn: () => api.testVersion(rule.id, version.id),
    onSuccess: (result) => setRun({ label: `stored ${versionLabel(version)}`, result }),
  })
  const runUnsaved = useMutation({
    mutationFn: () => api.testDefinition(rule.id, unsaved as RuleDefinition),
    onSuccess: (result) => setRun({ label: 'unsaved edit', result }),
  })
  const remove = useMutation({
    mutationFn: (caseId: string) => api.deleteTestCase(rule.id, caseId),
    onSuccess: () => {
      setRun(null)
      qc.invalidateQueries({ queryKey: ['rule', rule.id] })
    },
  })
  const failing = run?.result.results.filter((r) => !r.passed).length ?? 0
  const err = runStored.error ?? runUnsaved.error ?? remove.error

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" icon={<Play className="size-3.5" aria-hidden />} onClick={() => runStored.mutate()} loading={runStored.isPending} disabled={!rule.test_cases.length}>
          Run against {versionLabel(version)}
        </Button>
        {unsaved && (
          <Button size="sm" variant="secondary" icon={<Play className="size-3.5" aria-hidden />} onClick={() => runUnsaved.mutate()} loading={runUnsaved.isPending} disabled={!rule.test_cases.length}>
            Run against unsaved edit
          </Button>
        )}
        {canManage && (
          <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => setAdding(true)} className="ml-auto">
            Add test case
          </Button>
        )}
      </div>
      {err && (
        <p role="alert" className="text-[13px] font-medium text-fail">
          {errorMessage(err)}
        </p>
      )}
      {run && (
        <div
          role="status"
          className={cn('rounded-lg px-3 py-2 text-[13px] font-medium', failing ? 'bg-fail-bg text-fail' : 'bg-pass-bg text-pass')}
        >
          {run.result.passed} of {run.result.total} cases match their expected outcome ({run.label}).
          {failing > 0 && ' Fix the rule or the expectation before submitting.'}
        </div>
      )}
      {rule.test_cases.length === 0 ? (
        <EmptyState icon={<FlaskConical className="size-6" />} title="No test cases yet">
          Add test cases with invented records and expected outcomes. Every existing case must pass before a version can be submitted.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {rule.test_cases.map((tc) => {
            const r = run?.result.results.find((x) => x.test_case_id === tc.id)
            return (
              <li key={tc.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1 text-sm font-medium">{tc.name}</span>
                  <span className="text-[12px] text-ink-subtle">expects</span>
                  <StatusPill status={RULE_OUTCOME[tc.expected_outcome].pill}>{RULE_OUTCOME[tc.expected_outcome].label}</StatusPill>
                  {r && (
                    <>
                      <span className="text-[12px] text-ink-subtle">got</span>
                      <StatusPill status={RULE_OUTCOME[r.actual].pill}>{RULE_OUTCOME[r.actual].label}</StatusPill>
                      <span className={cn('text-[12px] font-semibold', r.passed ? 'text-pass' : 'text-fail')}>{r.passed ? '✓ matches' : '✗ mismatch'}</span>
                    </>
                  )}
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => remove.mutate(tc.id)}
                      disabled={remove.isPending}
                      className="rounded-md p-1 text-ink-subtle hover:bg-fail-bg hover:text-fail"
                      aria-label={`Delete test case ${tc.name}`}
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </button>
                  )}
                </div>
                {tc.description && <p className="mt-0.5 text-[12.5px] text-ink-muted">{tc.description}</p>}
                <details className="group mt-1.5">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] font-medium text-violet-700">
                    <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
                    {r ? `Trace · ${RESULT_REASON[r.reason] ?? r.reason}` : 'Test input'}
                  </summary>
                  <div className="mt-2 space-y-2">
                    {r && <TraceView trace={r.trace} />}
                    <pre className="max-h-56 overflow-auto rounded-lg bg-navy-950 p-3 font-mono text-[11.5px] leading-5 text-navy-50">{JSON.stringify(tc.case, null, 2)}</pre>
                  </div>
                </details>
              </li>
            )
          })}
        </ul>
      )}
      {adding && <AddCaseDialog ruleId={rule.id} onClose={() => setAdding(false)} onAdded={() => setRun(null)} />}
    </div>
  )
}

function AddCaseDialog({ ruleId, onClose, onAdded }: { ruleId: string; onClose: () => void; onAdded: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [expected, setExpected] = useState<RuleOutcome>('pass')
  const [text, setText] = useState(() => synthCaseTemplate(todayIso()))
  const [localError, setLocalError] = useState<string | null>(null)
  const ids = { exp: useId(), json: useId() }
  const add = useMutation({
    mutationFn: (body: { name: string; case: unknown; expected_outcome: RuleOutcome }) => api.addTestCase(ruleId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rule', ruleId] })
      onAdded()
      onClose()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    if (name.trim().length < 3) return setLocalError('Give the case a name of at least 3 characters.')
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return setLocalError('The case is not valid JSON.')
    }
    add.mutate({ name: name.trim(), case: parsed, expected_outcome: expected })
  }
  const serverDetails = add.error instanceof ApiError && Array.isArray(add.error.details) ? (add.error.details as { loc?: unknown; msg?: string }[]) : []
  return (
    <Dialog open onClose={onClose} title="Add test case" description="Use invented records only. Include the required test marker in the JSON." width="max-w-2xl">
      <form className="space-y-4" onSubmit={submit} noValidate>
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_200px]">
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Adult applicant passes" />
          <div className="space-y-1.5">
            <label htmlFor={ids.exp} className="block text-[13px] font-medium">
              Expected outcome
            </label>
            <Select id={ids.exp} value={expected} onChange={(e) => setExpected(e.target.value as RuleOutcome)} >
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {RULE_OUTCOME[o].label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={ids.json} className="block text-[13px] font-medium">
            Test input (JSON)
          </label>
          <textarea
            id={ids.json}
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="block min-h-64 w-full rounded-xl border border-navy-800 bg-navy-950 p-3 font-mono text-[12px] leading-5 text-navy-50 focus:outline-none focus:ring-4 focus:ring-violet-100"
          />
          <p className="text-[12px] text-ink-subtle">
            Fields: <code>value</code>, <code>status</code> (found | missing | invalid | ambiguous), <code>quality</code> (high | medium | low), <code>source</code> (extracted | correction). Optional{' '}
            <code>evidence</code>: {'{ group: { outcome, quality } }'}.
          </p>
        </div>
        {(localError || add.isError) && (
          <div role="alert" className="rounded-lg bg-fail-bg/70 px-3 py-2 text-[13px] text-fail">
            <p className="font-medium">{localError ?? errorMessage(add.error)}</p>
            {!localError && serverDetails.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-[12.5px]">
                {serverDetails.map((d, i) => (
                  <li key={i}>
                    {locText(d.loc) && `${locText(d.loc)}: `}
                    {d.msg}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={add.isPending}>
            Add case
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
