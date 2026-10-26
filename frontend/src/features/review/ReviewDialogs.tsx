import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, RotateCw } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { ApiError, api, errorMessage } from '../../lib/api'
import type { ReviewActionResult, ReviewDetail, ReviewField, SubmittableAction } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'
import { ACTION_FORM, newRequestId } from './reviewMeta'
import { controlClass } from '../../components/ui/controlClass'
import { Select } from '../../components/ui/Field'

const area = 'block min-h-24 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-violet-500 focus:outline-none focus:ring-4 focus:ring-violet-100'
const input = controlClass()

/**
 * Shared submit behaviour for review dialogs:
 * - one request id per dialog, reused on retry, so a resubmission after a network error is not applied twice
 * - a stale version (someone else acted) keeps the dialog and the typed text, and offers to load the latest state
 */
function useSubmit<T>(itemId: string, fn: (requestId: string) => Promise<ReviewActionResult>, onDone: (r: ReviewActionResult) => void, optimistic?: T) {
  const qc = useQueryClient()
  const [requestId] = useState(newRequestId)
  return useMutation({
    mutationFn: () => fn(requestId),
    onMutate: optimistic as never,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['review', itemId] })
      qc.invalidateQueries({ queryKey: ['reviews'] })
      if (r.revalidation?.performed) qc.invalidateQueries({ queryKey: ['validation-runs'] })
      onDone(r)
    },
  })
}

function StaleNotice({ error, itemId }: { error: unknown; itemId: string }) {
  const qc = useQueryClient()
  if (!(error instanceof ApiError)) return null
  if (error.code !== 'stale_item') {
    return (
      <p role="alert" className="rounded-lg bg-fail-bg/70 px-3 py-2 text-[13px] font-medium text-fail">
        {errorMessage(error)}
      </p>
    )
  }
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-review/30 bg-review-bg/70 px-3 py-2 text-[13px] text-review">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Someone else updated this item.</p>
        <p className="text-ink-muted">Load the latest state, check what changed, then submit again. Your text is kept.</p>
      </div>
      <Button size="sm" variant="secondary" icon={<RotateCw className="size-3.5" aria-hidden />} onClick={() => qc.invalidateQueries({ queryKey: ['review', itemId] })}>
        Load latest
      </Button>
    </div>
  )
}

function Footer({ onClose, pending, label, danger, disabled }: { onClose: () => void; pending: boolean; label: string; danger?: boolean; disabled?: boolean }) {
  return (
    <div className="flex justify-end gap-2 pt-1">
      <Button variant="ghost" onClick={onClose}>
        Cancel
      </Button>
      <Button type="submit" variant={danger ? 'danger' : 'primary'} loading={pending} disabled={disabled}>
        {label}
      </Button>
    </div>
  )
}

export function ActionDialog({
  detail,
  action,
  onClose,
  onDone,
}: {
  detail: ReviewDetail
  action: Exclude<SubmittableAction, 'assigned' | 'unassigned'>
  onClose: () => void
  onDone: (r: ReviewActionResult) => void
}) {
  const form = ACTION_FORM[action]
  const qc = useQueryClient()
  const { user } = useAuth()
  const [reason, setReason] = useState('')
  const [doc, setDoc] = useState('')
  const ids = { reason: useId(), doc: useId(), hint: useId() }
  const item = detail.item
  // Comments are the only optimistic update: they never change status, and a failure simply removes the draft entry.
  const optimistic =
    action === 'commented'
      ? () => {
          const key = ['review', item.id]
          const prev = qc.getQueryData<ReviewDetail>(key)
          if (prev && user)
            qc.setQueryData<ReviewDetail>(key, {
              ...prev,
              history: [
                ...prev.history,
                { id: 'pending', sequence: prev.history.length + 1, action: 'commented', actor: user, from_status: item.status, to_status: item.status, reason: reason.trim(), data: { pending: true }, request_id: null, created_at: new Date().toISOString() },
              ],
            })
          return { prev }
        }
      : undefined
  const m = useSubmit(
    item.id,
    (request_id) =>
      api.reviewAction(item.id, {
        action,
        expected_version: (qc.getQueryData<ReviewDetail>(['review', item.id])?.item.version ?? item.version),
        request_id,
        reason: reason.trim() || undefined,
        document_description: action === 'document_requested' ? doc.trim() : undefined,
      }),
    (r) => {
      onDone(r)
      onClose()
    },
    optimistic,
  )
  const tooShort = reason.trim().length < form.minReason || (action === 'document_requested' && doc.trim().length < 5)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!tooShort) m.mutate(undefined, { onError: () => action === 'commented' && qc.invalidateQueries({ queryKey: ['review', item.id] }) })
  }
  return (
    <Dialog open onClose={onClose} title={form.title} description={form.hint}>
      <form className="space-y-4" onSubmit={submit} noValidate>
        {action === 'document_requested' && (
          <div className="space-y-1.5">
            <label htmlFor={ids.doc} className="block text-[13px] font-medium">
              Document needed
            </label>
            <input id={ids.doc} className={input} value={doc} maxLength={500} onChange={(e) => setDoc(e.target.value)} placeholder="e.g. Certified copy of birth certificate" />
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor={ids.reason} className="block text-[13px] font-medium">
            {form.reasonLabel}
          </label>
          <textarea id={ids.reason} aria-describedby={ids.hint} className={area} value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
          <p id={ids.hint} className="text-[12px] text-ink-subtle">
            {form.minReason > 1 && reason.trim().length < form.minReason
              ? `At least ${form.minReason} characters (${reason.trim().length} so far).`
              : 'Recorded permanently with your name and the time.'}
          </p>
        </div>
        <StaleNotice error={m.error} itemId={item.id} />
        <Footer onClose={onClose} pending={m.isPending} label={form.button} danger={form.danger} disabled={tooShort} />
      </form>
    </Dialog>
  )
}

export function AssignDialog({ detail, onClose, onDone, selfOnly }: { detail: ReviewDetail; onClose: () => void; onDone: (r: ReviewActionResult) => void; selfOnly?: boolean }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const item = detail.item
  const people = useQuery({ queryKey: ['review-assignees', item.id], queryFn: () => api.reviewAssignees(item.id) })
  const [assignee, setAssignee] = useState(selfOnly && user ? user.id : (item.assignee?.id ?? ''))
  const [reason, setReason] = useState('')
  const ids = { who: useId(), reason: useId() }
  const takingFromOther = !!item.assignee && item.assignee.id !== user?.id
  const m = useSubmit(
    item.id,
    (request_id) =>
      api.reviewAction(item.id, {
        action: assignee ? 'assigned' : 'unassigned',
        assignee_id: assignee || undefined,
        expected_version: qc.getQueryData<ReviewDetail>(['review', item.id])?.item.version ?? item.version,
        request_id,
        reason: reason.trim() || undefined,
      }),
    (r) => {
      onDone(r)
      onClose()
    },
  )
  const disabled = (assignee || null) === (item.assignee?.id ?? null) || (takingFromOther && reason.trim().length < 5)
  return (
    <Dialog
      open
      onClose={onClose}
      title={selfOnly ? 'Take this item' : 'Assign'}
      description={takingFromOther ? `Currently assigned to ${item.assignee!.full_name}. Taking it over needs a reason.` : 'Only people who can resolve reviews on this application are listed.'}
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!disabled) m.mutate()
        }}
      >
        <div className="space-y-1.5">
          <label htmlFor={ids.who} className="block text-[13px] font-medium">
            Assignee
          </label>
          {people.isError ? (
            <p className="text-[13px] text-fail">{errorMessage(people.error)}</p>
          ) : (
            <Select id={ids.who} value={assignee} onChange={(e) => setAssignee(e.target.value)} disabled={people.isPending}>
              <option value="">Unassigned</option>
              {people.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.email}){u.id === user?.id ? ' — you' : ''}
                </option>
              ))}
            </Select>
          )}
        </div>
        {takingFromOther && (
          <div className="space-y-1.5">
            <label htmlFor={ids.reason} className="block text-[13px] font-medium">
              Reason for reassignment
            </label>
            <textarea id={ids.reason} className={area} value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
        <StaleNotice error={m.error} itemId={item.id} />
        <Footer onClose={onClose} pending={m.isPending} label="Save assignment" disabled={disabled} />
      </form>
    </Dialog>
  )
}

