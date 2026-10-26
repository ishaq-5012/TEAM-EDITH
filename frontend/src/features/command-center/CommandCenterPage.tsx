import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowUpRight, Cpu, Fingerprint, History, Scale, Users } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { Link } from 'react-router-dom'
import { MODULES } from '../../components/layout/modules'
import { Card, CardHeader } from '../../components/ui/Card'
import { PageContainer } from '../../components/layout/PageContainer'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { formatRelative, roleLabel, shortHash } from '../../lib/format'
import { AiStatusCard } from '../ai/AiStatusCard'
import { Panel, SyntheticNotice } from '../insights/InsightsPanel'
import { BarRows, DailyBars, MetricTile } from '../insights/MetricParts'
import { SERIES, daysAgo, outcomeRows, pct, todayUtc, useDefinitions } from '../insights/insightsMeta'
import { DURATION, stagger } from '../../lib/motion'
import { useAuth } from '../auth/AuthProvider'
import { ActionLabel } from '../governance/ActionLabel'

function CapabilitiesCard() {
  const q = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  return (
    <Card>
      <CardHeader icon={<Cpu className="size-4" />} title="Processing capabilities" description="Detected on the server at request time." />
      {q.isPending ? (
        <LoadingRows rows={4} label="Loading capabilities" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <ul className="divide-y divide-line">
          {q.data.capabilities.map((c) => (
            <li key={c.key} className="flex items-start justify-between gap-4 px-5 py-3.5">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{c.label}</p>
                <p className="mt-0.5 text-[12.5px] leading-5 text-ink-muted">{c.detail}</p>
              </div>
              <StatusPill status={c.available ? 'pass' : 'missing'}>{c.available ? 'Available' : 'Unavailable'}</StatusPill>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function IntegrityCard() {
  const q = useQuery({ queryKey: ['audit', 'verify'], queryFn: api.verifyAudit })
  return (
    <Card>
      <CardHeader icon={<Fingerprint className="size-4" />} title="Audit chain integrity" description="Every event is SHA-256 chained to the previous one." />
      {q.isPending ? (
        <LoadingRows rows={2} label="Verifying audit chain" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-4 p-5">
          <div className="flex items-center justify-between">
            <StatusPill status={q.data.valid ? 'pass' : 'fail'}>{q.data.valid ? 'Chain verified' : 'Integrity failure'}</StatusPill>
            <span className="tabular text-[13px] text-ink-muted">{q.data.checked.toLocaleString()} events checked</span>
          </div>
          {!q.data.valid && (
            <p className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
              First invalid event #{q.data.first_invalid_seq}: {q.data.reason}
            </p>
          )}
          <dl className="rounded-lg bg-navy-50 px-3 py-2.5">
            <dt className="text-[11px] font-medium uppercase tracking-wider text-ink-subtle">Head hash</dt>
            <dd className="mt-0.5 font-mono text-xs break-all text-ink">{q.data.head_hash ?? '—'}</dd>
          </dl>
        </div>
      )}
    </Card>
  )
}

function RecentActivity() {
  const q = useQuery({ queryKey: ['audit', 'events', { limit: 8 }], queryFn: () => api.auditEvents({ limit: 8 }) })
  return (
    <Card>
      <CardHeader
        icon={<History className="size-4" />}
        title="Recent activity"
        description="Latest entries from the audit history."
        action={
          <Link to="/governance" className="inline-flex items-center gap-1 text-[13px] font-medium text-violet-700 hover:underline">
            Full history <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        }
      />
      {q.isPending ? (
        <LoadingRows rows={5} label="Loading activity" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.items.length === 0 ? (
        <EmptyState icon={<Activity className="size-6" />} title="No activity yet" />
      ) : (
        <ol className="divide-y divide-line">
          {q.data.items.map((e) => (
            <li key={e.id} className="flex items-center gap-4 px-5 py-3">
              <ActionLabel action={e.action} outcome={e.outcome} />
              <p className="min-w-0 flex-1 truncate text-[13px] text-ink-muted">
                {e.summary} {e.actor_email && <span className="text-ink-subtle">· {e.actor_email}</span>}
              </p>
              <time dateTime={e.occurred_at} className="shrink-0 text-xs text-ink-subtle" title={e.occurred_at}>
                {formatRelative(e.occurred_at)}
              </time>
              <span className="hidden shrink-0 font-mono text-[11px] text-ink-subtle md:inline" title={e.entry_hash}>
                {shortHash(e.entry_hash, 8)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

function ModuleGrid() {
  const { can } = useAuth()
  const reduce = useReducedMotion()
  const visible = MODULES.filter((m) => m.path !== '/' && can(m.permission))
  return (
    <section aria-labelledby="modules-h" className="pt-3">
      <h2 id="modules-h" className="mb-3 text-sm font-semibold text-ink">
        Modules
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((m, i) => (
          <motion.div
            key={m.path}
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: stagger(i), duration: DURATION.base }}
          >
            <Link
              to={m.path}
              className="interactive group flex h-full flex-col rounded-[var(--radius-card)] border border-line bg-surface p-4 shadow-[var(--shadow-card)]"
            >
              <div className="flex items-center justify-between">
                <span className="grid size-9 place-items-center rounded-lg bg-navy-900 text-violet-400">
                  <m.icon className="size-[18px]" aria-hidden />
                </span>
                {m.status === 'available' ? (
                  <StatusPill status="pass">Available</StatusPill>
                ) : (
                  <StatusPill status="info">In a later phase</StatusPill>
                )}
              </div>
              <h3 className="mt-3 text-sm font-semibold text-ink group-hover:text-violet-700">{m.label}</h3>
              <p className="mt-1 text-[13px] leading-5 text-ink-muted">{m.summary}</p>
            </Link>
          </motion.div>
        ))}
      </div>
    </section>
  )
}

function AdminOperations() {
  const users = useQuery({ queryKey: ['users', 'admin-overview'], queryFn: () => api.listUsers({ limit: 100 }) })
  const applications = useQuery({ queryKey: ['applications', 'admin-workflow'], queryFn: () => api.applications({ status: ['needs_review'], scope: 'all', limit: 100 }) })
  const escalations = useQuery({ queryKey: ['reviews', 'admin-escalated'], queryFn: () => api.reviews({ status: 'escalated', limit: 1 }) })
  const pending = applications.data?.items ?? []
  const reviewerCount = pending.filter((app) => app.review_stage === 'reviewer').length
  const auditorCount = pending.filter((app) => app.review_stage === 'audit').length
  const activeUsers = users.data?.items.filter((user) => user.is_active).length
  return (
    <section aria-labelledby="admin-operations" className="space-y-3">
      <div>
        <h2 id="admin-operations" className="text-sm font-semibold">Admin operations</h2>
        <p className="mt-1 text-[12.5px] text-ink-muted">Live staff access and case handoffs. Open a queue to act on its records.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Link to="/governance?tab=users" className="interactive rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
          <Users className="mb-3 size-5 text-violet-700" aria-hidden />
          <p className="text-2xl font-semibold tabular-nums">{users.isPending ? '…' : users.isError ? '—' : activeUsers}</p>
          <p className="text-[13px] font-medium">Active staff accounts</p>
          <p className="mt-1 text-[12px] text-ink-muted">Manage roles and sessions →</p>
        </Link>
        <Link to="/applications?status=needs_review" className="interactive rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
          <p className="text-2xl font-semibold tabular-nums">{applications.isPending ? '…' : applications.isError ? '—' : reviewerCount}</p>
          <p className="text-[13px] font-medium">At reviewer</p>
          <p className="mt-1 text-[12px] text-ink-muted">Inspect assigned applications →</p>
        </Link>
        <Link to="/review?status=escalated" className="interactive rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
          <p className="text-2xl font-semibold tabular-nums">{escalations.isPending ? '…' : escalations.isError ? '—' : escalations.data?.total}</p>
          <p className="text-[13px] font-medium">Compliance escalations</p>
          <p className="mt-1 text-[12px] text-ink-muted">Manager decisions needed →</p>
        </Link>
        <Link to="/review" className="interactive rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
          <p className="text-2xl font-semibold tabular-nums">{applications.isPending ? '…' : applications.isError ? '—' : auditorCount}</p>
          <p className="text-[13px] font-medium">At auditor</p>
          <p className="mt-1 text-[12px] text-ink-muted">Awaiting final decision →</p>
        </Link>
      </div>
      {(users.isError || applications.isError || escalations.isError) && <p role="alert" className="text-[12px] text-fail">Some admin counts could not load. Open the linked section to retry.</p>}
    </section>
  )
}

function RoleWorklist() {
  const { user } = useAuth()
  if (!user || user.role === 'admin') return null
  const focus = user.role === 'compliance_manager'
    ? { title: 'Compliance decisions', detail: 'Review items escalated by an officer, then decide or return them with a reason.', to: '/review?status=escalated' }
    : user.role === 'auditor'
      ? { title: 'Final audit', detail: 'Confirm the reviewer handoff, documents and evidence before approving.', to: '/review' }
      : user.role === 'reviewer'
        ? { title: 'Officer review', detail: 'Inspect new applications and escalate unresolved findings to compliance.', to: '/review' }
        : { title: 'Rule governance', detail: 'Maintain and independently approve the rules used for review.', to: '/compliance' }
  return <Card className="p-5">
    <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Your next step</p>
    <h2 className="mt-1 text-base font-semibold">{focus.title}</h2>
    <p className="mt-1 text-[13px] text-ink-muted">{focus.detail}</p>
    <Link to={focus.to} className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-violet-700 hover:underline">Open worklist <ArrowUpRight className="size-4" aria-hidden /></Link>
  </Card>
}

const COMMAND_DAYS = 30

/** Current-state tiles and the last 30 days, scoped by the server to applications this user can see. */
function OperationsOverview() {
  const { can } = useAuth()
  const params = { from: daysAgo(COMMAND_DAYS - 1), to: todayUtc() }
  const q = useQuery({ queryKey: ['insights', 'overview', params], queryFn: () => api.insightsOverview(params) })
  const { byKey: d } = useDefinitions()
  if (q.isPending) return <LoadingRows rows={4} label="Loading operations overview" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const o = q.data
  const c = o.current
  const f = c.findings
  return (
    <section aria-labelledby="ops-h" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 id="ops-h" className="text-sm font-semibold text-ink">
          Operations · {o.scope.applications} application{o.scope.applications === 1 ? '' : 's'} you can see
        </h2>
        {can('audit:read') && (
          <Link to="/governance?tab=insights" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-violet-700 hover:underline">
            Governance & Insights <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        )}
      </div>
      <SyntheticNotice count={o.scope.synthetic_applications} included />
      {o.scope.applications === 0 ? (
        <Card>
          <EmptyState icon={<Activity className="size-6" />} title="No applications yet" className="py-10">
            Metrics appear here as applications are created, processed, validated and reviewed. Nothing is estimated or filled in.
          </EmptyState>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
            <MetricTile def={d.get('applications.by_status')} label="Applications" value={c.applications.total} sub={`${c.applications.by_status.needs_review ?? 0} need review`} to="/applications?status=needs_review" />
            <MetricTile def={d.get('review.backlog')} label="Review backlog" value={c.review.backlog} sub={`${c.review.unassigned} unassigned`} to="/review" tone="info" />
            <MetricTile def={d.get('findings.engine_failures')} label="Rule failures (engine)" value={f.engine_failures} tone="fail" sub="latest run per application" to="/review?category=failure" />
            <MetricTile def={d.get('findings.review_required')} label="Review required (engine)" value={f.review_required} tone="review" sub={`uncertainty ${pct(f.rates.uncertainty)}`} to="/review?category=uncertain" />
            <MetricTile def={d.get('findings.insufficient')} label="Insufficient evidence" value={f.insufficient} tone="missing" sub={`rate ${pct(f.rates.insufficient)}`} to="/review?category=missing" />
            <MetricTile def={d.get('review.human_confirmed')} label="Confirmed failures (human)" value={c.human.confirmed} tone="fail" sub={`${c.human.dismissed} dismissed`} to="/review?status=confirmed" />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Rule findings by outcome" def={d.get('findings.current')} icon={<Scale className="size-4" />}>
              <BarRows rows={outcomeRows(f.by_outcome)} label="Rule findings by outcome" empty="No application you can see has been validated yet." />
            </Panel>
            <Panel title={`Validation runs, last ${COMMAND_DAYS} days`} def={d.get('validation.runs')} icon={<Activity className="size-4" />}>
              <DailyBars
                label={`Validation runs per day, last ${COMMAND_DAYS} days`}
                data={o.window.validation.by_day}
                series={[
                  { key: 'manual', label: 'Manual', color: SERIES[0] },
                  { key: 'correction', label: 'After a correction', color: SERIES[1] },
                ]}
              />
            </Panel>
          </div>
        </>
      )}
    </section>
  )
}

export function CommandCenterPage() {
  const { user, can } = useAuth()
  const first = user?.full_name.split(/\s+/)[0]
  return (
    <PageContainer
      eyebrow="Command Center"
      title={`Welcome back${first ? `, ${first}` : ''}`}
      description={`Signed in as ${roleLabel(user?.role ?? '')}. This overview shows only live data from the VerifyFlow server.`}
    >
      {user?.role === 'admin' ? <AdminOperations /> : <RoleWorklist />}
      <OperationsOverview />
      <div className="grid gap-5 lg:grid-cols-2">
        <CapabilitiesCard />
        {can('audit:read') && <IntegrityCard />}
        <AiStatusCard />
      </div>
      {can('audit:read') && <RecentActivity />}
      <ModuleGrid />
    </PageContainer>
  )
}
