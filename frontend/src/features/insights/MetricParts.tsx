import { CalendarRange, Clock3, Info } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CountUp } from '../../components/fx/CountUp'
import { useTilt } from '../../components/fx/useTilt'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { cn } from '../../components/ui/cn'
import { StatusPill, type Status } from '../../components/ui/StatusPill'
import type { MetricDefinition } from '../../lib/types'
import { STATUS_FILL } from './insightsMeta'

/** Basis badge: "Now" for current-state metrics, the window for historical ones. */
export function Basis({ def }: { def?: MetricDefinition }) {
  if (!def) return null
  return def.basis === 'current' ? (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-700" title="Current state: the date window doesn't apply">
      <Clock3 className="size-3" aria-hidden /> Now
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-700" title={`Counted by ${def.time_field} inside the selected window`}>
      <CalendarRange className="size-3" aria-hidden /> In window
    </span>
  )
}

/** "About this metric": definition, time basis, data source and de-duplication rule. */
export function MetricInfo({ def }: { def?: MetricDefinition }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onClick = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])
  if (!def) return null
  return (
    <span ref={ref} className="relative inline-flex">
      <button
        type="button"
        aria-label={`About “${def.label}”`}
        aria-expanded={open}
        aria-controls={id}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        className="relative grid size-5 place-items-center rounded-full text-ink-subtle before:absolute before:-inset-1 before:content-[''] hover:bg-navy-50 hover:text-violet-700"
      >
        <Info className="size-3.5" aria-hidden />
      </button>
      {open && (
        <span
          id={id}
          role="note"
          className="absolute top-6 right-0 z-30 w-72 rounded-xl border border-line bg-surface p-3 text-left text-[12px] leading-5 font-normal text-ink-muted shadow-[var(--shadow-card)]"
        >
          <span className="block font-semibold text-ink">{def.label}</span>
          <span className="mt-1 block">{def.definition}</span>
          <span className="mt-1.5 block">
            <span className="text-ink-subtle">Time basis: </span>
            {def.basis === 'current' ? 'current state (the window does not apply)' : `inside the window, by ${def.time_field}`}
          </span>
          <span className="block">
            <span className="text-ink-subtle">Source: </span>
            <span className="font-mono text-[11px]">{def.source}</span>
          </span>
          {def.dedup && (
            <span className="block">
              <span className="text-ink-subtle">No double counting: </span>
              {def.dedup}
            </span>
          )}
        </span>
      )}
    </span>
  )
}

function TiltLink({ to, className, children }: { to: string; className: string; children: ReactNode }) {
  const ref = useTilt<HTMLAnchorElement>()
  return (
    <Link ref={ref} to={to} className={className}>
      {children}
    </Link>
  )
}

function TiltDiv({ className, children }: { className: string; children: ReactNode }) {
  const ref = useTilt<HTMLDivElement>()
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  )
}

export function MetricTile({
  def,
  label,
  value,
  sub,
  to,
  tone,
}: {
  def?: MetricDefinition
  /** Always given: the definitions load separately and may be unavailable. */
  label: string
  value: ReactNode
  sub?: ReactNode
  to?: string
  tone?: Status
}) {
  const body = (
    <>
      <span className="flex items-start justify-between gap-2">
        <span className="text-[12.5px] font-medium text-ink-muted">{label}</span>
        <MetricInfo def={def} />
      </span>
      <span className="mt-1 flex items-baseline gap-2">
        {tone && <span aria-hidden className="size-2 shrink-0 translate-y-[-3px] rounded-full" style={{ background: STATUS_FILL[tone] }} />}
        <span className="tabular text-vibrant neon-text bg-clip-text text-[28px] leading-none font-bold tracking-[-0.03em] text-transparent">
          {typeof value === 'number' ? <CountUp value={value} /> : value}
        </span>
      </span>
      <span className="mt-2 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-[12px] text-ink-subtle">{sub}</span>
        <Basis def={def} />
      </span>
    </>
  )
  const cls = 'tilt-surface metal flex min-w-0 flex-col rounded-[var(--radius-card)] border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)]'
  return to ? (
    <TiltLink to={to} className={cn(cls, 'focus-visible:border-violet-400')}>
      {body}
    </TiltLink>
  ) : (
    <TiltDiv className={cls}>{body}</TiltDiv>
  )
}

export interface BarRow {
  key: string
  label: string
  pill?: Status
  count: number
  to?: string
  note?: string
}

