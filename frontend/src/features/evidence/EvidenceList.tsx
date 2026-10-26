import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import type { EvidenceFinding } from '../../lib/types'
import type { Selection } from './EvidenceGraph'
import { OUTCOME, REASON, SEVERITY } from './evidenceMeta'

/** Accessible, list-based alternative to the graph: findings ordered by priority, each with its relationships. */
export function EvidenceList({ findings, selection, onSelect }: { findings: EvidenceFinding[]; selection: Selection; onSelect: (s: Selection) => void }) {
  const ordered = [...findings].sort((a, b) => b.priority_score - a.priority_score || a.group_label.localeCompare(b.group_label))
  return (
    <ol className="space-y-3" aria-label="Findings ordered by priority">
      {ordered.map((f) => {
        const ref = (id: string) => f.references.find((r) => r.id === id)
        return (
          <li key={f.id} className={cn('rounded-xl border bg-surface', selection?.findingId === f.id ? 'border-violet-500' : 'border-line')}>
            <button
              onClick={() => onSelect({ kind: 'finding', findingId: f.id })}
              className="flex w-full flex-wrap items-center gap-2 px-4 py-3 text-left"
              aria-label={`${f.group_label}: ${OUTCOME[f.outcome].label}, ${SEVERITY[f.severity]} severity, priority ${f.priority_score}. Show finding details`}
            >
              <span className="text-[13.5px] font-semibold">{f.group_label}</span>
              <StatusPill status={OUTCOME[f.outcome].pill}>{OUTCOME[f.outcome].label}</StatusPill>
              <span className="text-[12px] text-ink-muted">
                {SEVERITY[f.severity]} severity · priority {f.priority_score} · {f.coverage.with_value} of {f.coverage.documents} documents with a value
              </span>
            </button>
            {f.relationships.length > 0 && (
              <div className="table-scroll border-t border-line">
              <table className="data-table">
                <caption className="sr-only">Comparisons for {f.group_label}</caption>
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Target</th>
                    <th scope="col">Result</th>
                    <th scope="col">
                      <span className="sr-only">Details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {f.relationships.map((r) => {
                    const s = ref(r.source_reference_id)!
                    const t = ref(r.target_reference_id)!
                    const selected = selection?.kind === 'relationship' && selection.id === r.id
                    return (
                      <tr key={r.id} className={cn(selected && 'bg-violet-50')}>
                        <td>
                          <span className="block font-medium">{s.document_name}</span>
                          <span className="font-mono text-ink-muted">{s.effective_value ?? `(${s.status.replace('_', ' ')})`}</span>
                        </td>
                        <td>
                          <span className="block font-medium">{t.document_name}</span>
                          <span className="font-mono text-ink-muted">{t.effective_value ?? `(${t.status.replace('_', ' ')})`}</span>
                        </td>
                        <td>
                          <StatusPill status={OUTCOME[r.result].pill}>{OUTCOME[r.result].label}</StatusPill>
                          <span className="mt-0.5 block text-ink-subtle">{REASON[r.reason] ?? r.reason}</span>
                        </td>
                        <td className="text-right">
                          <button
                            onClick={() => onSelect({ kind: 'relationship', findingId: f.id, id: r.id })}
                            className="rounded-md px-2 py-1 text-[12px] font-medium text-violet-700 hover:bg-violet-50"
                            aria-label={`Compare ${s.document_name} and ${t.document_name} for ${f.group_label}`}
                          >
                            Compare
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
