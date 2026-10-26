import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  BookCheck,
  CircleHelp,
  FileSearch,
  FileText,
  GitCommitVertical,
  History,
  Network,
  PencilLine,
  Scale,
  ShieldAlert,
  UserCheck,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useBreadcrumbTrail } from '../../components/layout/crumbStore'
import { Button } from '../../components/ui/Button'
import { Notice, NoticeSlot } from '../../components/ui/Notice'
import { cn } from '../../components/ui/cn'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { formatDateTime, formatRelative, shortHash } from '../../lib/format'
import type { ReviewActionResult, ReviewDetail, ReviewField, SubmittableAction } from '../../lib/types'
import { AiExplanationPanel } from '../ai/AiExplanationPanel'
import { useAuth } from '../auth/AuthProvider'
import { RESULT_REASON, RULE_OUTCOME } from '../compliance/ruleMeta'
import { TraceView } from '../compliance/TraceView'
import { OUTCOME, SEVERITY } from '../evidence/evidenceMeta'
import { ActionDialog, AssignDialog, CorrectionDialog, Section } from './ReviewDialogs'
import { ACTION_LABEL, ACTIVE, CATEGORY, REVIEW_STATUS } from './reviewMeta'
import { SourcePage } from './SourcePage'

type DialogState =
  | { kind: 'action'; action: Exclude<SubmittableAction, 'assigned' | 'unassigned'> }
  | { kind: 'assign'; selfOnly?: boolean }
  | { kind: 'correct'; field: ReviewField }
  | null

export function ReviewItemPage() {
  const { itemId = '' } = useParams()
  const q = useQuery({ queryKey: ['review', itemId], queryFn: () => api.review(itemId) })
  useBreadcrumbTrail(q.data ? [{ label: `${q.data.application.reference} · ${q.data.item.rule_name}` }] : undefined)
  if (q.isPending) return <LoadingRows rows={8} label="Loading review item" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  return <ReviewView detail={q.data} refetching={q.isFetching} />
}

function defaultField(d: ReviewDetail): string | null {
  const failing = new Set(d.result.trace.flatMap((t) => t.observations.filter((o) => o.satisfied === false || o.quality === 'low').map((o) => o.field_id)))
  return (d.fields.find((f) => failing.has(f.field_id)) ?? d.fields.find((f) => f.in_trace) ?? d.fields[0])?.field_id ?? null
}

