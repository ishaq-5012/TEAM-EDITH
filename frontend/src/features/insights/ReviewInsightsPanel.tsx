import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Clock3, ThumbsDown, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import type { ReviewCategory, ReviewInsights, ReviewStatus } from '../../lib/types'
import { CATEGORY, REVIEW_STATUS } from '../review/reviewMeta'
import { BarRows } from './MetricParts'
import { Panel, Stat } from './InsightsPanel'
import { AGE_LABEL, pct, useDefinitions, useInsightsWindow } from './insightsMeta'
import { WindowFilters } from './WindowFilters'

export function ReviewInsightsPanel() {
  const w = useInsightsWindow()
  const q = useQuery({ queryKey: ['insights', 'review', w.query], queryFn: () => api.reviewInsights(w.query), placeholderData: keepPreviousData })
  return (
    <div className="space-y-5">
      <WindowFilters />
      {q.isPending ? <LoadingRows rows={6} label="Loading review insights" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : <Body r={q.data} />}
    </div>
  )
}

function Body({ r }: { r: ReviewInsights }) {
  const { byKey: d } = useDefinitions()
  const fp = r.false_positives
  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Backlog by age" def={d.get('review.age')} icon={<Clock3 className="size-4" />}>
          <p className="mb-3 text-[12.5px] text-ink-muted">
            {r.backlog.total} active item{r.backlog.total === 1 ? '' : 's'} · {r.backlog.unassigned} unassigned
          </p>
          <BarRows label="Active review items by age" empty="The review queue is empty." rows={Object.entries(r.backlog.by_age).map(([k, n]) => ({ key: k, label: AGE_LABEL[k], count: n }))} />
          <h3 className="mt-4 mb-2 text-[13px] font-semibold">By status and category</h3>
          {r.backlog.by_status_category.length ? (
            <ul className="space-y-1 text-[12.5px]">
              {r.backlog.by_status_category.map((x) => (
                <li key={`${x.status}-${x.category}`}>
                  <Link to={`/review?status=${x.status}&category=${x.category}`} className="flex items-center justify-between gap-2 rounded-md px-1 py-0.5 hover:bg-navy-50/70">
                    <span className="flex gap-1.5">
                      <StatusPill status={REVIEW_STATUS[x.status as ReviewStatus].pill}>{REVIEW_STATUS[x.status as ReviewStatus].label}</StatusPill>
                      <StatusPill status={CATEGORY[x.category as ReviewCategory].pill}>{CATEGORY[x.category as ReviewCategory].label}</StatusPill>
                    </span>
                    <span className="tabular">{x.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-ink-subtle">Nothing is waiting for review.</p>
          )}
        </Panel>
        <Panel title="Workload by assignee" def={d.get('review.workload')} icon={<Users className="size-4" />}>
          {r.workload.length ? (
            <div className="table-scroll">
            <table className="data-table flush dense" aria-label="Active review items per assignee">
              <thead>
                <tr>
                  <th scope="col">Assignee</th>
                  <th scope="col" className="num">Active items</th>
                  <th scope="col" className="num">Critical / high</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {r.workload.map((u) => (
                  <tr key={u.user_id ?? 'none'}>
                    <td>
                      <Link to={`/review?assignee=${u.user_id ?? 'unassigned'}`} className="text-violet-700 hover:underline">
                        {u.full_name ?? 'Unassigned'}
                      </Link>
                      {u.email && <span className="ml-1 text-ink-subtle">{u.email}</span>}
                    </td>
                    <td className="num">{u.count}</td>
                    <td className="num">{(u.by_severity.critical ?? 0) + (u.by_severity.high ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          ) : (
            <p className="text-[13px] text-ink-subtle">No active review items.</p>
          )}
        </Panel>
      </div>

      <Panel title="False positives from reviewer decisions" def={d.get('review.false_positive_rate')} icon={<ThumbsDown className="size-4" />}>
        <div className="mb-4 grid gap-2 text-[12.5px] sm:grid-cols-4">
          <Stat label="False-positive rate" value={pct(fp.rate)} sub={`${fp.dismissed} dismissed of ${fp.decided_items} decided`} />
          <Stat label="Confirmed" value={fp.confirmed} to="/review?status=confirmed" />
          <Stat label="Dismissed" value={fp.dismissed} to="/review?status=dismissed" />
          <Stat label="Reopened (excluded)" value={fp.reopened_excluded} />
        </div>
        {fp.by_rule.length ? (
          <div className="table-scroll">
            <table className="data-table flush dense min-w-[520px]" aria-label="False positives by rule">
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col" className="num">Confirmed</th>
                  <th scope="col" className="num">Dismissed</th>
                  <th scope="col" className="pl-4">False-positive rate</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {fp.by_rule.map((x) => (
                  <tr key={x.rule_id}>
                    <td>
                      <Link to={`/compliance/rules/${x.rule_id}`} className="text-violet-700 hover:underline">
                        {x.rule_name}
                      </Link>
                      <span className="ml-1 font-mono text-[11px] text-ink-subtle">{x.rule_key}</span>
                    </td>
                    <td className="num">{x.confirmed}</td>
                    <td className="num">{x.dismissed}</td>
                    <td className="pl-4">
                      <span className="flex items-center gap-2">
                        <span className="relative h-2 w-24 rounded bg-navy-50" aria-hidden>
                          <span className="absolute inset-y-0 left-0 rounded-r bg-[var(--color-violet-600)]" style={{ width: `${(x.false_positive_rate ?? 0) * 100}%` }} />
                        </span>
                        {pct(x.false_positive_rate)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[13px] text-ink-subtle">No confirm or dismiss decisions were recorded in this window.</p>
        )}
        {Object.keys(fp.by_category).length > 0 && (
          <p className="mt-3 text-[12px] text-ink-muted">
            By category:{' '}
            {Object.entries(fp.by_category)
              .map(([k, v]) => `${CATEGORY[k as ReviewCategory]?.label ?? k} ${pct(v.false_positive_rate)} (${v.dismissed}/${v.confirmed + v.dismissed})`)
              .join(' · ')}
          </p>
        )}
      </Panel>
    </div>
  )
}
