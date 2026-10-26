import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, BadgeCheck, CopyPlus, FileClock, Hash, Save, Send, ShieldAlert, ThumbsDown, UserRound } from 'lucide-react'
import { useEffect, useId, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { useBreadcrumbTrail } from '../../components/layout/crumbStore'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { controlClass } from '../../components/ui/controlClass'
import { TextField } from '../../components/ui/Field'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { cn } from '../../components/ui/cn'
import { ApiError, api, errorMessage } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { RuleDefinition, RuleDetail, RuleVersion } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'
import { ComparePanel } from './ComparePanel'
import { Disclaimer } from './CompliancePage'
import { CheckPanel, DefinitionEditor } from './DefinitionEditor'
import { useDefinitionCheck, useRuleCatalog } from './queries'
import { cleanDefinition, locText, VERSION_STATUS } from './ruleMeta'
import { SimulationPanel } from './SimulationPanel'
import { TestCasesPanel } from './TestCasesPanel'

type Tab = 'definition' | 'tests' | 'compare' | 'simulate'

export function RuleDetailPage() {
  const { ruleId = '' } = useParams()
  const q = useQuery({ queryKey: ['rule', ruleId], queryFn: () => api.rule(ruleId) })
  useBreadcrumbTrail(q.data ? [{ label: q.data.name }] : undefined)
  if (q.isPending) return <LoadingRows rows={6} label="Loading rule" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  return <RuleView rule={q.data} />
}

function RuleView({ rule }: { rule: RuleDetail }) {
  const { can, user } = useAuth()
  const qc = useQueryClient()
  const canManage = can('rules:manage')
  const canPublish = can('rules:publish')
  const [selectedId, setSelectedId] = useState(() => (rule.versions.find((v) => v.status === 'draft') ?? rule.versions.find((v) => v.in_force_today) ?? rule.versions[0]).id)
  const selected = rule.versions.find((v) => v.id === selectedId) ?? rule.versions[0]
  const [tab, setTab] = useState<Tab>('definition')
  const [unsaved, setUnsaved] = useState<RuleDefinition | null>(null)
  const hasDraft = rule.versions.some((v) => v.status === 'draft')
  const setRule = (r: RuleDetail) => qc.setQueryData(['rule', rule.id], r)

  const newVersion = useMutation({
    mutationFn: () => api.newRuleVersion(rule.id, selected.id),
    onSuccess: (r) => {
      setRule(r)
      qc.invalidateQueries({ queryKey: ['rules'] })
      const d = r.versions.find((v) => v.status === 'draft')
      if (d) setSelectedId(d.id)
      setTab('definition')
    },
  })

  const tabs: { key: Tab; label: string; hidden?: boolean }[] = [
    { key: 'definition', label: selected.status === 'draft' && canManage ? 'Editor' : 'Definition' },
    { key: 'tests', label: `Tests (${rule.test_cases.length})` },
    { key: 'compare', label: 'Compare versions' },
    { key: 'simulate', label: 'What-if simulation', hidden: !canManage },
  ]

  return (
    <PageContainer
      eyebrow={`Compliance Studio · ${rule.category}`}
      title={rule.name}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <code className="font-mono text-[12px]">{rule.key}</code>
          <span className="inline-flex items-center gap-1">
            <UserRound className="size-3.5" aria-hidden /> Owner {rule.owner.full_name}
          </span>
          {rule.description && <span>{rule.description}</span>}
        </span>
      }
      actions={
        canManage &&
        !hasDraft && (
          <Button variant="secondary" size="sm" icon={<CopyPlus className="size-3.5" aria-hidden />} onClick={() => newVersion.mutate()} loading={newVersion.isPending}>
            New version from v{selected.version_number}
          </Button>
        )
      }
    >
      <Disclaimer text={rule.disclaimer} />
      {newVersion.isError && (
        <p role="alert" className="text-[13px] font-medium text-fail">
          {errorMessage(newVersion.error)}
        </p>
      )}
      <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader icon={<FileClock className="size-4" />} title="Version history" description="Submitted versions are immutable." />
          <ol className="relative space-y-1 p-3" aria-label="Versions">
            {rule.versions.map((v) => {
              const meta = VERSION_STATUS[v.status]
              const active = v.id === selected.id
              return (
                <li key={v.id}>
                  <button
                    type="button"
                    aria-current={active || undefined}
                    onClick={() => {
                      setSelectedId(v.id)
                      setUnsaved(null)
                    }}
                    className={cn('w-full rounded-lg border px-3 py-2.5 text-left transition-colors', active ? 'border-violet-300 bg-violet-50/70' : 'border-transparent hover:bg-navy-50')}
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-semibold">v{v.version_number}</span>
                      <StatusPill status={meta.pill}>{meta.label}</StatusPill>
                      {v.in_force_today && <span className="ml-auto text-[11px] font-semibold uppercase tracking-wide text-pass">in force</span>}
                    </span>
                    <span className="mt-1 block text-[12px] text-ink-muted">
                      {v.effective_from} → {v.effective_to ?? 'open-ended'}
                    </span>
                    {v.change_summary && <span className="mt-0.5 block truncate text-[12px] text-ink-subtle">{v.change_summary}</span>}
                  </button>
                </li>
              )
            })}
          </ol>
        </Card>

        <div className="min-w-0 space-y-5">
          <VersionCard key={selected.id} rule={rule} version={selected} canManage={canManage} canPublish={canPublish} userId={user?.id} onRule={setRule} unsavedDirty={!!unsaved} />
          <Card>
            <div role="tablist" aria-label="Version tools" className="flex gap-1 overflow-x-auto border-b border-line px-3 pt-2">
              {tabs
                .filter((t) => !t.hidden)
                .map((t) => (
                  <button
                    key={t.key}
                    role="tab"
                    type="button"
                    aria-selected={tab === t.key}
                    onClick={() => setTab(t.key)}
                    className={cn(
                      '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium',
                      tab === t.key ? 'border-violet-600 text-violet-700' : 'border-transparent text-ink-muted hover:text-ink',
                    )}
                  >
                    {t.label}
                  </button>
                ))}
            </div>
            {/* The editor stays mounted while other tabs are open so unsaved edits survive tab switches. */}
            <div role="tabpanel" className="p-5" hidden={tab !== 'definition'}>
              <DefinitionTab key={selected.id} rule={rule} version={selected} editable={selected.status === 'draft' && canManage} onRule={setRule} onUnsaved={setUnsaved} />
            </div>
            <div role="tabpanel" className="p-5" hidden={tab === 'definition'}>
              {tab === 'definition' ? null : tab === 'tests' ? (
                <TestCasesPanel rule={rule} version={selected} canManage={canManage} unsaved={unsaved} />
              ) : tab === 'compare' ? (
                <ComparePanel key={selected.id} rule={rule} selectedId={selected.id} />
              ) : (
                <SimulationPanel key={selected.id} rule={rule} version={selected} unsaved={unsaved} />
              )}
            </div>
          </Card>
        </div>
      </div>
    </PageContainer>
  )
}

