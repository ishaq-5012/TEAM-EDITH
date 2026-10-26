import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowRight, Inbox, Search, UserCheck } from 'lucide-react'
import { useRef, useState, type KeyboardEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageContainer } from '../../components/layout/PageContainer'
import { Card } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { useAuth } from '../auth/AuthProvider'
import { formatRelative } from '../../lib/format'
import type { ReviewCategory, Severity } from '../../lib/types'
import { SEVERITY } from '../evidence/evidenceMeta'
import { CATEGORY, REVIEW_STATUS } from './reviewMeta'
import { Select } from '../../components/ui/Field'

const STATUS_TABS = [
  { value: 'active', label: 'Active' },
  { value: 'open', label: 'Open' },
  { value: 'awaiting_document', label: 'Awaiting document' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'closed', label: 'Closed' },
  { value: 'all', label: 'All' },
]


export function ReviewQueuePage() {
  const { user } = useAuth()
  const isAuditor = user?.role === 'auditor'
  const isManager = user?.role === 'compliance_manager'
  const [params, setParams] = useSearchParams()
  const filters = {
    status: params.get('status') ?? (isManager ? 'escalated' : 'active'),
    category: (params.get('category') ?? '') as ReviewCategory | '',
    assignee: params.get('assignee') ?? '',
    severity: (params.get('severity') ?? '') as Severity | '',
    application_id: params.get('application_id') ?? '',
    q: params.get('q') ?? '',
  }
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }
  const q = useQuery({ queryKey: ['reviews', filters], queryFn: () => api.reviews({ ...filters, limit: 100 }), placeholderData: keepPreviousData })
  const pending = useQuery({
    queryKey: ['review-applications', filters.application_id, isAuditor],
    queryFn: () => api.applications({ status: ['needs_review'], scope: isAuditor ? 'all' : 'mine', limit: 100 }),
    enabled: !isManager,
  })
  const [search, setSearch] = useState(filters.q)
  const rows = useRef<(HTMLAnchorElement | null)[]>([])

  // Arrow keys move through the queue; Enter follows the focused link (native behaviour).
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    const items = rows.current.filter(Boolean) as HTMLAnchorElement[]
    const i = items.indexOf(document.activeElement as HTMLAnchorElement)
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : Math.min(items.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))
    items[next]?.focus()
    e.preventDefault()
  }

  const counts = q.data?.counts
  return (
    <PageContainer
      eyebrow="Review & Resolution"
      title="Review queue"
      description={isManager
        ? 'Escalated findings arrive here after a reviewer identifies an issue. Decide or return each item with a recorded reason before the reviewer can hand the application to the auditor.'
        : 'Rule results that need human judgement: failures, uncertain results and missing evidence. Every decision is recorded with its reason and can’t be erased.'}
    >
      {!isManager && <Card className="mb-5">
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">{isAuditor ? 'Applications awaiting auditor approval' : 'Applications awaiting officer review'}</h2>
          <p className="mt-1 text-[12.5px] text-ink-muted">{isAuditor ? 'Independently confirm the reviewed documents and rule results before approval.' : 'Includes applications whose rules passed. Review the documents and evidence before sending one to the auditor.'}</p>
        </div>
        {pending.isPending ? <LoadingRows rows={2} label="Loading assigned applications" /> : pending.isError ? (
          <ErrorState error={pending.error} onRetry={() => pending.refetch()} />
        ) : pending.data.items.filter((app) => app.review_stage === (isAuditor ? 'audit' : 'reviewer') && (!filters.application_id || app.id === filters.application_id)).length === 0 ? (
          <p className="px-5 py-4 text-[13px] text-ink-muted">{isAuditor ? 'No applications are awaiting auditor approval.' : 'No applications assigned to you are awaiting officer review.'}</p>
        ) : (
          <ul className="divide-y divide-line">
            {pending.data.items.filter((app) => app.review_stage === (isAuditor ? 'audit' : 'reviewer') && (!filters.application_id || app.id === filters.application_id)).map((app) => (
              <li key={app.id}>
                <Link to={`/applications/${app.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-navy-50/50">
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{app.reference} · {app.title}</span>
                    <span className="text-[12px] text-ink-muted">{app.institution?.name ?? 'Institution'} · {app.document_count} documents</span>
                  </span>
                  <StatusPill status="review">{isAuditor ? 'Audit pending' : 'Needs review'}</StatusPill>
                  <ArrowRight className="size-4 text-ink-subtle" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>}
      {isManager && <p role="status" className="mb-5 rounded-xl border border-line bg-surface px-5 py-4 text-[13px] text-ink-muted">
        Compliance review is conditional: a reviewer opens a finding and selects <strong>Escalate</strong>. Once you decide or return it, the reviewer continues the application. Applications with no escalated issue go directly from reviewer to auditor.
      </p>}
      <Card className="p-4">
        <div role="tablist" aria-label="Status" className="mb-3 flex flex-wrap gap-1">
          {STATUS_TABS.map((t) => {
            const count = t.value in REVIEW_STATUS ? counts?.status[t.value as keyof typeof REVIEW_STATUS] : undefined
            return (
              <button
                key={t.value}
                role="tab"
                type="button"
                aria-selected={filters.status === t.value}
                onClick={() => set('status', t.value === (isManager ? 'escalated' : 'active') ? '' : t.value)}
                className={cn('rounded-lg px-3 py-1.5 text-[13px] font-medium', filters.status === t.value ? 'bg-navy-900 text-white' : 'text-ink-muted hover:bg-navy-50')}
              >
                {t.label}
                {count ? <span className="ml-1.5 tabular-nums opacity-75">{count}</span> : null}
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <form
            role="search"
            className="relative min-w-56 flex-1"
            onSubmit={(e) => {
              e.preventDefault()
              set('q', search.trim())
            }}
          >
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
            <input
              aria-label="Search rule, application reference or title"
              placeholder="Search rule, reference or title — press Enter"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-line-strong bg-surface pr-3 pl-8 text-[13px]"
            />
          </form>
          <Select aria-label="Category" size="sm" full={false} value={filters.category} onChange={(e) => set('category', e.target.value)}>
            <option value="">All categories</option>
            {(Object.keys(CATEGORY) as ReviewCategory[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY[c].label}
                {counts?.category[c] ? ` (${counts.category[c]})` : ''}
              </option>
            ))}
          </Select>
          <Select aria-label="Severity" size="sm" full={false} value={filters.severity} onChange={(e) => set('severity', e.target.value)}>
            <option value="">Any severity</option>
            {(Object.keys(SEVERITY) as Severity[]).map((s) => (
              <option key={s} value={s}>
                {SEVERITY[s]}
              </option>
            ))}
          </Select>
          <Select aria-label="Assignee" size="sm" full={false} value={filters.assignee} onChange={(e) => set('assignee', e.target.value)}>
            <option value="">Anyone</option>
            <option value="me">Assigned to me{counts ? ` (${counts.mine})` : ''}</option>
            <option value="unassigned">Unassigned</option>
          </Select>
          {filters.application_id && (
            <button type="button" onClick={() => set('application_id', '')} className="h-9 rounded-lg border border-violet-300 bg-violet-50 px-3 text-[12.5px] text-violet-700">
              One application only ✕
            </button>
          )}
        </div>
      </Card>

      <Card>
        {q.isPending ? (
          <LoadingRows rows={5} label="Loading review queue" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <EmptyState icon={<Inbox className="size-6" />} title={filters.status === 'active' ? 'Nothing needs review' : 'No items match'}>
            {filters.status === 'active'
              ? 'Items appear here when a validation run produces a failed, uncertain or insufficient-evidence result.'
              : 'Try a different status or clear the filters.'}
          </EmptyState>
        ) : (
          <>
            <p className="border-b border-line px-5 py-2 text-[12px] text-ink-subtle" id="queue-help">
              {q.data.total} item{q.data.total === 1 ? '' : 's'} · ordered by priority (severity + category) then age · use ↑ ↓ to move, Enter to open
            </p>
            <ul className="divide-y divide-line" aria-describedby="queue-help" onKeyDown={onListKey}>
              {q.data.items.map(({ item, application }, i) => {
                const st = REVIEW_STATUS[item.status]
                const cat = CATEGORY[item.category]
                return (
                  <li key={item.id}>
                    <Link
                      ref={(el) => {
                        rows.current[i] = el
                      }}
                      to={`/review/${item.id}`}
                      className="group flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-3 focus-visible:bg-violet-50 focus-visible:outline-none hover:bg-navy-50/50"
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-navy-50 text-[12px] font-semibold tabular-nums text-ink-muted" title="Priority">
                        {item.priority}
                      </span>
                      <span className="min-w-56 flex-1">
                        <span className="block text-sm font-medium group-hover:text-violet-700">{item.rule_name}</span>
                        <span className="text-[12px] text-ink-subtle">
                          <span className="font-mono">{application.reference}</span> · {application.title} · opened {formatRelative(item.created_at)}
                        </span>
                      </span>
                      <StatusPill status={cat.pill}>{cat.label}</StatusPill>
                      <span className="text-[12px] text-ink-muted">{SEVERITY[item.severity]}</span>
                      <StatusPill status={st.pill}>{st.label}</StatusPill>
                      <span className="inline-flex w-36 items-center gap-1 truncate text-[12px] text-ink-muted">
                        <UserCheck className="size-3.5 shrink-0" aria-hidden />
                        {item.assignee ? item.assignee.full_name : 'Unassigned'}
                      </span>
                      <ArrowRight className="size-4 text-ink-subtle group-hover:text-violet-700" aria-hidden />
                    </Link>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </Card>
    </PageContainer>
  )
}
