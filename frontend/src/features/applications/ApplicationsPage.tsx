import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FileText, FolderKanban, Plus, Search, X } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { api } from '../../lib/api'
import { formatRelative } from '../../lib/format'
import type { ApplicationSort, ApplicationStatus } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'
import { ApplicationFormDialog } from './ApplicationFormDialog'
import { StatusPill } from '../../components/ui/StatusPill'
import { ApplicationStatusPill } from './status'
import { APP_STATUS, APP_STATUSES } from './statusMeta'
import { Select } from '../../components/ui/Field'

const PAGE = 20
const SORTS: { value: ApplicationSort; label: string }[] = [
  { value: 'updated_desc', label: 'Recently updated' },
  { value: 'created_desc', label: 'Newest first' },
  { value: 'reference_asc', label: 'Reference' },
  { value: 'title_asc', label: 'Title' },
]

/** Filter state lives in the URL so views are shareable and survive reloads. */
function useFilters() {
  const [params, setParams] = useSearchParams()
  const statuses = params.getAll('status').filter((s): s is ApplicationStatus => s in APP_STATUS)
  const filters = {
    q: params.get('q') ?? '',
    statuses,
    type: params.get('type') ?? '',
    scope: (params.get('scope') === 'mine' ? 'mine' : 'all') as 'all' | 'mine',
    sort: (SORTS.find((s) => s.value === params.get('sort'))?.value ?? 'updated_desc') as ApplicationSort,
    offset: Math.max(0, Number(params.get('offset')) || 0),
  }
  const update = (patch: Partial<typeof filters>, resetPage = true) => {
    const next = { ...filters, ...patch, ...(resetPage && !('offset' in patch) ? { offset: 0 } : {}) }
    const p = new URLSearchParams()
    if (next.q) p.set('q', next.q)
    next.statuses.forEach((s) => p.append('status', s))
    if (next.type) p.set('type', next.type)
    if (next.scope === 'mine') p.set('scope', 'mine')
    if (next.sort !== 'updated_desc') p.set('sort', next.sort)
    if (next.offset) p.set('offset', String(next.offset))
    setParams(p, { replace: true })
  }
  const active = !!(filters.q || filters.statuses.length || filters.type || filters.scope === 'mine')
  return { filters, update, active, clear: () => setParams(new URLSearchParams(), { replace: true }) }
}

