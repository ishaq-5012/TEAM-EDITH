import { FlaskConical } from 'lucide-react'
import { useState } from 'react'
import { DEFAULT_DAYS, daysAgo, todayUtc, useInsightsWindow } from './insightsMeta'
import { controlClass } from '../../components/ui/controlClass'

const QUICK = [7, 30, 90, 365]

/** One row of filters above the charts: window (UTC days, inclusive), application type, synthetic data. */
export function WindowFilters({ showScope = true }: { showScope?: boolean }) {
  const { value, update } = useInsightsWindow()
  const [type, setType] = useState(value.application_type)
  const field = controlClass({ size: 'sm', full: false })
  const span = Math.round((Date.parse(value.to) - Date.parse(value.from)) / 86_400_000) + 1
  return (
    <div role="group" aria-label="Insights filters" className="flex flex-wrap items-end gap-x-3 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Quick ranges">
        {QUICK.map((d) => {
          const active = value.to === todayUtc() && span === d
          return (
            <button
              key={d}
              type="button"
              aria-pressed={active}
              onClick={() => update({ from: daysAgo(d - 1), to: todayUtc() })}
              className={`h-8 rounded-lg px-2.5 text-[12.5px] font-medium ${active ? 'bg-navy-900 text-white' : 'text-ink-muted hover:bg-navy-50'}`}
            >
              {d === 365 ? '1 year' : `${d} days`}
            </button>
          )
        })}
      </div>
      <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
        From (UTC)
        <input type="date" className={field} value={value.from} max={value.to} onChange={(e) => e.target.value && update({ from: e.target.value })} />
      </label>
      <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
        To (UTC)
        <input type="date" className={field} value={value.to} min={value.from} max={todayUtc()} onChange={(e) => e.target.value && update({ to: e.target.value })} />
      </label>
      {showScope && (
        <>
          <form
            className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle"
            onSubmit={(e) => {
              e.preventDefault()
              update({ application_type: type.trim() })
            }}
          >
            <label htmlFor="insights-type">Application type</label>
            <input id="insights-type" className={`${field} w-36`} placeholder="All types" value={type} onChange={(e) => setType(e.target.value)} onBlur={() => type.trim() !== value.application_type && update({ application_type: type.trim() })} />
          </form>
          <label className="flex h-8 items-center gap-2 text-[12.5px] text-ink-muted">
            <input type="checkbox" checked={value.include_synthetic} onChange={(e) => update({ include_synthetic: e.target.checked })} className="size-4 accent-violet-600" />
            <FlaskConical className="size-3.5" aria-hidden /> Include test records
          </label>
        </>
      )}
      {(value.from !== daysAgo(DEFAULT_DAYS - 1) || value.to !== todayUtc() || value.application_type || !value.include_synthetic) && (
        <button type="button" className="h-8 text-[12.5px] font-medium text-violet-700 hover:underline" onClick={() => { setType(''); update({ from: daysAgo(DEFAULT_DAYS - 1), to: todayUtc(), application_type: '', include_synthetic: true }) }}>
          Reset
        </button>
      )}
    </div>
  )
}
