import { useQuery } from '@tanstack/react-query'
import { ArrowRight, GitCompareArrows, Minus, Plus } from 'lucide-react'
import { useId, useState } from 'react'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import { api } from '../../lib/api'
import type { DefinitionSummary, RuleDetail, RuleVersionStatus } from '../../lib/types'
import { formatValue, VERSION_STATUS } from './ruleMeta'
import { Select } from '../../components/ui/Field'

/** Side-by-side readable summaries plus a structural diff of two stored versions. */
export function ComparePanel({ rule, selectedId }: { rule: RuleDetail; selectedId: string }) {
  const ordered = [...rule.versions].sort((a, b) => a.version_number - b.version_number)
  const idx = ordered.findIndex((v) => v.id === selectedId)
  const [to, setTo] = useState(selectedId)
  const [from, setFrom] = useState(ordered[Math.max(0, idx - 1)]?.id ?? selectedId)
  const ids = { from: useId(), to: useId() }
  const q = useQuery({
    queryKey: ['rule-compare', rule.id, from, to],
    queryFn: () => api.compareVersions(rule.id, from, to),
    enabled: from !== to,
  })
  if (ordered.length < 2) {
    return (
      <EmptyState icon={<GitCompareArrows className="size-6" />} title="Only one version">
        Create a new version to compare changes over time.
      </EmptyState>
    )
  }
  const picker = (id: string, value: string, set: (v: string) => void, label: string) => (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[12px] font-medium text-ink-muted">
        {label}
      </label>
      <Select id={id} value={value} onChange={(e) => set(e.target.value)} size="sm" full={false}>
        {ordered.map((v) => (
          <option key={v.id} value={v.id}>
            v{v.version_number} · {VERSION_STATUS[v.status].label}
          </option>
        ))}
      </Select>
    </div>
  )
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        {picker(ids.from, from, setFrom, 'Before')}
        <ArrowRight className="mb-2 size-4 text-ink-subtle" aria-hidden />
        {picker(ids.to, to, setTo, 'After')}
      </div>
      {from === to ? (
        <p className="text-[13px] text-ink-subtle">Choose two different versions.</p>
      ) : q.isPending ? (
        <LoadingRows rows={3} label="Comparing versions" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <SummaryCard title={`v${q.data.from.version_number}`} status={q.data.from.status} summary={q.data.from.summary} tone="before" />
            <SummaryCard title={`v${q.data.to.version_number}`} status={q.data.to.status} summary={q.data.to.summary} tone="after" />
          </div>
          <section aria-label="Changes">
            <h3 className="mb-2 text-[13px] font-semibold">{q.data.changes.length ? `${q.data.changes.length} change${q.data.changes.length > 1 ? 's' : ''}` : 'No differences'}</h3>
            {q.data.changes.length > 0 && (
              <div className="table-scroll rounded-xl border border-line">
                <table className="data-table">
                  <caption className="sr-only">Changes between versions</caption>
                  <thead className="bg-navy-50/70">
                    <tr>
                      <th scope="col">Path</th>
                      <th scope="col">Before</th>
                      <th scope="col">After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.changes.map((c) => (
                      <tr key={c.path}>
                        <td className="font-mono text-[11.5px]">
                          <span className="inline-flex items-center gap-1">
                            {c.change === 'added' ? <Plus className="size-3 text-pass" aria-label="added" /> : c.change === 'removed' ? <Minus className="size-3 text-fail" aria-label="removed" /> : null}
                            {c.path}
                          </span>
                        </td>
                        <td className={cn('font-mono', c.change !== 'added' && 'bg-fail-bg/40 line-through decoration-fail/50')}>{c.change === 'added' ? '—' : formatValue(c.before)}</td>
                        <td className={cn('font-mono', c.change !== 'removed' && 'bg-pass-bg/50')}>{c.change === 'removed' ? '—' : formatValue(c.after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function SummaryCard({ title, status, summary, tone }: { title: string; status: RuleVersionStatus; summary: DefinitionSummary; tone: 'before' | 'after' }) {
  return (
    <div className={cn('rounded-xl border p-4 text-[13px] leading-6', tone === 'before' ? 'border-line bg-navy-50/40' : 'border-violet-200 bg-violet-50/40')}>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <StatusPill status={VERSION_STATUS[status].pill}>{VERSION_STATUS[status].label}</StatusPill>
      </div>
      <p>
        <span className="font-medium text-ink-muted">Applies: </span>
        {summary.applies_when}
      </p>
      <p>
        <span className="font-medium text-ink-muted">Passes when: </span>
        {summary.condition}
      </p>
      <p className="text-[12.5px] text-ink-muted">{summary.policies}</p>
    </div>
  )
}