export function ApplicationsPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const reduce = useReducedMotion()
  const { filters, update, active, clear } = useFilters()
  const [search, setSearch] = useState(filters.q)
  const [creating, setCreating] = useState(false)

  // Debounce typing into the URL (and therefore into the query).
  useEffect(() => {
    if (search === filters.q) return
    const id = window.setTimeout(() => update({ q: search.trim() }), 300)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const params = {
    q: filters.q || undefined,
    status: filters.statuses,
    application_type: filters.type || undefined,
    scope: filters.scope,
    sort: filters.sort,
    limit: PAGE,
    offset: filters.offset,
  }
  const q = useQuery({ queryKey: ['applications', params], queryFn: () => api.applications(params), placeholderData: keepPreviousData })
  const total = q.data?.total ?? 0
  const readsAll = can('applications:read_all')

  const toggleStatus = (s: ApplicationStatus) =>
    update({ statuses: filters.statuses.includes(s) ? filters.statuses.filter((x) => x !== s) : [...filters.statuses, s] })

  return (
    <PageContainer
      eyebrow="Application Workspace"
      title="Applications"
      description={readsAll ? 'Every application in the organisation.' : 'Applications you own or are a member of.'}
      actions={
        q.data?.can_create && (
          <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
            New application
          </Button>
        )
      }
    >
      <Card>
        <div className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center">
          <label className="relative flex-1">
            <span className="sr-only">Search applications</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search title, reference or applicant"
              maxLength={100}
              className="h-9 w-full rounded-lg border border-line-strong bg-surface pr-3 pl-9 text-[13px] focus:border-violet-500 focus:ring-4 focus:ring-violet-100 focus:outline-none"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Application type"
              value={filters.type}
              onChange={(e) => update({ type: e.target.value })}
              size="sm" full={false}
            >
              <option value="">All types</option>
              {q.data?.application_types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Sort by"
              value={filters.sort}
              onChange={(e) => update({ sort: e.target.value as ApplicationSort })}
              size="sm" full={false}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
            {readsAll && (
              <div role="radiogroup" aria-label="Scope" className="inline-flex rounded-lg border border-line-strong p-0.5">
                {(['all', 'mine'] as const).map((s) => (
                  <button
                    key={s}
                    role="radio"
                    aria-checked={filters.scope === s}
                    onClick={() => update({ scope: s })}
                    className={cn('h-7 rounded-md px-2.5 text-[12.5px] font-medium', filters.scope === s ? 'bg-navy-900 text-white' : 'text-ink-muted hover:text-ink')}
                  >
                    {s === 'all' ? 'All' : 'Mine'}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2.5" role="group" aria-label="Filter by status">
          {APP_STATUSES.map((s) => {
            const on = filters.statuses.includes(s)
            return (
              <button
                key={s}
                aria-pressed={on}
                onClick={() => toggleStatus(s)}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors',
                  on ? 'border-violet-500 bg-violet-50 text-violet-700' : 'border-line text-ink-muted hover:border-line-strong hover:text-ink',
                )}
              >
                {APP_STATUS[s].label}
              </button>
            )
          })}
          {active && (
            <button
              onClick={() => {
                setSearch('')
                clear()
              }}
              className="ml-1 inline-flex items-center gap-1 text-[12px] font-medium text-ink-muted hover:text-ink"
            >
              <X className="size-3.5" aria-hidden /> Clear filters
            </button>
          )}
        </div>

        {q.isPending ? (
          <LoadingRows rows={6} label="Loading applications" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          active ? (
            <EmptyState icon={<Search className="size-6" />} title="No applications match these filters">
              Try a different search or clear the filters.
            </EmptyState>
          ) : (
            <EmptyState
              icon={<FolderKanban className="size-6" />}
              title="No applications yet"
              action={q.data.can_create && <Button onClick={() => setCreating(true)}>Create the first application</Button>}
            >
              {q.data.can_create ? 'Create an application, then upload its documents.' : 'Applications shared with you will appear here.'}
            </EmptyState>
          )
        ) : (
          <div className={cn('table-scroll relative transition-opacity', q.isPlaceholderData && 'opacity-60')}>
            <table className="data-table min-w-[760px] text-[13px]">
              <thead>
                <tr>
                  <th scope="col">Application</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Documents</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((a, i) => (
                  <motion.tr
                    key={a.id}
                    initial={reduce ? false : { opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(i, 10) * 0.02 }}
                    className="group"
                  >
                    <td className="py-3">
                      <Link to={`/applications/${a.id}`} className="block rounded focus-visible:outline-2">
                        <span className="block font-medium text-ink group-hover:text-violet-700">
                          {a.title}
                          {a.is_synthetic && (
                            <span className="ml-2 align-middle">
                              <StatusPill status="info">Test record</StatusPill>
                            </span>
                          )}
                        </span>
                        <span className="font-mono text-[11.5px] text-ink-subtle">{a.reference}</span>
                        {a.applicant_name && <span className="text-ink-subtle"> · {a.applicant_name}</span>}
                      </Link>
                    </td>
                    <td className="py-3 text-ink-muted">{a.application_type}</td>
                    <td className="py-3">
                      {a.review_stage === 'audit' ? <StatusPill status="info">Awaiting auditor</StatusPill>
                        : a.review_stage === 'approved' ? <StatusPill status="pass">Approved</StatusPill>
                        : a.status === 'completed' ? <StatusPill status="review">Auditor approval not recorded</StatusPill>
                        : <ApplicationStatusPill status={a.status} />}
                    </td>
                    <td className="num py-3 text-ink-muted">
                      <span className="inline-flex items-center gap-1">
                        <FileText className="size-3.5" aria-hidden />
                        {a.document_count}
                      </span>
                    </td>
                    <td className="py-3 text-ink-muted">{a.owner.full_name}</td>
                    <td className="py-3 text-ink-muted" title={a.updated_at}>
                      {formatRelative(a.updated_at)}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {q.data && total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3 text-[13px] text-ink-muted">
            <span className="tabular" aria-live="polite">
              {filters.offset + 1}–{Math.min(filters.offset + PAGE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" disabled={filters.offset === 0} onClick={() => update({ offset: Math.max(0, filters.offset - PAGE) }, false)} aria-label="Previous page">
                <ChevronLeft className="size-4" aria-hidden />
              </Button>
              <Button size="sm" variant="ghost" disabled={filters.offset + PAGE >= total} onClick={() => update({ offset: filters.offset + PAGE }, false)} aria-label="Next page">
                <ChevronRight className="size-4" aria-hidden />
              </Button>
            </div>
          </div>
        )}
      </Card>
      <ApplicationFormDialog
        open={creating}
        onClose={() => setCreating(false)}
        knownTypes={q.data?.application_types}
        onSaved={(app) => {
          setCreating(false)
          navigate(`/applications/${app.id}`)
        }}
      />
    </PageContainer>
  )
}
