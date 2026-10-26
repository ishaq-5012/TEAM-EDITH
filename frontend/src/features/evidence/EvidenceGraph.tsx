import { ChevronsLeftRight, ChevronsRightLeft, Equal } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { Fragment, useMemo, useState } from 'react'
import { cn } from '../../components/ui/cn'
import type { EvidenceFinding, EvidenceReference, FieldRelationship } from '../../lib/types'
import { OUTCOME, OUTCOME_LOOK, groupIcon } from './evidenceMeta'

export type Selection =
  | { kind: 'finding'; findingId: string }
  | { kind: 'relationship'; findingId: string; id: string }
  | { kind: 'reference'; findingId: string; id: string }
  | null

export interface GraphDocument {
  id: string
  name: string
}

/** Documents in order of first appearance across findings (references are stored in document order). */
// eslint-disable-next-line react-refresh/only-export-components
export function documentsOf(findings: EvidenceFinding[]): GraphDocument[] {
  const seen = new Map<string, string>()
  for (const f of findings) for (const r of f.references) if (!seen.has(r.document_id)) seen.set(r.document_id, r.document_name)
  return [...seen].map(([id, name]) => ({ id, name }))
}

type CellState = 'agrees' | 'differs' | 'only' | 'missing'

function valueText(r: EvidenceReference): string {
  if (r.effective_value) return r.effective_value.replace(/\n/g, ', ')
  return r.status === 'not_extracted' ? 'not extracted' : r.status === 'invalid' ? `invalid: ${r.raw_value ?? ''}` : 'missing'
}

/** How each document's value relates to the most common value of the check. */
function cellStates(f: EvidenceFinding): Map<string, CellState> {
  const counts = new Map<string, number>()
  for (const r of f.references) if (r.usable && r.effective_value) counts.set(r.effective_value, (counts.get(r.effective_value) ?? 0) + 1)
  const ranked = [...counts].sort((a, b) => b[1] - a[1])
  // Only a value held by more documents than any other counts as "most common"; a tie means every value differs.
  const majority = ranked.length && (ranked.length === 1 || ranked[0][1] > ranked[1][1]) ? ranked[0][0] : undefined
  const out = new Map<string, CellState>()
  for (const r of f.references) {
    if (!(r.usable && r.effective_value)) out.set(r.id, 'missing')
    else if (counts.size === 1 && counts.get(r.effective_value) === 1) out.set(r.id, 'only')
    else out.set(r.id, r.effective_value === majority ? 'agrees' : 'differs')
  }
  return out
}

const CELL: Record<CellState, { box: string; dot: string; label: string }> = {
  agrees: { box: 'border-pass/25 bg-pass-bg/60', dot: 'bg-pass', label: 'agrees with the most common value' },
  differs: { box: 'border-fail/30 bg-fail-bg', dot: 'bg-fail', label: 'differs from the most common value' },
  only: { box: 'border-line-strong bg-surface', dot: 'bg-violet-500', label: 'only value' },
  missing: { box: 'border-dashed border-line-strong bg-navy-50/60', dot: 'bg-navy-100', label: 'no usable value' },
}

/**
 * Evidence matrix: checks as rows, documents as columns. Each cell is a stored evidence reference, coloured by how
 * it relates to the check's most common value. Stored comparisons are listed under each check (differences first)
 * instead of being drawn as arcs. Nothing is shown that isn't in the analysis.
 */
