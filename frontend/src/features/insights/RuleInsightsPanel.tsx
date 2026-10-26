import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { GitCommitVertical, History, Scale, ShieldCheck, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardHeader } from '../../components/ui/Card'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { RuleVersionStatus, SimOutcome } from '../../lib/types'
import { RULE_OUTCOME, VERSION_STATUS } from '../compliance/ruleMeta'
import { Basis, MetricInfo } from './MetricParts'
import { Pager } from './Pager'
import { EVENT_LABEL, useDefinitions, useInsightsWindow } from './insightsMeta'
import { WindowFilters } from './WindowFilters'
import { Select } from '../../components/ui/Field'

const RUNS_PAGE = 10
const EVENTS_PAGE = 15

export function RuleInsightsPanel() {
  const w = useInsightsWindow()
  const { byKey: d } = useDefinitions()
  const [runsOffset, setRunsOffset] = useState(0)
  const [eventsOffset, setEventsOffset] = useState(0)
  const [ruleId, setRuleId] = useState('')
  const rules = useQuery({
    queryKey: ['insights', 'rules', w.query, runsOffset],
    queryFn: () => api.ruleInsights({ ...w.query, limit: RUNS_PAGE, offset: runsOffset }),
    placeholderData: keepPreviousData,
  })
  const gov = useQuery({
    queryKey: ['insights', 'governance', w.query.from, w.query.to, ruleId, eventsOffset],
    queryFn: () => api.ruleGovernance({ from: w.query.from, to: w.query.to, rule_id: ruleId || undefined, limit: EVENTS_PAGE, offset: eventsOffset }),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="space-y-5">
      <WindowFilters />
      <Card>
        <CardHeader
          icon={<Scale className="size-4" />}
          title={
            <span className="flex items-center gap-2">
              Rule-version usage <MetricInfo def={d.get('rules.version_usage')} />
            </span>
          }
          description={<Basis def={d.get('rules.version_usage')} />}
        />
        {rules.isPending ? (
          <LoadingRows rows={4} label="Loading rule usage" />
        ) : rules.isError ? (
          <ErrorState error={rules.error} onRetry={() => rules.refetch()} compact />
        ) : rules.data.version_usage.length === 0 ? (
          <EmptyState icon={<Scale className="size-6" />} title="No rule versions were evaluated in this window" className="py-10">
            Rule usage appears once validation runs evaluate published rules.
          </EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="data-table min-w-[640px]" aria-label="Rule-version usage">
              <thead>
                <tr>
                  <th scope="col">Rule version</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Runs</th>
                  <th scope="col" className="num">Applications</th>
                  <th scope="col">Latest outcomes (one per application)</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {rules.data.version_usage.map((u) => (
                  <tr key={u.version_id}>
                    <td>
                      <Link to={`/compliance/rules/${u.rule_id}`} className="text-violet-700 hover:underline">
                        {u.rule_name}
                      </Link>{' '}
                      <span className="text-ink-subtle">v{u.version_number}</span>
                      <span className="block text-[11px] text-ink-subtle">
                        effective {u.effective_from} → {u.effective_to ?? 'open-ended'}
                      </span>
                    </td>
                    <td>
                      <StatusPill status={VERSION_STATUS[u.status as RuleVersionStatus]?.pill ?? 'unknown'}>{VERSION_STATUS[u.status as RuleVersionStatus]?.label ?? u.status}</StatusPill>
                    </td>
                    <td className="num">{u.runs}</td>
                    <td className="num">{u.applications}</td>
                    <td>
                      <span className="flex flex-wrap gap-1.5">
                        {Object.entries(u.latest_outcomes).map(([o, n]) => (
                          <StatusPill key={o} status={RULE_OUTCOME[o as SimOutcome]?.pill ?? 'unknown'}>
                            {RULE_OUTCOME[o as SimOutcome]?.label ?? o}: {n}
                          </StatusPill>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          icon={<History className="size-4" />}
          title={
            <span className="flex items-center gap-2">
              Validation history <MetricInfo def={d.get('validation.runs')} />
            </span>
          }
          description="Every run in the window, newest first. Runs are immutable and linked to the run they followed."
        />
        {rules.isPending ? (
          <LoadingRows rows={4} label="Loading validation history" />
        ) : rules.isError ? null : rules.data.runs.items.length === 0 ? (
          <p className="px-5 py-6 text-[13px] text-ink-subtle">No validation runs in this window.</p>
        ) : (
          <>
            <ul className="divide-y divide-line">
              {rules.data.runs.items.map((r) => (
                <li key={r.run_id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-2.5 text-[12.5px]">
                  <span className="min-w-0">
                    <Link to={`/applications/${r.application_id}`} className="font-medium text-violet-700 hover:underline">
                      {r.application_reference}
                    </Link>
                    <span className="ml-2 text-ink-muted">
                      {formatDateTime(r.created_at)} · evaluated as of {r.evaluation_date} · {r.trigger === 'correction' ? 'after a correction' : 'manual'} · {r.rule_versions} rule version
                      {r.rule_versions === 1 ? '' : 's'} · {r.created_by}
                    </span>
                  </span>
                  <span className="flex flex-wrap gap-1.5">
                    {Object.entries(r.summary)
                      .filter(([, n]) => n > 0)
                      .map(([o, n]) => (
                        <StatusPill key={o} status={RULE_OUTCOME[o as SimOutcome]?.pill ?? 'unknown'}>
                          {RULE_OUTCOME[o as SimOutcome]?.label ?? o}: {n}
                        </StatusPill>
                      ))}
                  </span>
                </li>
              ))}
            </ul>
            <Pager label="Validation history pages" total={rules.data.runs.total} limit={RUNS_PAGE} offset={runsOffset} onChange={setRunsOffset} />
          </>
        )}
      </Card>

      <Card>
        <CardHeader
          icon={<GitCommitVertical className="size-4" />}
          title={
            <span className="flex items-center gap-2">
              Rule governance history <MetricInfo def={d.get('rules.governance')} />
            </span>
          }
          description="Lifecycle of every rule version: who drafted, submitted, approved, rejected or retired it, and whether approval was four-eyes."
          action={
            gov.data && (
              <label className="flex items-center gap-2 text-[12.5px] text-ink-muted">
                Rule
                <Select
                  size="sm" full={false}
                  value={ruleId}
                  onChange={(e) => {
                    setRuleId(e.target.value)
                    setEventsOffset(0)
                  }}
                >
                  <option value="">All rules</option>
                  {gov.data.rules.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </Select>
              </label>
            )
          }
        />
        {gov.isPending ? (
          <LoadingRows rows={4} label="Loading rule governance history" />
        ) : gov.isError ? (
          <ErrorState error={gov.error} onRetry={() => gov.refetch()} compact />
        ) : gov.data.items.length === 0 ? (
          <p className="px-5 py-6 text-[13px] text-ink-subtle">No rule governance events in this window.</p>
        ) : (
          <>
            <ol className="divide-y divide-line">
              {gov.data.items.map((e) => (
                <li key={`${e.version_id}-${e.event}`} className="grid gap-1 px-5 py-2.5 text-[12.5px] md:grid-cols-[150px_1fr_auto] md:items-center">
                  <span>
                    <StatusPill status={EVENT_LABEL[e.event].pill}>{EVENT_LABEL[e.event].label}</StatusPill>
                  </span>
                  <span className="min-w-0">
                    <Link to={`/compliance/rules/${e.rule_id}`} className="font-medium text-violet-700 hover:underline">
                      {e.rule_name}
                    </Link>{' '}
                    <span className="text-ink-subtle">v{e.version_number}</span>
                    <span className="ml-2 text-ink-muted">
                      {e.actor?.full_name ?? 'unknown'} · {formatDateTime(e.at)}
                    </span>
                    {e.detail && <span className="block truncate text-ink-subtle">{e.detail}</span>}
                  </span>
                  <span className="flex items-center gap-2 text-[11.5px] text-ink-subtle">
                    {e.four_eyes === true && (
                      <span className="inline-flex items-center gap-1 text-pass">
                        <ShieldCheck className="size-3.5" aria-hidden /> Four-eyes
                      </span>
                    )}
                    {e.four_eyes === false && (
                      <span className="inline-flex items-center gap-1 text-fail">
                        <ShieldAlert className="size-3.5" aria-hidden /> Same person
                      </span>
                    )}
                    <span className="font-mono" title={e.content_hash}>
                      {shortHash(e.content_hash, 8)}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
            <Pager label="Rule governance pages" total={gov.data.total} limit={EVENTS_PAGE} offset={eventsOffset} onChange={setEventsOffset} />
          </>
        )}
      </Card>
    </div>
  )
}