export function CorrectionDialog({ detail, field, onClose, onDone }: { detail: ReviewDetail; field: ReviewField; onClose: () => void; onDone: (r: ReviewActionResult) => void }) {
  const qc = useQueryClient()
  const item = detail.item
  const [value, setValue] = useState(field.effective_value ?? '')
  const [reason, setReason] = useState('')
  const ids = { value: useId(), reason: useId() }
  const m = useSubmit(
    item.id,
    (request_id) =>
      api.reviewCorrection(item.id, {
        expected_version: qc.getQueryData<ReviewDetail>(['review', item.id])?.item.version ?? item.version,
        request_id,
        document_id: field.document_id,
        field_id: field.field_id,
        value: value.trim(),
        reason: reason.trim(),
      }),
    (r) => {
      onDone(r)
      onClose()
    },
  )
  const disabled = !value.trim() || value.trim() === field.effective_value || reason.trim().length < 5
  return (
    <Dialog open onClose={onClose} title={`Correct ${field.label}`} description={`${field.document_name}. The original extraction is never changed; your correction is added on top, and validation re-runs if a rule in force reads this field.`} width="max-w-xl">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!disabled) m.mutate()
        }}
      >
        <dl className="grid grid-cols-[150px_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-lg bg-navy-50/70 p-3 text-[13px]">
          <dt className="text-ink-subtle">Original extraction</dt>
          <dd className="font-mono">{field.raw_value ?? '—'}</dd>
          <dt className="text-ink-subtle">Current value</dt>
          <dd className="font-mono">{field.effective_value ?? '—'}</dd>
          <dt className="text-ink-subtle">New value</dt>
          <dd className="font-mono text-violet-700">{value.trim() || '—'}</dd>
        </dl>
        <div className="space-y-1.5">
          <label htmlFor={ids.value} className="block text-[13px] font-medium">
            Corrected value
          </label>
          <input id={ids.value} className={input} value={value} maxLength={500} onChange={(e) => setValue(e.target.value)} />
          {field.field_type === 'date' && <p className="text-[12px] text-ink-subtle">Use an unambiguous date such as 1990-03-03.</p>}
        </div>
        <div className="space-y-1.5">
          <label htmlFor={ids.reason} className="block text-[13px] font-medium">
            Reason (required)
          </label>
          <textarea id={ids.reason} className={area} value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} placeholder="What does the source document show, and why was the extraction wrong?" />
        </div>
        <StaleNotice error={m.error} itemId={item.id} />
        <Footer onClose={onClose} pending={m.isPending} label="Save correction" disabled={disabled} />
      </form>
    </Dialog>
  )
}

export function Section({ title, icon, children, action }: { title: string; icon: ReactNode; children: ReactNode; action?: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 id={id} className="flex items-center gap-2 text-[14px] font-semibold">
          <span className="text-violet-400" aria-hidden>
            {icon}
          </span>
          {title}
        </h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}