function ReviewView({ detail: d, refetching }: { detail: ReviewDetail; refetching: boolean }) {
  const { user } = useAuth()
  const item = d.item
  const [fieldId, setFieldId] = useState<string | null>(() => defaultField(d))
  const field = d.fields.find((f) => f.field_id === fieldId) ?? null
  const [dialog, setDialog] = useState<DialogState>(null)
  const [notice, setNotice] = useState<ReviewActionResult | null>(null)
  const active = ACTIVE.includes(item.status)
  const st = REVIEW_STATUS[item.status]
  const cat = CATEGORY[item.category]
  const p = d.permissions
  const onDone = (r: ReviewActionResult) => setNotice(r)
  useEffect(() => {
    document.title = `Review · ${item.rule_name} · VerifyFlow AI`
  }, [item.rule_name])

  return (
    <div className="pb-10">
      <header className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="mb-1 text-xs font-semibold tracking-[0.12em] text-violet-400 uppercase">
            Review · <Link to={`/applications/${d.application.id}`} className="hover:underline">{d.application.reference}</Link> · {d.application.title}
          </p>
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">{item.rule_name}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-ink-muted">
            <StatusPill status={st.pill}>{st.label}</StatusPill>
            <StatusPill status={cat.pill}>{cat.label}</StatusPill>
            <StatusPill status={RULE_OUTCOME[item.outcome].pill}>{RULE_OUTCOME[item.outcome].label}</StatusPill>
            <span>{SEVERITY[item.severity]} severity</span>
            <span className="inline-flex items-center gap-1">
              <UserCheck className="size-3.5" aria-hidden /> {item.assignee ? item.assignee.full_name : 'Unassigned'}
            </span>
            <span className="text-ink-subtle">priority {item.priority} · version {item.version}</span>
          </p>
        </div>
        {p.can_act ? (
          <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Review actions">
            {active && item.assignee?.id !== user?.id && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'assign', selfOnly: true })}>
                Take item
              </Button>
            )}
            {active && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'assign' })}>
                Assign…
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'action', action: 'commented' })}>
              Comment
            </Button>
            {item.status === 'open' && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'action', action: 'document_requested' })}>
                Request document
              </Button>
            )}
            {(item.status === 'open' || item.status === 'awaiting_document') && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'action', action: 'escalated' })}>
                Escalate
              </Button>
            )}
            {(item.status === 'awaiting_document' || (item.status === 'escalated' && p.oversight)) && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'action', action: 'resumed' })}>
                Resume
              </Button>
            )}
            {p.can_decide && (
              <>
                <Button size="sm" onClick={() => setDialog({ kind: 'action', action: 'confirmed' })}>
                  Confirm finding
                </Button>
                <Button size="sm" variant="danger" onClick={() => setDialog({ kind: 'action', action: 'dismissed' })}>
                  Dismiss…
                </Button>
              </>
            )}
            {(item.status === 'confirmed' || item.status === 'dismissed') && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'action', action: 'reopened' })}>
                Reopen…
              </Button>
            )}
          </div>
        ) : (
          <p role="note" className="rounded-lg bg-navy-50 px-3 py-2 text-[13px] text-ink-muted">
            Read-only: you can view this item but not act on it.
          </p>
        )}
      </header>

      {item.status === 'escalated' && !p.oversight && (
        <p role="note" className="mb-4 flex items-center gap-2 rounded-xl border border-fail/20 bg-fail-bg/50 px-4 py-2.5 text-[13px] text-fail">
          <ShieldAlert className="size-4" aria-hidden /> Escalated: only a compliance manager can decide or return this item.
        </p>
      )}
      {item.document_request && (
        <p role="note" className="mb-4 rounded-xl border border-info/20 bg-info-bg/60 px-4 py-2.5 text-[13px] text-info">
          Waiting for: <strong>{item.document_request.description}</strong> — requested by {item.document_request.requested_by} {formatRelative(item.document_request.requested_at)}
        </p>
      )}
      <NoticeSlot>
        {notice && <ResultNotice key={notice.action.id} r={notice} applicationId={d.application.id} onClose={() => setNotice(null)} />}
      </NoticeSlot>
      {refetching && <p className="sr-only" role="status">Refreshing…</p>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        {/* Left pane: the original document */}
        <div className="min-w-0 space-y-3 xl:sticky xl:top-4 xl:self-start">
          <Section title="Original document" icon={<FileText className="size-4" />}>
            {d.fields.length === 0 ? (
              <p className="text-[13px] text-ink-muted">This rule reads no extracted document fields (for example, it only uses evidence outcomes or application attributes).</p>
            ) : (
              <>
                <div role="listbox" aria-label="Fields this rule reads" className="mb-3 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                  {d.fields.map((f) => (
                    <button
                      key={f.field_id}
                      type="button"
                      role="option"
                      aria-selected={f.field_id === fieldId}
                      onClick={() => setFieldId(f.field_id)}
                      className={cn(
                        'max-w-full truncate rounded-lg border px-2.5 py-1 text-left text-[12px]',
                        f.field_id === fieldId ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-line hover:bg-navy-50',
                      )}
                    >
                      <span className="font-medium">{f.document_name}</span> · {f.label}: <span className="font-mono">{f.effective_value ?? '—'}</span>
                    </button>
                  ))}
                </div>
                {field && <SourcePage applicationId={d.application.id} field={field} />}
              </>
            )}
          </Section>
        </div>

        {/* Right pane: field, evidence, rule, history */}
        <div className="min-w-0 space-y-4">
          <Section title="Why this needs review" icon={<CircleHelp className="size-4" />}>
            <p className="mb-2 text-[13px]">
              <span className="font-medium">{RESULT_REASON[d.result.reason] ?? d.result.reason}</span>
              {d.result.message && <span className="text-ink-muted"> — {d.result.message}</span>}
            </p>
            {d.uncertainty.length ? (
              <ul className="space-y-1.5 text-[13px]">
                {d.uncertainty.map((u, i) => (
                  <li key={i} className="flex gap-2 rounded-lg bg-navy-50/70 px-3 py-1.5">
                    <span className="font-mono text-[11px] text-ink-subtle">{u.code}</span>
                    <span>{u.message}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-ink-subtle">No further detail was recorded.</p>
            )}
          </Section>

          <AiExplanationPanel subjectType="review_item" subjectId={item.id} />

          {field && (
            <Section
              title={`Extracted field · ${field.label}`}
              icon={<FileSearch className="size-4" />}
              action={
                p.can_correct &&
                field.is_current_extraction && (
                  <Button size="sm" variant="secondary" icon={<PencilLine className="size-3.5" aria-hidden />} onClick={() => setDialog({ kind: 'correct', field })}>
                    Correct value
                  </Button>
                )
              }
            >
              <FieldPanel f={field} applicationId={d.application.id} />
            </Section>
          )}

          <Section title="Applicable rule" icon={<Scale className="size-4" />} action={<Link to={`/compliance/rules/${item.rule_id}`} className="text-[12.5px] font-medium text-violet-700 hover:underline">Open rule</Link>}>
            {d.rule.summary ? (
              <div className="space-y-1.5 text-[13px] leading-6">
                <p>
                  <span className="font-medium text-ink-muted">Passes when: </span>
                  {d.rule.summary.condition}
                </p>
                <p className="text-[12.5px] text-ink-muted">{d.rule.summary.policies}</p>
                <p className="text-[12.5px] text-ink-muted">
                  v{d.rule.version_number} · source {d.rule.source_reference || '—'} · owner {d.rule.owner} · approved by {d.rule.approved_by ?? '—'}
                </p>
              </div>
            ) : (
              <p className="text-[13px] text-ink-subtle">The rule version record is unavailable.</p>
            )}
            <details className="group mt-3">
              <summary className="cursor-pointer text-[12.5px] font-medium text-violet-700">Evaluation trace (validation run of {formatDateTime(d.run.created_at)})</summary>
              <div className="mt-2">
                <TraceView trace={d.result.trace} applicationId={d.application.id} />
              </div>
            </details>
          </Section>

          <Section title="Comparison evidence" icon={<Network className="size-4" />} action={<Link to={`/applications/${d.application.id}/evidence`} className="text-[12.5px] font-medium text-violet-700 hover:underline">Evidence graph</Link>}>
            {d.evidence.findings.length === 0 ? (
              <p className="text-[13px] text-ink-subtle">{d.evidence.analysis_id ? 'No cross-document comparison covers these fields.' : 'No evidence analysis has been run for this application.'}</p>
            ) : (
              <ul className="space-y-2">
                {d.evidence.findings.map((f) => (
                  <li key={f.id} className="rounded-lg border border-line px-3 py-2 text-[13px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{f.group_label}</span>
                      <StatusPill status={OUTCOME[f.outcome].pill}>{OUTCOME[f.outcome].label}</StatusPill>
                      <span className="text-[12px] text-ink-subtle">{f.evidence_quality ? `${f.evidence_quality} quality evidence` : 'no evidence quality'}</span>
                    </div>
                    <p className="mt-1 text-[12.5px] text-ink-muted">{f.explanation}</p>
                    {f.relationships.slice(0, 4).map((r) => (
                      <p key={r.id} className="mt-1 text-[12px] text-ink-muted">
                        • {r.explanation}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="History" icon={<History className="size-4" />}>
            <HistoryTimeline d={d} />
          </Section>
        </div>
      </div>

      {dialog?.kind === 'action' && <ActionDialog detail={d} action={dialog.action} onClose={() => setDialog(null)} onDone={onDone} />}
      {dialog?.kind === 'assign' && <AssignDialog detail={d} selfOnly={dialog.selfOnly} onClose={() => setDialog(null)} onDone={onDone} />}
      {dialog?.kind === 'correct' && <CorrectionDialog detail={d} field={dialog.field} onClose={() => setDialog(null)} onDone={onDone} />}
    </div>
  )
}

function FieldPanel({ f, applicationId }: { f: ReviewField; applicationId: string }) {
  const changed = f.value_at_validation !== null && String(f.value_at_validation) !== f.effective_value
  return (
    <div className="space-y-3 text-[13px]">
      <dl className="grid grid-cols-[150px_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <dt className="text-ink-subtle">Document</dt>
        <dd>
          <Link to={`/applications/${applicationId}/documents/${f.document_id}?${new URLSearchParams({ page: String(f.page_number ?? 1), field: f.field_key })}`} className="text-violet-700 hover:underline">
            {f.document_name}
          </Link>
          {f.page_number ? ` · page ${f.page_number}` : ''}
        </dd>
        <dt className="text-ink-subtle">Original extraction</dt>
        <dd>
          <span className="font-mono">{f.raw_value ?? '—'}</span>
          {f.normalized_value && f.normalized_value !== f.raw_value && <span className="text-ink-muted"> → normalized <span className="font-mono">{f.normalized_value}</span></span>}
          <span className="block text-[12px] text-ink-subtle">
            {f.status} · {f.method ?? 'no method'}
            {f.confidence !== null ? ` · score ${f.confidence.toFixed(2)}` : ''}
            {f.quality_flags.length ? ` · flags: ${f.quality_flags.join(', ')}` : ''}
          </span>
        </dd>
        <dt className="text-ink-subtle">Used by validation</dt>
        <dd className="font-mono">{f.in_trace ? String(f.value_at_validation ?? '—') : 'not used (no usable value)'}</dd>
        <dt className="text-ink-subtle">Current value</dt>
        <dd>
          <span className="font-mono">{f.effective_value ?? '—'}</span>
          {changed && <span className="ml-2 rounded bg-review-bg px-1.5 py-0.5 text-[11px] font-semibold text-review uppercase">changed since validation</span>}
        </dd>
      </dl>
      {!f.is_current_extraction && <p className="text-[12px] text-review">This value comes from an older extraction run; corrections apply only to the current run.</p>}
      {f.corrections.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-[12px] font-semibold text-ink-muted uppercase">Corrections (newest last)</h3>
          <ol className="space-y-1.5">
            {f.corrections.map((c) => (
              <li key={c.id} className="rounded-lg bg-navy-50/70 px-3 py-1.5">
                <span className="font-mono">{c.based_on_value ?? '—'}</span> <ArrowRight className="inline size-3" aria-label="changed to" /> <span className="font-mono text-violet-700">{c.normalized_value}</span>
                <span className="block text-[12px] text-ink-muted">
                  “{c.reason}” — {c.actor.full_name}, {formatDateTime(c.created_at)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function HistoryTimeline({ d }: { d: ReviewDetail }) {
  return (
    <div className="space-y-4">
      <ol className="relative space-y-3 border-l border-line pl-5">
        {d.history.map((h) => {
          const before = h.data.before as Record<string, unknown> | string | undefined
          const after = h.data.after as Record<string, unknown> | string | undefined
          return (
            <li key={h.id} className={cn('relative text-[13px]', h.id === 'pending' && 'opacity-60')}>
              <GitCommitVertical className="absolute top-0.5 -left-[27px] size-4 rounded-full bg-surface text-violet-400" aria-hidden />
              <p>
                <span className="font-medium">{ACTION_LABEL[h.action]}</span>
                {h.from_status && h.to_status && h.from_status !== h.to_status && (
                  <span className="text-ink-muted">
                    {' '}
                    · {REVIEW_STATUS[h.from_status].label} → {REVIEW_STATUS[h.to_status].label}
                  </span>
                )}
                <span className="text-ink-subtle">
                  {' '}
                  — {h.actor.full_name} · <time dateTime={h.created_at}>{h.id === 'pending' ? 'sending…' : formatDateTime(h.created_at)}</time>
                </span>
              </p>
              {h.reason && <p className="mt-0.5 rounded-md bg-navy-50/70 px-2 py-1 whitespace-pre-wrap">{h.reason}</p>}
              {h.action === 'field_corrected' && (
                <p className="mt-0.5 text-[12.5px] text-ink-muted">
                  {String(h.data.field_label)}: <span className="font-mono">{String(before ?? '—')}</span> → <span className="font-mono text-violet-700">{String(after)}</span> (original extraction “{String((h.data.original_extraction as { raw_value?: string })?.raw_value ?? '—')}” kept)
                </p>
              )}
              {h.action === 'revalidated' && typeof before === 'object' && typeof after === 'object' && (
                <p className="mt-0.5 text-[12.5px] text-ink-muted">
                  Outcome {String(before.outcome ?? '—')} → {String(after.outcome)}
                  {h.data.decision_stands ? ' · identical evidence, the earlier decision stands' : h.data.evidence_changed ? ' · evidence changed' : ''}
                  {h.data.trigger === 'correction' ? ' · after a correction' : ''}
                </p>
              )}
              {(h.action === 'assigned' || h.action === 'unassigned') && (
                <p className="mt-0.5 text-[12.5px] text-ink-muted">
                  {String(h.data.from_assignee ?? 'Unassigned')} → {String(h.data.to_assignee ?? 'Unassigned')}
                </p>
              )}
              {h.action === 'document_requested' && <p className="mt-0.5 text-[12.5px] text-ink-muted">Requested: {String(h.data.document)}</p>}
            </li>
          )
        })}
      </ol>
      <div>
        <h3 className="mb-1.5 text-[12px] font-semibold text-ink-muted uppercase">This rule across validation runs</h3>
        <ol className="space-y-1">
          {d.rule_runs.map((r) => (
            <li key={r.run_id} className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <StatusPill status={RULE_OUTCOME[r.outcome].pill}>{RULE_OUTCOME[r.outcome].label}</StatusPill>
              <span>{formatDateTime(r.created_at)}</span>
              <span className="text-ink-subtle">
                v{r.version_number} · {r.trigger === 'correction' ? 'revalidation after correction' : 'manual run'} · run {shortHash(r.run_id, 8)}
                {r.previous_run_id ? ` (after ${shortHash(r.previous_run_id, 8)})` : ''}
              </span>
              {r.run_id === d.item.current_run_id && <span className="text-[11px] font-semibold text-violet-700 uppercase">current</span>}
            </li>
          ))}
        </ol>
      </div>
      {d.previous_items.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-[12px] font-semibold text-ink-muted uppercase">Earlier review items for this rule</h3>
          <ul className="space-y-1 text-[12.5px]">
            {d.previous_items.map((p) => (
              <li key={p.id}>
                <Link to={`/review/${p.id}`} className="text-violet-700 hover:underline">
                  {REVIEW_STATUS[p.status].label} · {RULE_OUTCOME[p.outcome].label}
                </Link>{' '}
                <span className="text-ink-subtle">opened {formatDateTime(p.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ResultNotice({ r, applicationId, onClose }: { r: ReviewActionResult; applicationId: string; onClose: () => void }) {
  const rv = r.revalidation
  return (
    <Notice
      tone="success"
      className="mb-4"
      onDismiss={onClose}
      title={`${ACTION_LABEL[r.action.action]} recorded${r.replayed ? ' (already processed — no duplicate was created)' : ''}.`}
    >
      {rv &&
        (rv.performed ? (
          <>
            Revalidated: <BookCheck className="inline size-3.5" aria-hidden />{' '}
            {Object.entries(rv.summary ?? {})
              .filter(([, n]) => n)
              .map(([k, n]) => `${n} ${k.replace('_', ' ')}`)
              .join(', ')}
            . Item is now {REVIEW_STATUS[r.item.status].label.toLowerCase()}.{' '}
            <Link to={`/applications/${applicationId}`} className="text-violet-700 underline">
              See validation runs
            </Link>
          </>
        ) : (
          rv.reason
        ))}
    </Notice>
  )
}
