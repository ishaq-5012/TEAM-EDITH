import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Activity, FileSearch, FlaskConical, FolderKanban, Scale, UserCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardHeader } from '../../components/ui/Card'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { ApplicationStatus, DocumentStatus, InsightsOverview, MetricDefinition, ReviewCategory, SimOutcome } from '../../lib/types'
import { APP_STATUS, DOC_STATUS } from '../applications/statusMeta'
import { RULE_OUTCOME } from '../compliance/ruleMeta'
import { OUTCOME } from '../evidence/evidenceMeta'
import { CATEGORY } from '../review/reviewMeta'
import { BarRows, Basis, DailyBars, MetricInfo, MetricTile, SeverityMatrix } from './MetricParts'
import { FIELD_STATUS, OCR_LABEL, OUTCOME_CATEGORY, RULE_OUTCOMES, SERIES, SEVERITIES, outcomeRows, pct, useDefinitions, useInsightsWindow } from './insightsMeta'
import { WindowFilters } from './WindowFilters'


export function SyntheticNotice({ count, included }: { count: number; included: boolean }) {
  if (!count) return null
  return (
    <p role="note" className="flex items-center gap-2 rounded-xl border border-info/20 bg-info-bg px-4 py-2.5 text-[12.5px] text-info">
      <FlaskConical className="size-4 shrink-0" aria-hidden />
      {included
        ? `Includes ${count} test record${count === 1 ? '' : 's'}. Untick “Include test records” to exclude them.`
        : `${count} test record${count === 1 ? ' is' : 's are'} excluded.`}
    </p>
  )
}

export function Panel({ title, def, icon, children, action }: { title: string; def?: MetricDefinition; icon: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <Card className="min-w-0">
      <CardHeader
        icon={icon}
        title={
          <span className="flex items-center gap-2">
            {title} <MetricInfo def={def} />
          </span>
        }
        description={<Basis def={def} />}
        action={action}
      />
      <div className="p-4">{children}</div>
    </Card>
  )
}

function useOverview() {
  const w = useInsightsWindow()
  const q = useQuery({ queryKey: ['insights', 'overview', w.query], queryFn: () => api.insightsOverview(w.query), placeholderData: keepPreviousData })
  return { ...q, window: w }
}

export function InsightsPanel() {
  const q = useOverview()
  const { byKey } = useDefinitions()
  return (
    <div className="space-y-5">
      <WindowFilters />
      {q.isPending ? (
        <LoadingRows rows={8} label="Loading insights" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <>
          {q.data.scope.applications === 0 && (q.window.value.application_type || !q.window.value.include_synthetic) && (
            <p role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-review/30 bg-review-bg px-4 py-3 text-[13px] text-ink">
              <span>No applications match the current filters. The application type or excluded test records may be hiding the data.</span>
              <button type="button" className="font-semibold text-violet-700 underline" onClick={() => q.window.update({ application_type: '', include_synthetic: true })}>Show all applications</button>
            </p>
          )}
          <OverviewBody o={q.data} d={byKey} />
        </>
      )}
    </div>
  )
}

