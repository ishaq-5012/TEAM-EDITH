import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, CheckCheck, Copy, FolderSearch, Network, Pencil, Undo2, UserPlus, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useParams } from 'react-router-dom'
import { z } from 'zod'
import { useBreadcrumbTrail } from '../../components/layout/crumbStore'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { SelectField, TextField } from '../../components/ui/Field'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { ApiError, api, errorMessage } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { ApplicationDetail, MemberRole, TransitionAction } from '../../lib/types'
import { ApplicationFormDialog } from './ApplicationFormDialog'
import { DocumentInventory } from './DocumentInventory'
import { StatusPill } from '../../components/ui/StatusPill'
import { ApplicationStatusPill } from './status'
import { APP_STATUS } from './statusMeta'
import { AiExplanationPanel } from '../ai/AiExplanationPanel'
import { UploadZone } from './UploadZone'
import { ValidationRunsCard } from './ValidationRunsCard'
import { useAuth } from '../auth/AuthProvider'

const ACTIONS: Record<TransitionAction, { label: string; icon: typeof CheckCheck; confirm: string; danger?: boolean }> = {
  complete: { label: 'Send to auditor', icon: CheckCheck, confirm: 'Confirm your review is complete and send this application for independent auditor approval.' },
  approve: { label: 'Verify & approve', icon: CheckCheck, confirm: 'Confirm the documents, evidence and rule results. This records your independent auditor approval.' },
  return: { label: 'Return to reviewer', icon: Undo2, confirm: 'Return this application to the reviewer with a reason for further work.' },
  reopen: { label: 'Reopen', icon: Undo2, confirm: 'Move this application back to needs review.' },
  archive: { label: 'Archive', icon: Archive, confirm: 'Archived applications are read-only. They can be restored later.', danger: true },
  restore: { label: 'Restore', icon: ArchiveRestore, confirm: 'Restore this application to the status it had before archiving.' },
}

const reasonSchema = z.object({ reason: z.string().trim().min(3, 'Give a reason (at least 3 characters)').max(500) })