/** Version metadata, approval trail and the lifecycle actions allowed for the current user. */
function VersionCard({
  rule,
  version: v,
  canManage,
  canPublish,
  userId,
  onRule,
  unsavedDirty,
}: {
  rule: RuleDetail
  version: RuleVersion
  canManage: boolean
  canPublish: boolean
  userId?: string
  onRule: (r: RuleDetail) => void
  unsavedDirty: boolean
}) {
  const qc = useQueryClient()
  const [dialog, setDialog] = useState<null | 'approve' | 'reject' | 'retire'>(null)
  const submit = useMutation({
    mutationFn: () => api.submitVersion(rule.id, v.id),
    onSuccess: (r) => {
      onRule(r)
      qc.invalidateQueries({ queryKey: ['rules'] })
    },
  })
  const meta = VERSION_STATUS[v.status]
  const ownWork = !!userId && (v.created_by.id === userId || v.submitted_by?.id === userId)
  const failing = submit.error instanceof ApiError && submit.error.code === 'tests_failing' ? (submit.error.details as { name: string; expected: string; actual: string }[]) : null

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            Version {v.version_number} <StatusPill status={meta.pill}>{meta.label}</StatusPill>
            {v.in_force_today && <StatusPill status="pass">In force today</StatusPill>}
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">{meta.hint}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {v.status === 'draft' && canManage && (
            <Button size="sm" icon={<Send className="size-3.5" aria-hidden />} onClick={() => submit.mutate()} loading={submit.isPending} disabled={unsavedDirty} title={unsavedDirty ? 'Save your edits first' : undefined}>
              Submit for approval
            </Button>
          )}
          {v.status === 'pending_approval' && canPublish && !ownWork && (
            <>
              <Button size="sm" icon={<BadgeCheck className="size-3.5" aria-hidden />} onClick={() => setDialog('approve')}>
                Approve & publish
              </Button>
              <Button size="sm" variant="secondary" icon={<ThumbsDown className="size-3.5" aria-hidden />} onClick={() => setDialog('reject')}>
                Reject
              </Button>
            </>
          )}
          {v.status === 'published' && canPublish && (
            <Button size="sm" variant="secondary" icon={<Archive className="size-3.5" aria-hidden />} onClick={() => setDialog('retire')}>
              Retire
            </Button>
          )}
        </div>
      </div>
      {v.status === 'pending_approval' && canPublish && ownWork && (
        <p role="note" className="flex items-center gap-2 border-b border-line bg-review-bg/50 px-5 py-2.5 text-[13px] text-review">
          <ShieldAlert className="size-4" aria-hidden /> Four-eyes rule: you authored or submitted this version, so a different person with publish rights must review it.
        </p>
      )}
      {submit.isError && (
        <div role="alert" className="border-b border-line bg-fail-bg/50 px-5 py-2.5 text-[13px] text-fail">
          <p className="font-medium">{errorMessage(submit.error)}</p>
          {failing && (
            <ul className="mt-1 list-disc pl-5">
              {failing.map((f) => (
                <li key={f.name}>
                  {f.name}: expected {f.expected}, got {f.actual}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <dl className="grid gap-x-6 gap-y-3 p-5 text-[13px] sm:grid-cols-2">
        <Item label="Effective window">
          {v.effective_from} (inclusive) → {v.effective_to ? `${v.effective_to} (exclusive)` : 'open-ended'}
        </Item>
        <Item label="Source">{v.source_reference || <span className="text-review">Not documented yet — required before submission</span>}</Item>
        <Item label="Change summary">{v.change_summary || <span className="text-ink-subtle">—</span>}</Item>
        <Item label="Owner">{rule.owner.full_name}</Item>
        <Item label="Authored">
          {v.created_by.full_name} · {formatDateTime(v.created_at)}
        </Item>
        {v.submitted_by && (
          <Item label="Submitted">
            {v.submitted_by.full_name} · {formatDateTime(v.submitted_at)}
            {v.test_summary && ` · tests ${v.test_summary.passed}/${v.test_summary.total} passing`}
          </Item>
        )}
        {v.reviewed_by && (
          <Item label={v.status === 'rejected' ? 'Rejected' : 'Approved'}>
            {v.reviewed_by.full_name} · {formatDateTime(v.reviewed_at)}
            {v.review_note && <span className="block text-ink-muted">“{v.review_note}”</span>}
          </Item>
        )}
        {v.retired_by && (
          <Item label="Retired">
            {v.retired_by.full_name} · {formatDateTime(v.retired_at)}
            {v.retire_reason && <span className="block text-ink-muted">“{v.retire_reason}”</span>}
          </Item>
        )}
        <Item label="Content hash">
          <span className="inline-flex items-center gap-1 font-mono text-[12px]" title={v.content_hash}>
            <Hash className="size-3" aria-hidden />
            {shortHash(v.content_hash, 16)}
          </span>
        </Item>
      </dl>
      {dialog && <ReviewDialog kind={dialog} rule={rule} version={v} onClose={() => setDialog(null)} onRule={onRule} />}
    </Card>
  )
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[11.5px] font-medium uppercase tracking-wide text-ink-subtle">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}

const REVIEW_COPY = {
  approve: { title: 'Approve and publish', label: 'Review note', button: 'Approve & publish', hint: 'Record what you checked, e.g. the source clause and the test cases.' },
  reject: { title: 'Reject version', label: 'Reason', button: 'Reject', hint: 'Tell the author what needs to change.' },
  retire: { title: 'Retire version', label: 'Reason', button: 'Retire', hint: 'Retired versions stop being evaluated. Past validation runs keep the exact version they used.' },
} as const

function ReviewDialog({ kind, rule, version, onClose, onRule }: { kind: 'approve' | 'reject' | 'retire'; rule: RuleDetail; version: RuleVersion; onClose: () => void; onRule: (r: RuleDetail) => void }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const copy = REVIEW_COPY[kind]
  const m = useMutation({
    mutationFn: () =>
      kind === 'approve' ? api.approveVersion(rule.id, version.id, note) : kind === 'reject' ? api.rejectVersion(rule.id, version.id, note) : api.retireVersion(rule.id, version.id, note),
    onSuccess: (r) => {
      onRule(r)
      qc.invalidateQueries({ queryKey: ['rules'] })
      onClose()
    },
  })
  return (
    <Dialog open onClose={onClose} title={`${copy.title}: v${version.version_number}`} description={copy.hint}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          m.mutate()
        }}
      >
        {kind === 'approve' && (
          <div className="rounded-lg bg-navy-50/70 p-3 text-[13px] leading-6">
            <p>
              <span className="font-medium text-ink-muted">Passes when: </span>
              {version.summary.condition}
            </p>
            <p>
              <span className="font-medium text-ink-muted">Effective: </span>
              {version.effective_from} → {version.effective_to ?? 'open-ended'}
            </p>
            <p>
              <span className="font-medium text-ink-muted">Source: </span>
              {version.source_reference}
            </p>
          </div>
        )}
        <TextField label={copy.label} value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
        {m.isError && (
          <p role="alert" className="text-[13px] font-medium text-fail">
            {errorMessage(m.error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant={kind === 'approve' ? 'primary' : 'danger'} loading={m.isPending} disabled={note.trim().length < 3}>
            {copy.button}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/** Definition view; for drafts, the full editor with live schema check, save and window fields. */
function DefinitionTab({
  rule,
  version,
  editable,
  onRule,
  onUnsaved,
}: {
  rule: RuleDetail
  version: RuleVersion
  editable: boolean
  onRule: (r: RuleDetail) => void
  onUnsaved: (d: RuleDefinition | null) => void
}) {
  const catalog = useRuleCatalog()
  const qc = useQueryClient()
  const [definition, setDefinition] = useState<RuleDefinition>(version.definition)
  const [meta, setMeta] = useState({
    effective_from: version.effective_from,
    effective_to: version.effective_to ?? '',
    source_reference: version.source_reference,
    change_summary: version.change_summary,
  })
  const defDirty = JSON.stringify(cleanDefinition(definition)) !== JSON.stringify(cleanDefinition(version.definition))
  const metaDirty =
    meta.effective_from !== version.effective_from ||
    meta.effective_to !== (version.effective_to ?? '') ||
    meta.source_reference !== version.source_reference ||
    meta.change_summary !== version.change_summary
  const check = useDefinitionCheck(definition, editable)
  const ids = { src: useId(), sum: useId() }

  useEffect(() => {
    onUnsaved(editable && defDirty ? definition : null)
  }, [editable, defDirty, definition, onUnsaved])

  const save = useMutation({
    mutationFn: () =>
      api.updateDraft(rule.id, version.id, {
        ...(defDirty ? { definition: cleanDefinition(definition) } : {}),
        effective_from: meta.effective_from,
        effective_to: meta.effective_to || null,
        source_reference: meta.source_reference,
        change_summary: meta.change_summary,
      }),
    onSuccess: (r) => {
      onRule(r)
      qc.invalidateQueries({ queryKey: ['rules'] })
      const saved = r.versions.find((x) => x.id === version.id)
      if (saved) setDefinition(saved.definition)
    },
  })

  if (catalog.isPending) return <LoadingRows rows={3} label="Loading field catalog" />
  if (catalog.isError) return <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} compact />

  if (!editable) {
    return (
      <div className="space-y-4">
        <CheckPanel check={{ valid: true, errors: [], summary: version.summary }} pending={false} error={null} />
        <details className="group">
          <summary className="cursor-pointer text-[13px] font-medium text-violet-700">Show structured definition</summary>
          <div className="mt-3">
            <DefinitionEditor catalog={catalog.data} definition={version.definition} onChange={() => undefined} readOnly />
          </div>
        </details>
      </div>
    )
  }

  const saveError = save.error instanceof ApiError && Array.isArray(save.error.details) ? (save.error.details as { loc?: unknown; msg?: string }[]) : []
  return (
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-5">
        <DefinitionEditor catalog={catalog.data} definition={definition} onChange={setDefinition} />
        <section aria-label="Version details" className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
          <TextField label="Effective from (inclusive)" type="date" value={meta.effective_from} onChange={(e) => setMeta({ ...meta, effective_from: e.target.value })} />
          <TextField label="Effective until (exclusive, optional)" type="date" value={meta.effective_to} onChange={(e) => setMeta({ ...meta, effective_to: e.target.value })} />
          <div className="space-y-1.5 sm:col-span-2">
            <label htmlFor={ids.src} className="block text-[13px] font-medium">
              Source reference
            </label>
            <input id={ids.src} className={controlClass()} value={meta.source_reference} maxLength={2000} onChange={(e) => setMeta({ ...meta, source_reference: e.target.value })} placeholder="Policy, regulation or internal standard this version implements" />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <label htmlFor={ids.sum} className="block text-[13px] font-medium">
              Change summary
            </label>
            <input id={ids.sum} className={controlClass()} value={meta.change_summary} maxLength={2000} onChange={(e) => setMeta({ ...meta, change_summary: e.target.value })} placeholder="What changes in this version, and why" />
          </div>
        </section>
      </div>
      <aside className="space-y-3 2xl:sticky 2xl:top-4 2xl:self-start">
        <CheckPanel check={check.data} pending={check.isFetching} error={check.error} />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            icon={<Save className="size-4" aria-hidden />}
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!(defDirty || metaDirty) || (defDirty && check.data?.valid === false)}
            disabledReason={
              !(defDirty || metaDirty) ? 'There are no unsaved changes.' : 'The definition has validation errors (see the check above). Fix them to save.'
            }
          >
            Save draft
          </Button>
          {(defDirty || metaDirty) && <span className="text-[12.5px] text-review">Unsaved changes</span>}
          {save.isSuccess && !(defDirty || metaDirty) && <span className="text-[12.5px] text-pass">Saved</span>}
        </div>
        {save.isError && (
          <div role="alert" className="rounded-lg bg-fail-bg/60 px-3 py-2 text-[13px] text-fail">
            <p className="font-medium">{errorMessage(save.error)}</p>
            {saveError.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-[12.5px]">
                {saveError.map((d, i) => (
                  <li key={i}>
                    {locText(d.loc) && `${locText(d.loc)}: `}
                    {d.msg}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <p className="text-[12px] leading-5 text-ink-subtle">Drafts are never evaluated against applications. Submitting freezes this version; a different person with publish rights must approve it.</p>
      </aside>
    </div>
  )
}
