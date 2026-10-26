import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ChevronDown, Fingerprint, ScrollText, Search } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { AuditEvent, AuditQuery } from '../../lib/types'
import { ActionLabel } from './ActionLabel'
import { controlClass } from '../../components/ui/controlClass'
import { Select } from '../../components/ui/Field'

const PAGE = 25
const FIELD = controlClass({ size: 'sm', full: false })

interface Filters {
  action: string
  outcome: '' | 'success' | 'failure'
  from: string
  to: string
  q: string
}

const EMPTY: Filters = { action: '', outcome: '', from: '', to: '', q: '' }

function EventRow({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false)
  const reduce = useReducedMotion()
  return (
    <li className="border-b border-line last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-3 text-left hover:bg-navy-50/60 md:grid-cols-[56px_auto_1fr_180px_auto]"
      >
        <span className="tabular hidden font-mono text-xs text-ink-subtle md:block">#{e.seq}</span>
        <ActionLabel action={e.action} outcome={e.outcome} />
        <span className="min-w-0 truncate text-[13px] text-ink-muted">
          {e.summary}
          {e.actor_email && <span className="text-ink-subtle"> · {e.actor_email}</span>}
        </span>
        <time dateTime={e.occurred_at} className="hidden text-xs text-ink-subtle md:block">
          {formatDateTime(e.occurred_at)}
        </time>
        <ChevronDown className={cn('size-4 text-ink-subtle transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reduce ? { opacity: 1 } : { height: 'auto', opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="grid gap-4 bg-navy-50/50 px-5 py-4 text-[12.5px] lg:grid-cols-2">
              <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5">
                <dt className="text-ink-subtle">Sequence</dt>
                <dd className="font-mono">{e.seq}</dd>
                <dt className="text-ink-subtle">Occurred</dt>
                <dd>{e.occurred_at}</dd>
                <dt className="text-ink-subtle">Entity</dt>
                <dd className="font-mono break-all">{e.entity_type ? `${e.entity_type}:${e.entity_id}` : '—'}</dd>
                <dt className="text-ink-subtle">Request ID</dt>
                <dd className="font-mono break-all">{e.request_id ?? '—'}</dd>
                <dt className="text-ink-subtle">Previous hash</dt>
                <dd className="font-mono break-all">{e.prev_hash}</dd>
                <dt className="text-ink-subtle">Entry hash</dt>
                <dd className="font-mono break-all">{e.entry_hash}</dd>
              </dl>
              <div>
                <p className="mb-1 text-ink-subtle">Recorded data</p>
                <pre className="max-h-64 overflow-auto rounded-lg border border-line bg-surface p-3 font-mono text-[11.5px] leading-5">
                  {JSON.stringify(e.data, null, 2)}
                </pre>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

export function AuditLog() {
  const qc = useQueryClient()
  const [offset, setOffset] = useState(0)
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [filters, setFilters] = useState<Filters>(EMPTY)
  const params: AuditQuery = {
    action: filters.action || undefined,
    outcome: filters.outcome || undefined,
    from: filters.from || undefined,
    to: filters.to || undefined,
    q: filters.q || undefined,
    limit: PAGE,
    offset,
  }
  const events = useQuery({
    queryKey: ['audit', 'events', params],
    queryFn: () => api.auditEvents(params),
    placeholderData: keepPreviousData,
  })
  const actions = useQuery({ queryKey: ['audit', 'actions'], queryFn: api.auditActions, staleTime: 60_000 })
  const groups = [...new Set((actions.data ?? []).map((a) => a.split('.')[0] + '.'))]
  const filtered = Object.values(filters).some(Boolean)
  const verify = useQuery({ queryKey: ['audit', 'verify'], queryFn: api.verifyAudit })

  const total = events.data?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + PAGE, total)

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
          <span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-violet-400" aria-hidden>
            <Fingerprint className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Hash-chain verification</p>
            {verify.isPending ? (
              <p className="text-[13px] text-ink-muted">Verifying…</p>
            ) : verify.isError ? (
              <ErrorState compact error={verify.error} onRetry={() => verify.refetch()} />
            ) : (
              <p className="text-[13px] text-ink-muted">
                {verify.data.checked.toLocaleString()} events re-hashed · head{' '}
                <span className="font-mono" title={verify.data.head_hash ?? ''}>
                  {shortHash(verify.data.head_hash, 16)}
                </span>
                {!verify.data.valid && (
                  <span className="text-fail">
                    {' '}
                    · broken at #{verify.data.first_invalid_seq}: {verify.data.reason}
                  </span>
                )}
              </p>
            )}
          </div>
          {verify.data && (
            <StatusPill status={verify.data.valid ? 'pass' : 'fail'}>{verify.data.valid ? 'Verified' : 'Tampering detected'}</StatusPill>
          )}
          <Button variant="secondary" size="sm" loading={verify.isFetching} onClick={() => qc.invalidateQueries({ queryKey: ['audit'] })}>
            Re-verify
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader
          icon={<ScrollText className="size-4" />}
          title="Audit history"
          description="Append-only. Entries cannot be edited or deleted through the application or the database."
        />
        <form
          aria-label="Audit filters"
          className="flex flex-wrap items-end gap-2 border-b border-line px-5 py-3"
          onSubmit={(ev) => {
            ev.preventDefault()
            setOffset(0)
            setFilters({ ...draft, q: draft.q.trim() })
          }}
        >
          <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
            Action
            <Select value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} size="sm" full={false}>
              <option value="">All actions</option>
              <optgroup label="Groups">
                {groups.map((g) => (
                  <option key={g} value={g}>
                    {g}* (all {g.slice(0, -1)} actions)
                  </option>
                ))}
              </optgroup>
              <optgroup label="Actions">
                {(actions.data ?? []).map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </optgroup>
            </Select>
          </label>
          <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
            Outcome
            <Select value={draft.outcome} onChange={(e) => setDraft({ ...draft, outcome: e.target.value as Filters['outcome'] })} size="sm" full={false}>
              <option value="">Any</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </Select>
          </label>
          <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
            From (UTC)
            <input type="date" value={draft.from} max={draft.to || undefined} onChange={(e) => setDraft({ ...draft, from: e.target.value })} className={FIELD} />
          </label>
          <label className="flex flex-col gap-0.5 text-[11.5px] text-ink-subtle">
            To (UTC)
            <input type="date" value={draft.to} min={draft.from || undefined} onChange={(e) => setDraft({ ...draft, to: e.target.value })} className={FIELD} />
          </label>
          <label className="relative flex min-w-48 flex-1 flex-col gap-0.5 text-[11.5px] text-ink-subtle sm:max-w-xs">
            Search
            <span className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
              <input
                value={draft.q}
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                placeholder="Summary or actor email"
                maxLength={100}
                className={controlClass({ size: 'sm' })}
                style={{ paddingLeft: 36 }}
              />
            </span>
          </label>
          <Button type="submit" size="sm" variant="secondary">
            Apply
          </Button>
          {filtered && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(EMPTY)
                setFilters(EMPTY)
                setOffset(0)
              }}
            >
              Clear
            </Button>
          )}
        </form>
        {events.isPending ? (
          <LoadingRows rows={6} label="Loading audit history" />
        ) : events.isError ? (
          <ErrorState error={events.error} onRetry={() => events.refetch()} />
        ) : events.data.items.length === 0 ? (
          <EmptyState icon={<ScrollText className="size-6" />} title={filtered ? 'No events match these filters' : 'No audit events yet'} />
        ) : (
          <ul className={cn('transition-opacity', events.isPlaceholderData && 'opacity-60')}>
            {events.data.items.map((e) => (
              <EventRow key={e.id} e={e} />
            ))}
          </ul>
        )}
        <div className="flex items-center justify-between border-t border-line px-5 py-3 text-[13px] text-ink-muted">
          <span className="tabular" aria-live="polite">
            {from}–{to} of {total.toLocaleString()}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))} aria-label="Previous page">
              <ChevronLeft className="size-4" aria-hidden />
            </Button>
            <Button size="sm" variant="ghost" disabled={to >= total} onClick={() => setOffset((o) => o + PAGE)} aria-label="Next page">
              <ChevronRight className="size-4" aria-hidden />
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