function TransitionDialog({ app, action, onClose }: { app: ApplicationDetail; action: TransitionAction; onClose: () => void }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const form = useForm<{ reason: string }>({ resolver: zodResolver(reasonSchema) })
  const meta = ACTIONS[action]
  const m = useMutation({
    mutationFn: (reason: string) => api.transitionApplication(app.id, action, reason),
    onSuccess: (updated) => {
      qc.setQueryData(['application', app.id], updated)
      qc.invalidateQueries({ queryKey: ['applications'] })
      qc.invalidateQueries({ queryKey: ['documents', app.id] })
      onClose()
    },
    onError: (e) => setError(errorMessage(e)),
  })
  return (
    <Dialog open onClose={onClose} title={`${meta.label}: ${app.reference}`} description={meta.confirm}>
      <form noValidate className="space-y-4" onSubmit={form.handleSubmit((v) => m.mutate(v.reason))}>
        <TextField label="Reason" hint="Recorded in the audit trail." error={form.formState.errors.reason?.message} {...form.register('reason')} />
        {error && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant={meta.danger ? 'danger' : 'primary'} loading={m.isPending}>
            {meta.label}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

const memberSchema = z.object({ email: z.string().trim().email('Enter a valid email address'), role: z.enum(['contributor', 'viewer']) })

function MembersCard({ app }: { app: ApplicationDetail }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const form = useForm<{ email: string; role: MemberRole }>({ resolver: zodResolver(memberSchema), defaultValues: { role: 'contributor' } })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['application', app.id] })
    setError(null)
  }
  const add = useMutation({
    mutationFn: (v: { email: string; role: MemberRole }) => api.addMember(app.id, v.email, v.role),
    onSuccess: () => {
      form.reset({ email: '', role: 'contributor' })
      refresh()
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 404) form.setError('email', { message: e.message })
      else setError(errorMessage(e))
    },
  })
  const remove = useMutation({ mutationFn: (userId: string) => api.removeMember(app.id, userId), onSuccess: refresh, onError: (e) => setError(errorMessage(e)) })

  return (
    <Card>
      <CardHeader icon={<Users className="size-4" />} title="People" description="Contributors can edit and upload. Viewers are read-only." />
      <ul className="divide-y divide-line">
        <li className="flex items-center gap-3 px-5 py-3 text-[13px]">
          <span className="min-w-0 flex-1">
            <span className="block font-medium">{app.owner.full_name}</span>
            <span className="text-ink-subtle">{app.owner.email}</span>
          </span>
          <span className="rounded-full bg-navy-900 px-2 py-0.5 text-[11px] font-medium text-white">Owner</span>
        </li>
        {app.members.map((m) => (
          <li key={m.user.id} className="flex items-center gap-3 px-5 py-3 text-[13px]">
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{m.user.full_name}</span>
              <span className="text-ink-subtle">{m.user.email}</span>
            </span>
            <span className="rounded-full bg-navy-50 px-2 py-0.5 text-[11px] font-medium text-ink capitalize">{m.role}</span>
            {app.permissions.can_manage_members && (
              <Button size="sm" variant="ghost" aria-label={`Remove ${m.user.email}`} loading={remove.isPending && remove.variables === m.user.id} onClick={() => remove.mutate(m.user.id)}>
                <X className="size-4" aria-hidden />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {app.permissions.can_manage_members && (
        <form noValidate className="space-y-3 border-t border-line p-5" onSubmit={form.handleSubmit((v) => add.mutate(v))}>
          <div className="grid gap-3 sm:grid-cols-[1fr_150px]">
            <TextField label="Add by email" type="email" autoComplete="off" error={form.formState.errors.email?.message} {...form.register('email')} />
            <SelectField label="Role" {...form.register('role')}>
              <option value="contributor">Contributor</option>
              <option value="viewer">Viewer</option>
            </SelectField>
          </div>
          {error && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[12.5px] text-fail">
              {error}
            </p>
          )}
          <Button type="submit" size="sm" variant="secondary" loading={add.isPending} icon={<UserPlus className="size-3.5" aria-hidden />}>
            Add person
          </Button>
        </form>
      )}
    </Card>
  )
}

function WorkflowCard({ app }: { app: ApplicationDetail }) {
  const [copyState, setCopyState] = useState('')
  const approved = app.review_stage === 'approved'
  const audit = app.review_stage === 'audit'
  const steps = [
    { label: 'Institution submission', detail: `${app.document_count} documents received`, done: app.status !== 'draft' },
    { label: 'Reviewer', detail: app.reviewer_completed_at ? `Handed off ${formatDateTime(app.reviewer_completed_at)}` : 'Checks documents, evidence and rule results', done: !!app.reviewer_completed_at },
    { label: 'Compliance manager', detail: 'Only for a finding escalated by the reviewer', done: false, conditional: true },
    { label: 'Auditor', detail: app.audited_at ? `Decision ${formatDateTime(app.audited_at)}` : 'Independently approves or returns the case', done: approved },
  ]
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${app.reference} | ${app.title}\nInstitution: ${app.institution?.name ?? '—'}\nStatus: ${app.status}\nReview stage: ${app.review_stage}\nDocuments: ${app.document_count}\nAuditor decision: ${app.audit_note ?? 'Pending'}`)
      setCopyState('Case summary copied')
    } catch {
      setCopyState('Could not copy; use the case details on this page')
    }
  }
  return (
    <Card>
      <CardHeader title="Application journey" description="Follow the handoff from submission to independent auditor decision." />
      <ol className="space-y-3 px-5 py-4">
        {steps.map((step, index) => (
          <li key={step.label} className="flex gap-3">
            <span className={`grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold ${step.done ? 'bg-pass-bg text-pass' : step.conditional ? 'bg-navy-50 text-ink-muted' : (index === 1 && !audit && !approved) || (index === 3 && audit) ? 'bg-violet-100 text-violet-700' : 'bg-navy-50 text-ink-muted'}`}>{step.done ? '✓' : step.conditional ? '—' : index + 1}</span>
            <span className="min-w-0">
              <span className="block text-[13px] font-medium">{step.label}</span>
              <span className="block text-[12px] text-ink-muted">{step.detail}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2 border-t border-line px-5 py-3">
        <Link to={`/review?application_id=${app.id}`} className="text-[12.5px] font-medium text-violet-700 hover:underline">Review decisions</Link>
        <Link to={`/applications/${app.id}/evidence`} className="text-[12.5px] font-medium text-violet-700 hover:underline">Evidence graph</Link>
        <button type="button" onClick={copy} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-violet-700 hover:underline"><Copy className="size-3.5" aria-hidden /> Copy case summary</button>
      </div>
      {copyState && <p role="status" className="px-5 pb-3 text-[12px] text-ink-muted">{copyState}</p>}
    </Card>
  )
}

export function ApplicationDetailPage() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const q = useQuery({ queryKey: ['application', id], queryFn: () => api.application(id) })
  const [editing, setEditing] = useState(false)
  const [action, setAction] = useState<TransitionAction | null>(null)
  useBreadcrumbTrail(q.data ? [{ label: q.data.reference }] : undefined)

  if (q.isPending) {
    return (
      <div className="space-y-5" role="status" aria-label="Loading application">
        <div className="skeleton h-16 w-2/3" />
        <LoadingRows rows={4} />
      </div>
    )
  }
  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 404) {
      return (
        <EmptyState
          icon={<FolderSearch className="size-6" />}
          title="Application not found"
          action={
            <Link to="/applications" className="text-sm font-medium text-violet-700 hover:underline">
              Back to applications
            </Link>
          }
        >
          It doesn’t exist, or you don’t have access to it.
        </EmptyState>
      )
    }
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  }

  const app = q.data
  const p = app.permissions
  return (
    <PageContainer
      eyebrow={app.reference}
      title={app.title}
      documentTitle={`${app.reference} ${app.title}`}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <ApplicationStatusPill status={app.status} />
          {app.review_stage === 'audit' && <StatusPill status="info">Awaiting auditor</StatusPill>}
          {app.review_stage === 'approved' && <StatusPill status="pass">Document verification approved</StatusPill>}
          {app.status === 'completed' && app.review_stage !== 'approved' && <StatusPill status="review">Auditor approval not recorded</StatusPill>}
          {app.is_synthetic && <StatusPill status="info">Test record</StatusPill>}
          <span>{APP_STATUS[app.status].hint}</span>
        </span>
      }
      actions={
        <>
          <Link
            to={`/applications/${app.id}/evidence`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong bg-surface px-3 text-[13px] font-medium hover:border-violet-400 hover:text-violet-700"
          >
            <Network className="size-3.5" aria-hidden /> Evidence graph
          </Link>
          {p.can_edit && (
            <Button variant="secondary" size="sm" icon={<Pencil className="size-3.5" aria-hidden />} onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
          {p.allowed_actions.map((a) => {
            const meta = ACTIONS[a]
            return (
              <Button key={a} size="sm" variant={a === 'complete' ? 'primary' : 'secondary'} icon={<meta.icon className="size-3.5" aria-hidden />} onClick={() => setAction(a)}>
                {meta.label}
              </Button>
            )
          })}
        </>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          {p.can_upload ? (
            <Card>
              <CardHeader title="Add documents" description="Files are stored privately, hashed with SHA-256 and inspected automatically." />
              <div className="p-5">
                <UploadZone applicationId={app.id} />
              </div>
            </Card>
          ) : (
            app.status !== 'draft' && (
              <p role="status" className="rounded-xl border border-line bg-surface px-4 py-3 text-[13px] text-ink-muted">
                {app.status === 'archived'
                  ? 'This application is archived and read-only.'
                  : app.status === 'completed'
                    ? 'This application is completed. Reopen it to add documents.'
                    : 'You have read-only access to this application.'}
              </p>
            )
          )}
          <DocumentInventory applicationId={app.id} approved={app.review_stage === 'approved'} />
          {user?.role === 'reviewer' && app.status === 'needs_review' && app.review_stage === 'reviewer' && !p.allowed_actions.includes('complete') && (
            <p role="note" className="rounded-xl border border-review/30 bg-review-bg px-4 py-3 text-[13px] text-ink">
              Auditor handoff is waiting for review items or rule results. <Link to={`/review?application_id=${app.id}`} className="font-semibold text-violet-700 underline">Open this case’s findings</Link>; escalate an unresolved issue to the Compliance Manager. The manager’s decision must be recorded before you can send the case to the auditor.
            </p>
          )}
          <ValidationRunsCard applicationId={app.id} canEdit={p.can_edit} />
          <AiExplanationPanel subjectType="application" subjectId={app.id} title="Application summary" />
        </div>
        <div className="space-y-5">
          <WorkflowCard app={app} />
          <Card>
            <CardHeader title="Details" />
            <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-2.5 p-5 text-[13px]">
              <dt className="text-ink-subtle">Type</dt>
              <dd>{app.application_type}</dd>
              <dt className="text-ink-subtle">Institution</dt>
              <dd>{app.institution?.name ?? '—'}</dd>
              <dt className="text-ink-subtle">Applicant</dt>
              <dd>{app.applicant_name ?? '—'}</dd>
              <dt className="text-ink-subtle">Created</dt>
              <dd>{formatDateTime(app.created_at)}</dd>
              <dt className="text-ink-subtle">Updated</dt>
              <dd>{formatDateTime(app.updated_at)}</dd>
              {app.archived_at && (
                <>
                  <dt className="text-ink-subtle">Archived</dt>
                  <dd>{formatDateTime(app.archived_at)}</dd>
                </>
              )}
              {app.reviewer_completed_at && <><dt className="text-ink-subtle">Reviewer handoff</dt><dd>{formatDateTime(app.reviewer_completed_at)}</dd></>}
              {app.audited_at && <><dt className="text-ink-subtle">Auditor decision</dt><dd>{formatDateTime(app.audited_at)}{app.audit_note ? ` · ${app.audit_note}` : ''}</dd></>}
              {app.description && (
                <>
                  <dt className="text-ink-subtle">Description</dt>
                  <dd className="whitespace-pre-wrap">{app.description}</dd>
                </>
              )}
            </dl>
          </Card>
          <MembersCard app={app} />
        </div>
      </div>
      <ApplicationFormDialog open={editing} onClose={() => setEditing(false)} existing={app} onSaved={() => setEditing(false)} />
      {action && <TransitionDialog app={app} action={action} onClose={() => setAction(null)} />}
    </PageContainer>
  )
}