export function EvidenceGraph({
  findings,
  selection,
  onSelect,
}: {
  findings: EvidenceFinding[]
  selection: Selection
  onSelect: (s: Selection) => void
}) {
  const reduce = useReducedMotion()
  const allDocs = useMemo(() => documentsOf(findings), [findings])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [onlyDifferences, setOnlyDifferences] = useState(false)
  const [showMatches, setShowMatches] = useState<Set<string>>(new Set())
  // Pairwise comparisons are listed on demand: the coloured cells already show which documents differ.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // Documents involved in at least one comparison that isn't a match.
  const involved = useMemo(() => {
    const ids = new Set<string>()
    for (const f of findings) {
      const doc = new Map(f.references.map((r) => [r.id, r.document_id]))
      for (const rel of f.relationships) {
        if (rel.result !== 'fail' && rel.result !== 'review') continue
        ids.add(doc.get(rel.source_reference_id)!)
        ids.add(doc.get(rel.target_reference_id)!)
      }
    }
    return ids
  }, [findings])
  const docs = onlyDifferences ? allDocs.filter((d) => involved.has(d.id)) : allDocs
  const index = new Map(allDocs.map((d, i) => [d.id, i + 1]))

  const toggle = (set: Set<string>, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  }

  const docLabel = (id: string) => `D${index.get(id)}`

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-ink-muted" aria-label="Legend">
          {(['agrees', 'differs', 'only', 'missing'] as const).map((s) => (
            <li key={s} className="inline-flex items-center gap-1.5">
              <span className={cn('inline-block h-3.5 w-5 rounded border', CELL[s].box)} aria-hidden />
              {s === 'agrees' ? 'Agrees with most documents' : s === 'differs' ? 'Differs' : s === 'only' ? 'Only value' : 'Missing or not extracted'}
            </li>
          ))}
        </ul>
        <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] font-medium text-ink-muted">
          <input type="checkbox" checked={onlyDifferences} onChange={(e) => setOnlyDifferences(e.target.checked)} className="size-4 accent-violet-600" />
          Only documents with differences ({involved.size} of {allDocs.length})
        </label>
      </div>

      <div
        role="group"
        aria-label={`Evidence graph: ${findings.length} checks across ${allDocs.length} documents`}
        className="overflow-hidden rounded-3xl border border-line bg-surface shadow-[var(--shadow-card)]"
      >
        <div className="max-h-[70vh] overflow-auto overscroll-contain">
          <table className="w-full border-separate border-spacing-0 text-left">
            <caption className="sr-only">Checks by document. Each cell is the value a document holds for the check.</caption>
            <thead>
              <tr>
                <th scope="col" className="sticky top-0 left-0 z-30 w-56 min-w-56 border-b border-line bg-navy-50/95 px-5 py-3 text-[11.5px] font-semibold tracking-wide text-ink-subtle uppercase backdrop-blur">
                  Check
                </th>
                {docs.map((d) => {
                  const isCollapsed = collapsed.has(d.id)
                  return (
                    <th key={d.id} scope="col" className={cn('sticky top-0 z-20 border-b border-l border-line bg-navy-50/95 p-1.5 align-bottom backdrop-blur', isCollapsed ? 'w-14 min-w-14' : 'w-40 min-w-40')}>
                      <button
                        type="button"
                        aria-expanded={!isCollapsed}
                        aria-label={`Document ${d.name}. ${isCollapsed ? 'Expand' : 'Collapse'} values`}
                        onClick={() => setCollapsed((s) => toggle(s, d.id))}
                        title={d.name}
                        className="group flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-white/[0.06]"
                      >
                        <span className={cn('grid h-6 shrink-0 place-items-center rounded-md px-1.5 text-[11px] font-bold text-white', involved.has(d.id) ? 'bg-fail' : 'bg-navy-900')}>
                          {docLabel(d.id)}
                        </span>
                        {!isCollapsed && <span className="min-w-0 flex-1 truncate text-[12px] font-semibold normal-case text-ink">{d.name}</span>}
                        {isCollapsed ? (
                          <ChevronsLeftRight className="size-3.5 shrink-0 text-ink-subtle" aria-hidden />
                        ) : (
                          <ChevronsRightLeft className="size-3.5 shrink-0 text-ink-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                        )}
                      </button>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {findings.map((f, row) => {
                const states = cellStates(f)
                const refById = new Map(f.references.map((r) => [r.id, r]))
                const rowSelected = selection?.findingId === f.id
                const look = OUTCOME_LOOK[f.outcome]
                const Icon = groupIcon(f.group_key)
                const differences = f.relationships.filter((r) => r.result !== 'pass')
                const nDiffer = f.relationships.filter((r) => r.result === 'fail' || r.result === 'review').length
                const nIncomplete = f.relationships.filter((r) => r.result === 'insufficient').length
                const matches = f.relationships.filter((r) => r.result === 'pass')
                const listed: FieldRelationship[] = showMatches.has(f.id) ? [...differences, ...matches] : differences
                const agreeing = [...states.values()].filter((s) => s === 'agrees').length
                const differing = [...states.values()].filter((s) => s === 'differs').length
                return (
                  <Fragment key={f.id}>
                    <motion.tr
                      initial={reduce ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: reduce ? 0 : Math.min(row * 0.04, 0.24) }}
                      className={cn('group/row', rowSelected && '[&>*]:bg-violet-50/70')}
                    >
                      <th scope="row" className="sticky left-0 z-10 border-t border-line bg-surface px-4 py-3 align-top font-normal group-hover/row:bg-navy-50/60">
                        <button
                          type="button"
                          aria-label={`${f.group_label}: ${OUTCOME[f.outcome].label}, priority ${f.priority_score}`}
                          onClick={() => onSelect({ kind: 'finding', findingId: f.id })}
                          className="flex w-full items-start gap-3 rounded-xl p-1 text-left transition-colors hover:bg-white/[0.06]"
                        >
                          <span className={cn('grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white shadow-sm', look.tile)}>
                            <Icon className="size-4" aria-hidden />
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-[13.5px] font-semibold text-ink">{f.group_label}</span>
                            <span className={cn('block text-[11.5px] font-medium', look.text)}>
                              {OUTCOME[f.outcome].label}
                              {f.outcome !== 'pass' && <span className="text-ink-subtle"> · P{f.priority_score}</span>}
                            </span>
                            <span className="mt-0.5 block text-[11px] text-ink-subtle">
                              {agreeing > 0 && `${agreeing} agree`}
                              {differing > 0 && ` · ${differing} differ`}
                            </span>
                          </span>
                        </button>
                        {f.relationships.length > 0 && (
                          <button
                            type="button"
                            aria-expanded={expanded.has(f.id)}
                            aria-label={`${expanded.has(f.id) ? 'Hide' : 'Show'} comparisons for ${f.group_label}`}
                            onClick={() => setExpanded((s) => toggle(s, f.id))}
                            className="mt-1 ml-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium text-violet-700 hover:bg-violet-50"
                          >
                            {expanded.has(f.id)
                              ? 'Hide comparisons'
                              : [nDiffer && `${nDiffer} differ`, nIncomplete && `${nIncomplete} incomplete`].filter(Boolean).join(' · ') || `${f.relationships.length} comparisons, all match`}
                            <span aria-hidden>{expanded.has(f.id) ? '▴' : '▾'}</span>
                          </button>
                        )}
                      </th>
                      {docs.map((d) => {
                        const ref = f.references.find((r) => r.document_id === d.id)
                        if (!ref) return <td key={d.id} className="border-t border-l border-line" />
                        const state = states.get(ref.id)!
                        const selected = selection?.kind === 'reference' && selection.id === ref.id
                        const isCollapsed = collapsed.has(d.id)
                        const text = valueText(ref)
                        return (
                          <td key={d.id} className="border-t border-l border-line p-1.5 align-top group-hover/row:bg-navy-50/40">
                            <button
                              type="button"
                              aria-pressed={selected}
                              aria-label={`${f.group_label} in ${d.name}: ${text}`}
                              title={`${d.name}: ${text} (${CELL[state].label})`}
                              onClick={() => onSelect({ kind: 'reference', findingId: f.id, id: ref.id })}
                              className={cn(
                                'block w-full rounded-xl border text-left transition-[box-shadow,transform] duration-150 hover:-translate-y-px hover:shadow-md motion-reduce:hover:translate-y-0',
                                CELL[state].box,
                                selected && 'ring-2 ring-violet-500 ring-offset-1',
                                isCollapsed ? 'grid h-10 place-items-center' : 'px-2.5 py-2',
                              )}
                            >
                              {isCollapsed ? (
                                <span className={cn('size-2.5 rounded-full', CELL[state].dot)} aria-hidden />
                              ) : (
                                <>
                                  <span className={cn('block truncate text-[12px]', state === 'missing' ? 'text-ink-subtle italic' : 'font-mono font-medium text-ink')}>{text}</span>
                                  <span className="mt-0.5 flex items-center gap-1 text-[10.5px] text-ink-subtle">
                                    <span className={cn('size-1.5 rounded-full', CELL[state].dot)} aria-hidden />
                                    {ref.page_number ? `p.${ref.page_number}` : ref.status.replace('_', ' ')}
                                    {ref.value_source === 'correction' && ' · corrected'}
                                    {ref.usable && ref.evidence_quality !== 'high' && ` · ${ref.evidence_quality}`}
                                  </span>
                                </>
                              )}
                            </button>
                          </td>
                        )
                      })}
                    </motion.tr>
                    {f.relationships.length > 0 && expanded.has(f.id) && (
                      <tr className={cn(rowSelected && '[&>*]:bg-violet-50/70')}>
                        <td colSpan={docs.length + 1} className="bg-navy-50/50 px-0 py-3">
                          {/* Sticky so the comparisons stay readable however far the table is scrolled sideways. */}
                          <div className="sticky left-0 flex max-w-[min(100%,calc(100vw-4rem))] flex-wrap items-center gap-1.5 px-5">
                            <span className="mr-1 text-[11px] font-semibold tracking-wide text-ink-subtle uppercase">
                              {[nDiffer && `${nDiffer} differ`, nIncomplete && `${nIncomplete} incomplete`].filter(Boolean).join(' · ') || 'All comparisons match'}
                            </span>
                            {listed.map((rel) => {
                              const src = refById.get(rel.source_reference_id)
                              const tgt = refById.get(rel.target_reference_id)
                              if (!src || !tgt) return null
                              const meta = OUTCOME[rel.result]
                              const selected = selection?.kind === 'relationship' && selection.id === rel.id
                              return (
                                <button
                                  key={rel.id}
                                  type="button"
                                  aria-pressed={selected}
                                  aria-label={`${f.group_label}: ${src.document_name} versus ${tgt.document_name}: ${meta.label}`}
                                  title={`${src.document_name} ↔ ${tgt.document_name}: ${meta.label}`}
                                  onClick={() => onSelect({ kind: 'relationship', findingId: f.id, id: rel.id })}
                                  className={cn(
                                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors',
                                    selected ? 'border-violet-600 bg-violet-600 text-white' : 'border-line bg-surface text-ink hover:border-violet-400',
                                  )}
                                >
                                  <span className="font-bold">{docLabel(src.document_id)}</span>
                                  <span aria-hidden>↔</span>
                                  <span className="font-bold">{docLabel(tgt.document_id)}</span>
                                  <span className="size-1.5 rounded-full" style={{ background: OUTCOME_LOOK[rel.result].ring }} aria-hidden />
                                  <span className={selected ? 'text-white/90' : 'text-ink-muted'}>{meta.short}</span>
                                </button>
                              )
                            })}
                            {matches.length > 0 && (
                              <button
                                type="button"
                                aria-expanded={showMatches.has(f.id)}
                                onClick={() => setShowMatches((s) => toggle(s, f.id))}
                                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] font-medium text-violet-700 hover:bg-violet-50"
                              >
                                <Equal className="size-3.5" aria-hidden />
                                {showMatches.has(f.id) ? 'Hide matching' : `+${matches.length} matching`}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
