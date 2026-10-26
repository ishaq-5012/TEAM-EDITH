import { AlertTriangle, Braces, CheckCircle2, Filter, ListTree, Loader2, X } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { cn } from '../../components/ui/cn'
import { errorMessage } from '../../lib/api'
import type { DefinitionCheck, LowConfidencePolicy, MissingDataPolicy, RuleCatalog, RuleDefinition, Severity } from '../../lib/types'
import { SEVERITY } from '../evidence/evidenceMeta'
import { ConditionBuilder } from './ConditionBuilder'
import { cleanDefinition, LOW_CONFIDENCE_POLICY, MISSING_POLICY, newLeaf } from './ruleMeta'
import { Tooltip } from '../../components/ui/Tooltip'
import { controlClass } from '../../components/ui/controlClass'
import { Select } from '../../components/ui/Field'

const select = controlClass({ size: 'sm' })

export function CheckPanel({
  check,
  pending,
  error,
}: {
  check: DefinitionCheck | undefined
  pending: boolean
  error: unknown
}) {
  return (
    <section aria-live="polite" aria-label="Rule check" className="rounded-xl border border-line bg-navy-50/50 p-4">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-subtle">
        Readable summary
        {pending && <Loader2 className="size-3.5 animate-spin" aria-label="Checking" />}
      </div>
      {error ? (
        <p className="text-[13px] text-fail">Couldn’t check the rule: {errorMessage(error)}</p>
      ) : !check ? (
        <p className="text-[13px] text-ink-subtle">Checking…</p>
      ) : check.valid && check.summary ? (
        <div className="space-y-2.5 text-[13.5px] leading-6">
          <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-pass">
            <CheckCircle2 className="size-3.5" aria-hidden /> Valid rule definition
          </p>
          <p>
            <span className="font-medium text-ink-muted">Applies: </span>
            {check.summary.applies_when}
          </p>
          <p>
            <span className="font-medium text-ink-muted">Passes when: </span>
            <span className="whitespace-pre-wrap">{check.summary.condition}</span>
          </p>
          <p className="text-[12.5px] text-ink-muted">{check.summary.policies}</p>
        </div>
      ) : (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-medium text-fail">
            <AlertTriangle className="size-3.5" aria-hidden /> {check.errors.length === 1 ? '1 problem' : `${check.errors.length} problems`} to fix
          </p>
          <ul className="space-y-1 text-[13px]">
            {check.errors.map((e, i) => (
              <li key={i} className="rounded-md bg-fail-bg/60 px-2 py-1">
                {e.loc && <code className="mr-1.5 font-mono text-[11.5px] text-ink-muted">{e.loc}</code>}
                {e.msg}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

/**
 * Edits a rule definition through a structured builder, or as JSON. Both produce the same
 * declarative document; nothing typed here is executed — the server validates it against the
 * operator allowlist and field catalog.
 */
export function DefinitionEditor({
  catalog,
  definition,
  onChange,
  readOnly,
}: {
  catalog: RuleCatalog
  definition: RuleDefinition
  onChange: (d: RuleDefinition) => void
  readOnly?: boolean
}) {
  const [view, setView] = useState<'builder' | 'json'>('builder')
  const [jsonText, setJsonText] = useState(() => JSON.stringify(cleanDefinition(definition), null, 2))
  const [jsonError, setJsonError] = useState<string | null>(null)
  const ids = { sev: useId(), viol: useId(), miss: useId(), low: useId(), pass: useId(), fail: useId() }
  const set = <K extends keyof RuleDefinition>(k: K, v: RuleDefinition[K]) => onChange({ ...definition, [k]: v })

  const switchTo = (v: 'builder' | 'json') => {
    if (v === 'json') {
      setJsonText(JSON.stringify(cleanDefinition(definition), null, 2))
      setJsonError(null)
    }
    setView(v)
  }
  const onJson = (text: string) => {
    setJsonText(text)
    try {
      const parsed = JSON.parse(text) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('The definition must be a JSON object')
      setJsonError(null)
      onChange(parsed as RuleDefinition)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }
  const builderBlocked = view === 'json' && !!jsonError

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Editor view" className="inline-flex rounded-lg border border-line-strong bg-surface p-0.5">
        {(
          [
            ['builder', 'Builder', ListTree],
            ['json', 'JSON', Braces],
          ] as const
        ).map(([k, label, Icon]) => {
          const blocked = k === 'builder' && builderBlocked
          const tab = (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={view === k}
            aria-disabled={blocked || undefined}
            onClick={() => !blocked && switchTo(k)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors aria-disabled:cursor-not-allowed aria-disabled:opacity-50',
              view === k ? 'bg-navy-900 text-white' : 'text-ink-muted hover:text-ink',
            )}
          >
            <Icon className="size-3.5" aria-hidden /> {label}
          </button>
          )
          return blocked ? (
            <Tooltip key={k} content="The JSON has errors. Fix them before switching back to the builder.">
              {tab}
            </Tooltip>
          ) : (
            tab
          )
        })}
      </div>

      {view === 'json' ? (
        <div className="space-y-1.5">
          <textarea
            aria-label="Rule definition JSON"
            spellCheck={false}
            className={cn(
              'block min-h-80 w-full rounded-xl border bg-navy-950 p-4 font-mono text-[12.5px] leading-5 text-navy-50 focus:outline-none focus:ring-4 focus:ring-violet-100',
              jsonError ? 'border-fail' : 'border-navy-800',
            )}
            value={jsonText}
            onChange={(e) => onJson(e.target.value)}
            readOnly={readOnly}
          />
          {jsonError && (
            <p role="alert" className="text-[12.5px] font-medium text-fail">
              {jsonError}
            </p>
          )}
          <p className="text-[12px] text-ink-subtle">Declarative JSON only. Operators outside the allowlist are rejected by the server; nothing here is executed.</p>
        </div>
      ) : (
        <>
          <section aria-labelledby={`${ids.sev}-cond`}>
            <h3 id={`${ids.sev}-cond`} className="mb-2 text-[13px] font-semibold text-ink">
              The rule passes when
            </h3>
            <ConditionBuilder node={definition.condition} catalog={catalog} onChange={(c) => set('condition', c)} readOnly={readOnly} label="Condition" />
          </section>

          <section aria-labelledby={`${ids.sev}-app`} className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id={`${ids.sev}-app`} className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
                <Filter className="size-3.5 text-ink-subtle" aria-hidden /> Applies only when
              </h3>
              {!readOnly &&
                (definition.applies_when ? (
                  <button type="button" onClick={() => set('applies_when', null)} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-ink-muted hover:text-fail">
                    <X className="size-3.5" aria-hidden /> Always apply
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => set('applies_when', newLeaf(catalog, 'application.application_type'))}
                    className="py-1 text-[12.5px] font-medium text-violet-700 hover:underline"
                  >
                    Add an applicability condition
                  </button>
                ))}
            </div>
            {definition.applies_when ? (
              <ConditionBuilder node={definition.applies_when} catalog={catalog} onChange={(c) => set('applies_when', c)} readOnly={readOnly} label="Applies when" />
            ) : (
              <p className="text-[13px] text-ink-subtle">Applies to every application. When an applicability condition is false, the outcome is “not applicable”.</p>
            )}
          </section>
        </>
      )}

      <section aria-label="Outcome configuration" className="grid gap-3 sm:grid-cols-2">
        <Labelled id={ids.sev} label="Severity" hint="Independent of the outcome; used for prioritisation.">
          <Select id={ids.sev} size="sm" value={definition.severity} onChange={(e) => set('severity', e.target.value as Severity)} disabled={readOnly || view === 'json'}>
            {(Object.keys(SEVERITY) as Severity[]).map((s) => (
              <option key={s} value={s}>
                {SEVERITY[s]}
              </option>
            ))}
          </Select>
        </Labelled>
        <Labelled id={ids.viol} label="When the condition is not met" hint="“Review” routes to a person instead of failing.">
          <Select id={ids.viol} size="sm" value={definition.on_violation} onChange={(e) => set('on_violation', e.target.value as 'fail' | 'review')} disabled={readOnly || view === 'json'}>
            <option value="fail">Rule fails</option>
            <option value="review">Needs human review</option>
          </Select>
        </Labelled>
        <Labelled id={ids.miss} label="When required data is missing" hint="Missing data is never treated as a contradiction by default.">
          <Select id={ids.miss} size="sm" value={definition.missing_data_policy} onChange={(e) => set('missing_data_policy', e.target.value as MissingDataPolicy)} disabled={readOnly || view === 'json'}>
            {(Object.keys(MISSING_POLICY) as MissingDataPolicy[]).map((p) => (
              <option key={p} value={p}>
                {MISSING_POLICY[p]}
              </option>
            ))}
          </Select>
        </Labelled>
        <Labelled id={ids.low} label="When inputs are low confidence" hint="e.g. noisy OCR or stale evidence analysis.">
          <Select id={ids.low} size="sm" value={definition.low_confidence_policy} onChange={(e) => set('low_confidence_policy', e.target.value as LowConfidencePolicy)} disabled={readOnly || view === 'json'}>
            {(Object.keys(LOW_CONFIDENCE_POLICY) as LowConfidencePolicy[]).map((p) => (
              <option key={p} value={p}>
                {LOW_CONFIDENCE_POLICY[p]}
              </option>
            ))}
          </Select>
        </Labelled>
        <Labelled id={ids.pass} label="Message when passed (optional)">
          <input id={ids.pass} className={select} maxLength={500} value={definition.pass_message ?? ''} onChange={(e) => set('pass_message', e.target.value)} disabled={readOnly || view === 'json'} />
        </Labelled>
        <Labelled id={ids.fail} label="Message when not met (optional)">
          <input id={ids.fail} className={select} maxLength={500} value={definition.fail_message ?? ''} onChange={(e) => set('fail_message', e.target.value)} disabled={readOnly || view === 'json'} />
        </Labelled>
      </section>
    </div>
  )
}

function Labelled({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[12.5px] font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11.5px] text-ink-subtle">{hint}</p>}
    </div>
  )
}
