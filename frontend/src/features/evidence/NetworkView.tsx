import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useMemo, useState, type KeyboardEvent } from 'react'
import { cn } from '../../components/ui/cn'
import type { EvidenceFinding, EvidenceReference } from '../../lib/types'
import { documentsOf, type Selection } from './EvidenceGraph'
import { OUTCOME, OUTCOME_LOOK, groupIcon } from './evidenceMeta'

const W = 920
const H = 640
const CX = W / 2
const CY = H / 2
const NODE_W = 168
const NODE_H = 56

const trunc = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

function activate(e: KeyboardEvent, fn: () => void) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    fn()
  }
}

function valueText(r: EvidenceReference | undefined): string {
  if (!r) return 'not in this check'
  if (r.effective_value) return r.effective_value.replace(/\n/g, ', ')
  return r.status === 'not_extracted' ? 'not extracted' : r.status === 'invalid' ? 'invalid value' : 'missing'
}

/**
 * Radial network for one check at a time: the check is the hub, documents sit on a ring, and every stored
 * comparison is a curved link between two documents. Nothing is drawn that isn't in the analysis.
 */
export function NetworkView({
  findings,
  selection,
  focus: focusProp,
  onSelect,
  onFocus,
}: {
  findings: EvidenceFinding[]
  selection: Selection
  focus: string | null
  onSelect: (s: Selection) => void
  onFocus: (id: string | null) => void
}) {
  const pinned = focusProp
  const reduce = useReducedMotion()
  const ordered = useMemo(() => [...findings].sort((a, b) => b.priority_score - a.priority_score), [findings])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [showMatches, setShowMatches] = useState(false)
  // Hovering traces a document's links without changing the focus chosen in the document rail.
  const [hover, setHover] = useState<string | null>(null)
  const active = ordered.find((f) => f.id === activeId) ?? ordered[0]
  const docs = useMemo(() => documentsOf(findings), [findings])
  if (!active) return null
  const focus = hover ?? pinned

  const n = docs.length
  const rx = Math.min(W / 2 - NODE_W / 2 - 16, 120 + n * 26)
  const ry = Math.min(H / 2 - NODE_H / 2 - 16, 90 + n * 20)
  const pos = new Map(
    docs.map((d, i) => {
      const a = -Math.PI / 2 + (i / Math.max(n, 1)) * Math.PI * 2
      return [d.id, { x: CX + rx * Math.cos(a), y: CY + ry * Math.sin(a) }] as const
    }),
  )
  const refByDoc = new Map(active.references.map((r) => [r.document_id, r]))
  const Icon = groupIcon(active.group_key)
  const look = OUTCOME_LOOK[active.outcome]
  const hidden = active.relationships.filter((r) => r.result === 'pass').length
  const rels = active.relationships.filter((r) => showMatches || r.result !== 'pass' || focus)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="radiogroup" aria-label="Check shown in the network" className="flex flex-wrap gap-2">
          {ordered.map((f) => {
            const on = f.id === active.id
            const FIcon = groupIcon(f.group_key)
            return (
              <button
                key={f.id}
                role="radio"
                aria-checked={on}
                onClick={() => setActiveId(f.id)}
                className={cn(
                  'relative inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition-colors',
                  on ? 'border-transparent text-white' : 'border-line bg-surface text-ink-muted hover:border-violet-300 hover:text-ink',
                )}
              >
                {on && (
                  <motion.span
                    layoutId="network-check-pill"
                    className="absolute inset-0 rounded-full bg-navy-900"
                    transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 500, damping: 40 }}
                    aria-hidden
                  />
                )}
                <FIcon className="relative size-3.5" aria-hidden />
                <span className="relative">{f.group_label}</span>
                <span className="relative size-2 rounded-full" style={{ background: OUTCOME_LOOK[f.outcome].ring }} aria-hidden />
              </button>
            )
          })}
        </div>
        {hidden > 0 && !focus && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-muted">
            <input type="checkbox" checked={showMatches} onChange={(e) => setShowMatches(e.target.checked)} className="size-4 accent-violet-600" />
            Show {hidden} matching comparison{hidden === 1 ? '' : 's'}
          </label>
        )}
      </div>

      <div className="relative overflow-hidden rounded-3xl border border-line bg-[radial-gradient(circle_at_50%_45%,var(--color-violet-50),var(--color-surface)_60%)] shadow-[var(--shadow-card)]">
        <div className="overflow-x-auto">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="mx-auto block w-full min-w-[640px] select-none"
            role="group"
            aria-label={`Network for ${active.group_label}: ${n} documents, ${active.relationships.length} comparisons`}
          >
            <defs>
              <radialGradient id="hub-glow">
                <stop offset="0" stopColor="var(--color-violet-400)" stopOpacity="0.45" />
                <stop offset="1" stopColor="var(--color-violet-400)" stopOpacity="0" />
              </radialGradient>
            </defs>
            <ellipse cx={CX} cy={CY} rx={rx} ry={ry} fill="none" stroke="var(--color-line-strong)" strokeDasharray="2 8" />

            {/* Spokes: the hub reaches every document */}
            {docs.map((d) => {
              const p = pos.get(d.id)!
              return <line key={d.id} x1={CX} y1={CY} x2={p.x} y2={p.y} stroke="var(--color-line)" strokeWidth={1} />
            })}

            {/* Stored comparisons, curved toward the hub */}
            <AnimatePresence>
              {rels.map((rel, i) => {
                const src = active.references.find((r) => r.id === rel.source_reference_id)
                const tgt = active.references.find((r) => r.id === rel.target_reference_id)
                const a = src && pos.get(src.document_id)
                const b = tgt && pos.get(tgt.document_id)
                if (!src || !tgt || !a || !b) return null
                const mx = (a.x + b.x) / 2
                const my = (a.y + b.y) / 2
                const qx = mx + (CX - mx) * 0.45
                const qy = my + (CY - my) * 0.45
                const d = `M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`
                const meta = OUTCOME[rel.result]
                const involved = !focus || src.document_id === focus || tgt.document_id === focus
                const selected = selection?.kind === 'relationship' && selection.id === rel.id
                const select = () => onSelect({ kind: 'relationship', findingId: active.id, id: rel.id })
                return (
                  <motion.g
                    key={`${active.id}:${rel.id}`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected}
                    aria-label={`${active.group_label}: ${src.document_name} versus ${tgt.document_name}: ${meta.label}`}
                    onClick={select}
                    onKeyDown={(e) => activate(e, select)}
                    className="graph-node cursor-pointer"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: involved ? 1 : 0.12 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.25 }}
                  >
                    <path d={d} fill="none" stroke="transparent" strokeWidth={14} />
                    <motion.path
                      d={d}
                      fill="none"
                      style={{ stroke: meta.stroke }}
                      strokeDasharray={meta.dash}
                      strokeLinecap="round"
                      initial={reduce || meta.dash ? false : { pathLength: 0 }}
                      animate={{ pathLength: 1, strokeWidth: selected ? 4 : rel.result === 'pass' ? 1.4 : 2.4 }}
                      transition={{ duration: reduce ? 0 : 0.6, delay: reduce ? 0 : Math.min(i * 0.03, 0.4), ease: [0.22, 1, 0.36, 1] }}
                    />
                  </motion.g>
                )
              })}
            </AnimatePresence>

            {/* Hub */}
            <g aria-hidden>
              <circle cx={CX} cy={CY} r={96} fill="url(#hub-glow)" className="art-pulse" />
              <motion.circle key={active.id} cx={CX} cy={CY} r={54} style={{ fill: 'var(--color-navy-900)' }} initial={reduce ? false : { scale: 0.85 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 300, damping: 18 }} />
              <circle cx={CX} cy={CY} r={54} fill="none" style={{ stroke: look.bright }} strokeWidth={3} />
              <Icon x={CX - 13} y={CY - 38} width={26} height={26} className="text-cyan-400" />
              <text x={CX} y={CY + 10} textAnchor="middle" className="fill-white text-[12px] font-semibold">
                {trunc(active.group_label, 18)}
              </text>
              <text x={CX} y={CY + 26} textAnchor="middle" className="text-[10.5px]" style={{ fill: look.bright }}>
                {OUTCOME[active.outcome].label}
              </text>
            </g>

            {/* Document nodes */}
            {docs.map((doc, i) => {
              const p = pos.get(doc.id)!
              const ref = refByDoc.get(doc.id)
              const selected = selection?.kind === 'reference' && !!ref && selection.id === ref.id
              const focused = focus === doc.id
              const select = () => (ref ? onSelect({ kind: 'reference', findingId: active.id, id: ref.id }) : onFocus(pinned === doc.id ? null : doc.id))
              return (
                <motion.g
                  key={doc.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  aria-label={`${active.group_label} in ${doc.name}: ${valueText(ref)}`}
                  onClick={select}
                  onKeyDown={(e) => activate(e, select)}
                  onMouseEnter={() => setHover(doc.id)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(doc.id)}
                  onBlur={() => setHover(null)}
                  className="graph-node cursor-pointer"
                  initial={reduce ? false : { opacity: 0, scale: 0.6 }}
                  animate={{ opacity: focus && !focused ? 0.55 : 1, scale: 1 }}
                  transition={{ duration: 0.35, delay: reduce ? 0 : Math.min(i * 0.03, 0.3) }}
                  style={{ transformOrigin: `${p.x}px ${p.y}px` }}
                >
                  <rect
                    x={p.x - NODE_W / 2}
                    y={p.y - NODE_H / 2}
                    width={NODE_W}
                    height={NODE_H}
                    rx={16}
                    className={cn(
                      'transition-[fill,stroke] duration-150',
                      selected || focused ? 'fill-violet-50 stroke-violet-600' : ref?.usable ? 'fill-surface stroke-line-strong' : 'fill-navy-50 stroke-line',
                    )}
                    strokeWidth={selected || focused ? 2.5 : 1}
                    strokeDasharray={ref?.usable ? undefined : '4 3'}
                    style={{ filter: "drop-shadow(0 4px 10px rgb(17 22 58 / 0.1))" }}
                  />
                  <text x={p.x - NODE_W / 2 + 14} y={p.y - 5} className="fill-ink text-[12px] font-semibold">
                    {trunc(doc.name, 21)}
                  </text>
                  <text x={p.x - NODE_W / 2 + 14} y={p.y + 13} className={ref?.usable ? 'fill-violet-700 font-mono text-[11px]' : 'fill-ink-subtle text-[11px] italic'}>
                    {trunc(valueText(ref), 22)}
                  </text>
                  <title>{`${doc.name}: ${valueText(ref)}`}</title>
                </motion.g>
              )
            })}
          </svg>
        </div>
      </div>
      <p className="flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-ink-muted">
        {(['fail', 'review', 'insufficient', 'pass'] as const).map((o) => (
          <span key={o} className="inline-flex items-center gap-1.5">
            <svg width="22" height="6" aria-hidden>
              <line x1="0" y1="3" x2="22" y2="3" style={{ stroke: OUTCOME[o].stroke }} strokeWidth="2.5" strokeDasharray={OUTCOME[o].dash} />
            </svg>
            {OUTCOME[o].label}
          </span>
        ))}
        <span>Hover a document to trace its comparisons. Select a link or a document to open its evidence.</span>
      </p>
    </div>
  )
}