/** Labelled horizontal bars: identity is the text label (and pill icon), never the bar color alone. */
export function BarRows({ rows, label, empty }: { rows: BarRow[]; label: string; empty?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  const total = rows.reduce((a, r) => a + r.count, 0)
  if (!total) return <p className="px-1 py-2 text-[13px] text-ink-subtle">{empty ?? 'Nothing to show for this scope.'}</p>
  return (
    <ul aria-label={label} className="space-y-1.5">
      {rows.map((r) => {
        const inner = (
          <>
            <span className="w-44 shrink-0 truncate text-[12.5px]">{r.pill ? <StatusPill status={r.pill}>{r.label}</StatusPill> : r.label}</span>
            <span className="relative h-3 min-w-0 flex-1 rounded bg-navy-50" aria-hidden>
              <span
                className="absolute inset-y-0 left-0 rounded-r"
                style={{ width: `${(r.count / max) * 100}%`, background: r.pill ? STATUS_FILL[r.pill] : 'var(--color-violet-600)', minWidth: r.count ? 3 : 0 }}
              />
            </span>
            <span className="tabular w-16 shrink-0 text-right text-[12.5px] text-ink">
              {r.count}{' '}
              <span className="text-[11px] text-ink-subtle">({Math.round((r.count / total) * 100)}%)</span>
            </span>
          </>
        )
        return (
          <li key={r.key} title={r.note}>
            {r.to ? (
              <Link to={r.to} className="flex items-center gap-3 rounded-md px-1 py-0.5 hover:bg-navy-50/70" aria-label={`${r.label}: ${r.count}`}>
                {inner}
              </Link>
            ) : (
              <span className="flex items-center gap-3 px-1 py-0.5" aria-label={`${r.label}: ${r.count}`}>
                {inner}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export interface DailySeries {
  key: string
  label: string
  color: string
}

function shortDate(d: string) {
  return d.slice(5)
}

/** Counts per UTC day. One series: no legend (the title names it). Two: legend + tooltip + table view. */
export function DailyBars({ data, series, label }: { data: Record<string, number | string>[]; series: DailySeries[]; label: string }) {
  const total = data.reduce((a, d) => a + series.reduce((b, s) => b + Number(d[s.key] ?? 0), 0), 0)
  return (
    <figure aria-label={label} className="min-w-0">
      {series.length > 1 && (
        <figcaption className="mb-2 flex flex-wrap gap-3 text-[12px] text-ink-muted">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </figcaption>
      )}
      {total === 0 ? (
        <p className="py-6 text-center text-[13px] text-ink-subtle">No events in this window.</p>
      ) : (
        <div className="h-44 w-full" role="img" aria-label={`${label}: ${total} in total`}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -18 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke="var(--color-line)" />
              <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'var(--color-ink-subtle)' }} tickLine={false} axisLine={{ stroke: 'var(--color-line-strong)' }} interval="preserveStartEnd" minTickGap={18} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--color-ink-subtle)' }} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ fill: 'var(--color-navy-50)' }}
                contentStyle={{ borderRadius: 10, border: '1px solid var(--color-line)', fontSize: 12, color: 'var(--color-ink)' }}
                labelStyle={{ color: 'var(--color-ink)', fontWeight: 600 }}
              />
              {series.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stackId="day"
                  fill={s.color}
                  stroke="var(--color-surface)"
                  strokeWidth={series.length > 1 ? 1 : 0}
                  radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
                  maxBarSize={28}
                  isAnimationActive
                  animationDuration={900}
                  animationEasing="ease-out"
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {total > 0 && (
        <details className="mt-2 text-[12px]">
          <summary className="cursor-pointer text-ink-muted">Table view</summary>
          <div className="table-scroll mt-1.5">
          <table className="data-table flush dense text-[12px]" aria-label={`${label} by day`}>
            <thead>
              <tr>
                <th scope="col">Date (UTC)</th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="num">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular">
              {data
                .filter((d) => series.some((s) => Number(d[s.key] ?? 0) > 0))
                .map((d) => (
                  <tr key={String(d.date)}>
                    <td>{String(d.date)}</td>
                    {series.map((s) => (
                      <td key={s.key} className="num">
                        {Number(d[s.key] ?? 0)}
                      </td>
                    ))}
                  </tr>
                ))}
            </tbody>
          </table>
          </div>
        </details>
      )}
    </figure>
  )
}

/** Outcome × severity counts. Cells with an open review category link to the filtered review queue. */
export function SeverityMatrix({
  cells,
  outcomes,
  severities,
  outcomeLabel,
  hrefFor,
  label,
}: {
  cells: { outcome: string; severity: string; count: number }[]
  outcomes: string[]
  severities: readonly string[]
  outcomeLabel: (o: string) => ReactNode
  hrefFor?: (outcome: string, severity: string) => string | undefined
  label: string
}) {
  const get = (o: string, s: string) => cells.find((c) => c.outcome === o && c.severity === s)?.count ?? 0
  const rows = outcomes.filter((o) => severities.some((s) => get(o, s) > 0))
  if (!rows.length) return <p className="py-2 text-[13px] text-ink-subtle">No findings for this scope.</p>
  return (
    <div className="table-scroll">
      <table className="data-table flush dense min-w-[420px]" aria-label={label}>
        <thead>
          <tr>
            <th scope="col">Outcome</th>
            {severities.map((s) => (
              <th key={s} scope="col" className="num capitalize">
                {s}
              </th>
            ))}
            <th scope="col" className="num">Total</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((o) => (
            <tr key={o}>
              <th scope="row">
                {outcomeLabel(o)}
              </th>
              {severities.map((s) => {
                const n = get(o, s)
                const href = n ? hrefFor?.(o, s) : undefined
                return (
                  <td key={s} className="num">
                    {href ? (
                      <Link to={href} className="font-medium text-violet-700 hover:underline" aria-label={`${n} ${o} findings with ${s} severity`}>
                        {n}
                      </Link>
                    ) : (
                      <span className={n ? 'text-ink' : 'text-ink-subtle'}>{n}</span>
                    )}
                  </td>
                )
              })}
              <td className="num font-semibold">{severities.reduce((a, s) => a + get(o, s), 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