function OverviewBody({ o, d }: { o: InsightsOverview; d: Map<string, MetricDefinition> }) {
  const c = o.current
  const w = o.window
  const f = c.findings
  return (
    <div className="space-y-5">
      <p className="text-[12.5px] text-ink-subtle">
        {o.scope.applications} application{o.scope.applications === 1 ? '' : 's'} in scope · window {o.scope.date_from} to {o.scope.date_to} (UTC) ·
        computed {formatDateTime(o.generated_at)}. “Now” metrics describe current records; “In window” metrics count events inside the window.
      </p>
      <SyntheticNotice count={o.scope.synthetic_applications} included={o.scope.include_synthetic} />

      <section aria-labelledby="sep-h" className="space-y-2">
        <h2 id="sep-h" className="text-sm font-semibold">Engine results and human decisions</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <MetricTile def={d.get('findings.engine_failures')} label="Rule failures (engine)" value={f.engine_failures} tone="fail" sub="latest run per application" to="/review?category=failure" />
          <MetricTile def={d.get('findings.review_required')} label="Review required (engine)" value={f.review_required} tone="review" sub={`uncertainty rate ${pct(f.rates.uncertainty)}`} to="/review?category=uncertain" />
          <MetricTile def={d.get('findings.insufficient')} label="Insufficient evidence" value={f.insufficient} tone="missing" sub={`rate ${pct(f.rates.insufficient)} of ${f.rates.denominator}`} to="/review?category=missing" />
          <MetricTile def={d.get('review.human_confirmed')} label="Confirmed failures (human)" value={c.human.confirmed} tone="fail" sub="a person confirmed" to="/review?status=confirmed" />
          <MetricTile def={d.get('review.human_dismissed')} label="Dismissed findings (human)" value={c.human.dismissed} tone="pass" sub="a person dismissed" to="/review?status=dismissed" />
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Rule findings by outcome" def={d.get('findings.current')} icon={<Scale className="size-4" />}>
          <p className="mb-3 text-[12px] text-ink-subtle">
            {f.applications_with_run} application{f.applications_with_run === 1 ? '' : 's'} validated · {f.applications_without_run} not validated yet
          </p>
          <BarRows rows={outcomeRows(f.by_outcome)} label="Rule findings by outcome" empty="No application in scope has been validated." />
          <div className="mt-4">
            <SeverityMatrix
              label="Rule findings by outcome and severity"
              cells={f.by_outcome_severity}
              outcomes={RULE_OUTCOMES}
              severities={SEVERITIES}
              outcomeLabel={(x) => RULE_OUTCOME[x as SimOutcome]?.label ?? x}
              hrefFor={(x, s) => (OUTCOME_CATEGORY[x] ? `/review?category=${OUTCOME_CATEGORY[x]}&severity=${s}` : undefined)}
            />
          </div>
        </Panel>
        <Panel title="Cross-document findings" def={d.get('evidence.current')} icon={<Activity className="size-4" />}>
          <BarRows
            label="Cross-document findings by outcome"
            empty="No evidence analysis has been run for applications in scope."
            rows={(['fail', 'review', 'insufficient', 'pass'] as const)
              .filter((x) => c.evidence.by_outcome[x] !== undefined)
              .map((x) => ({ key: x, label: OUTCOME[x].label, pill: OUTCOME[x].pill, count: c.evidence.by_outcome[x] }))}
          />
          <div className="mt-4">
            <SeverityMatrix label="Cross-document findings by outcome and severity" cells={c.evidence.by_outcome_severity} outcomes={['fail', 'review', 'insufficient', 'pass']} severities={SEVERITIES} outcomeLabel={(x) => OUTCOME[x as keyof typeof OUTCOME]?.label ?? x} />
          </div>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Applications" def={d.get('applications.by_status')} icon={<FolderKanban className="size-4" />}>
          <BarRows
            label="Applications by status"
            rows={(Object.keys(APP_STATUS) as ApplicationStatus[]).map((s) => ({ key: s, label: APP_STATUS[s].label, pill: APP_STATUS[s].pill, count: c.applications.by_status[s] ?? 0, to: `/applications?status=${s}` }))}
          />
          <h3 className="mt-5 mb-1 flex items-center gap-2 text-[13px] font-semibold">
            Created per day ({w.applications_created.total}) <MetricInfo def={d.get('applications.created')} /> <Basis def={d.get('applications.created')} />
          </h3>
          <DailyBars label="Applications created per day" data={w.applications_created.by_day} series={[{ key: 'count', label: 'Created', color: SERIES[0] }]} />
        </Panel>
        <Panel title="Validation runs" def={d.get('validation.runs')} icon={<Scale className="size-4" />}>
          <p className="mb-2 text-[12.5px] text-ink-muted">
            {w.validation.runs} run{w.validation.runs === 1 ? '' : 's'} in the window · {w.validation.cases.applications} application{w.validation.cases.applications === 1 ? '' : 's'} evaluated
          </p>
          <DailyBars
            label="Validation runs per day by trigger"
            data={w.validation.by_day}
            series={[
              { key: 'manual', label: 'Manual', color: SERIES[0] },
              { key: 'correction', label: 'After a correction', color: SERIES[1] },
            ]}
          />
          <h3 className="mt-4 mb-2 flex items-center gap-2 text-[13px] font-semibold">
            Cases evaluated in the window <MetricInfo def={d.get('validation.cases')} />
          </h3>
          <BarRows rows={outcomeRows(w.validation.cases.by_outcome, false)} label="Cases evaluated in the window by outcome" empty="No validation runs in this window." />
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel title="Review backlog" def={d.get('review.backlog')} icon={<UserCheck className="size-4" />}>
          <div className="mb-3 grid grid-cols-2 gap-2 text-[12.5px]">
            <Stat label="Active items" value={c.review.backlog} to="/review" />
            <Stat label="Unassigned" value={c.review.unassigned} to="/review?assignee=unassigned" def={d.get('review.unassigned')} />
            <Stat label="Opened in window" value={w.review.opened} def={d.get('review.opened')} />
            <Stat label="Decisions in window" value={w.review.confirmed + w.review.dismissed} def={d.get('review.decisions')} />
          </div>
          <BarRows
            label="Active review items by category"
            empty="The review queue is empty."
            rows={(Object.keys(CATEGORY) as ReviewCategory[]).map((k) => ({ key: k, label: CATEGORY[k].label, pill: CATEGORY[k].pill, count: c.review.backlog_by_category[k] ?? 0, to: `/review?category=${k}` }))}
          />
        </Panel>
        <Panel title="Documents and processing" def={d.get('documents.by_status')} icon={<FileSearch className="size-4" />}>
          <BarRows
            label="Documents by status"
            rows={(Object.keys(DOC_STATUS) as DocumentStatus[]).map((s) => ({ key: s, label: DOC_STATUS[s].label, pill: DOC_STATUS[s].pill, count: c.documents.by_status[s] ?? 0 }))}
          />
          <p className="mt-3 flex items-center gap-2 text-[12.5px] text-ink-muted">
            Jobs finished in window: {w.processing.finished} · failure rate {pct(w.processing.failure_rate)} <MetricInfo def={d.get('processing.jobs')} />
          </p>
        </Panel>
        <Panel title="Extraction quality" def={d.get('extraction.fields')} icon={<FileSearch className="size-4" />}>
          <BarRows
            label="Extracted fields by status"
            empty="No document in scope has been extracted."
            rows={Object.entries(FIELD_STATUS).map(([k, m]) => ({ key: k, label: m.label, pill: m.pill, count: c.extraction.fields_by_status[k] ?? 0 }))}
          />
          <div className="mt-3 grid grid-cols-2 gap-2 text-[12.5px]">
            <Stat label="Correction rate" value={pct(c.extraction.correction_rate.rate)} sub={`${c.extraction.correction_rate.corrected} of ${c.extraction.correction_rate.eligible}`} def={d.get('extraction.correction_rate')} />
            <Stat label="Corrections in window" value={w.extraction.corrections} def={d.get('extraction.corrections')} />
          </div>
          <h3 className="mt-3 mb-1 flex items-center gap-2 text-[12.5px] font-semibold">
            Pages by OCR status <MetricInfo def={d.get('extraction.pages')} />
          </h3>
          <ul className="space-y-0.5 text-[12.5px] text-ink-muted">
            {Object.entries(c.extraction.pages_by_ocr_status).map(([k, n]) => (
              <li key={k} className="flex justify-between">
                <span>{OCR_LABEL[k] ?? k}</span>
                <span className="tabular text-ink">{n}</span>
              </li>
            ))}
            {!Object.keys(c.extraction.pages_by_ocr_status).length && <li className="text-ink-subtle">No pages extracted.</li>}
          </ul>
        </Panel>
      </div>
    </div>
  )
}

export function Stat({ label, value, sub, to, def }: { label: string; value: ReactNode; sub?: ReactNode; to?: string; def?: MetricDefinition }) {
  const inner = (
    <>
      <span className="flex items-center gap-1 text-ink-subtle">
        {label} <MetricInfo def={def} />
      </span>
      <span className="tabular block text-[18px] font-semibold text-ink">{value}</span>
      {sub && <span className="block text-[11.5px] text-ink-subtle">{sub}</span>}
    </>
  )
  return to ? (
    <Link to={to} className="rounded-lg bg-navy-50/70 px-3 py-2 hover:bg-navy-50">
      {inner}
    </Link>
  ) : (
    <div className="rounded-lg bg-navy-50/70 px-3 py-2">{inner}</div>
  )
}
