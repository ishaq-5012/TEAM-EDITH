import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BookCheck, FilePlus2, Hourglass, Info, PencilRuler, Scale } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { TextField } from '../../components/ui/Field'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { ApiError, api, errorMessage } from '../../lib/api'
import type { RuleListItem } from '../../lib/types'
import { SEVERITY } from '../evidence/evidenceMeta'
import { cleanDefinition, DEFAULT_DEFINITION, todayIso, VERSION_STATUS } from './ruleMeta'

export function Disclaimer({ text }: { text: string }) {
  return (
    <p role="note" className="flex items-start gap-2 rounded-xl border border-info/20 bg-info-bg/60 px-4 py-3 text-[13px] leading-5 text-ink-muted">
      <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
      <span>{text}</span>
    </p>
  )
}

export function CompliancePage() {
  const q = useQuery({ queryKey: ['rules'], queryFn: api.rules })
  const [creating, setCreating] = useState(false)
  const items = q.data?.items ?? []
  const stats = [
    { label: 'In force today', value: items.filter((r) => r.in_force_version !== null).length, icon: BookCheck },
    { label: 'Awaiting approval', value: items.filter((r) => r.pending_approval).length, icon: Hourglass },
    { label: 'Open drafts', value: items.filter((r) => r.has_draft).length, icon: PencilRuler },
  ]
  const categories = [...new Set(items.map((r) => r.category))]

  return (
    <PageContainer
      eyebrow="Compliance Studio"
      title="Compliance Studio"
      description="Declarative, versioned rules with effective dates, independent approval, test cases and read-only what-if simulation."
      actions={
        q.data?.can_manage && (
          <Button icon={<FilePlus2 className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
            New rule
          </Button>
        )
      }
    >
      {q.data && <Disclaimer text={q.data.disclaimer} />}
      {q.data && items.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          {stats.map((s) => (
            <Card key={s.label} className="flex items-center gap-3 px-4 py-3.5">
              <span className="grid size-9 place-items-center rounded-lg bg-violet-50 text-violet-700" aria-hidden>
                <s.icon className="size-4" />
              </span>
              <span>
                <span className="block text-xl font-semibold tabular-nums">{s.value}</span>
                <span className="text-[12.5px] text-ink-muted">{s.label}</span>
              </span>
            </Card>
          ))}
        </div>
      )}
      <Card>
        <CardHeader icon={<Scale className="size-4" />} title="Rule register" description="Each rule shows its owner, the version in force today and any version awaiting review." />
        {q.isPending ? (
          <LoadingRows rows={4} label="Loading rules" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Scale className="size-6" />}
            title="No rules defined"
            action={
              q.data.can_manage && (
                <Button size="sm" onClick={() => setCreating(true)}>
                  Create the first rule
                </Button>
              )
            }
          >
            No rules exist yet, so nothing is evaluated during validation runs.
          </EmptyState>
        ) : (
          categories.map((c) => (
            <section key={c} aria-label={`Category ${c}`}>
              <h3 className="border-b border-line bg-navy-50/60 px-5 py-1.5 text-[11.5px] font-semibold uppercase tracking-[0.1em] text-ink-subtle">{c}</h3>
              <ul className="divide-y divide-line">
                {items
                  .filter((r) => r.category === c)
                  .map((r) => (
                    <RuleRow key={r.id} r={r} />
                  ))}
              </ul>
            </section>
          ))
        )}
      </Card>
      {creating && <CreateRuleDialog onClose={() => setCreating(false)} />}
    </PageContainer>
  )
}

function RuleRow({ r }: { r: RuleListItem }) {
  const latest = VERSION_STATUS[r.latest_status]
  return (
    <li>
      <Link to={`/compliance/rules/${r.id}`} className="group flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-3.5 hover:bg-navy-50/50">
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium group-hover:text-violet-700">{r.name}</span>
          <span className="font-mono text-[11.5px] text-ink-subtle">{r.key}</span>
          <span className="text-[12px] text-ink-subtle"> · owner {r.owner.full_name}</span>
        </span>
        {r.in_force_version !== null ? (
          <StatusPill status="pass">
            v{r.in_force_version} in force{r.in_force_severity ? ` · ${SEVERITY[r.in_force_severity]}` : ''}
          </StatusPill>
        ) : (
          <StatusPill status="unknown">Not in force</StatusPill>
        )}
        {(r.latest_status !== 'published' || r.latest_version !== r.in_force_version) && (
          <StatusPill status={latest.pill}>
            v{r.latest_version} {latest.label.toLowerCase()}
          </StatusPill>
        )}
        <ArrowRight className="size-4 text-ink-subtle group-hover:text-violet-700" aria-hidden />
      </Link>
    </li>
  )
}

const schema = z
  .object({
    name: z.string().trim().min(3, 'At least 3 characters').max(200),
    key: z.string().regex(/^[a-z][a-z0-9_]{2,59}$/, 'Lowercase letters, digits and underscores; starts with a letter; 3–60 characters'),
    category: z.string().trim().min(2, 'At least 2 characters').max(60),
    description: z.string().max(5000),
    effective_from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Choose a date'),
    effective_to: z.string(),
    source_reference: z.string().trim().min(3, 'Cite the policy, regulation or internal standard this rule implements').max(2000),
  })
  .refine((v) => !v.effective_to || v.effective_to > v.effective_from, { path: ['effective_to'], message: 'Must be after the start date' })
type FormValues = z.infer<typeof schema>

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^[^a-z]+|_+$/g, '')
    .slice(0, 60)

function CreateRuleDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', key: '', category: '', description: '', effective_from: todayIso(), effective_to: '', source_reference: '' },
  })
  const [keyTouched, setKeyTouched] = useState(false)
  const create = useMutation({
    mutationFn: (v: FormValues) =>
      api.createRule({
        ...v,
        effective_to: v.effective_to || null,
        definition: cleanDefinition(DEFAULT_DEFINITION),
        change_summary: 'Initial version',
      }),
    onSuccess: (rule) => {
      qc.invalidateQueries({ queryKey: ['rules'] })
      navigate(`/compliance/rules/${rule.id}`)
    },
    onError: (e) => {
      if (e instanceof ApiError) for (const [f, m] of Object.entries(e.fieldErrors())) form.setError(f as keyof FormValues, { message: m })
    },
  })
  const e = form.formState.errors
  const name = form.register('name')
  return (
    <Dialog open onClose={onClose} title="New rule" description="Creates draft v1 with a placeholder condition that you then edit. Nothing is evaluated until a second person approves it." width="max-w-xl">
      <form className="space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <TextField
          label="Name"
          {...name}
          onChange={(ev) => {
            name.onChange(ev)
            if (!keyTouched) form.setValue('key', slug(ev.target.value))
          }}
          error={e.name?.message}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Key" {...form.register('key', { onChange: () => setKeyTouched(true) })} error={e.key?.message} hint="Stable identifier, cannot change later" />
          <TextField label="Category" placeholder="e.g. eligibility" {...form.register('category')} error={e.category?.message} />
        </div>
        <TextField
          label="Source reference"
          placeholder="e.g. Internal onboarding policy OP-4 §2.1"
          {...form.register('source_reference')}
          error={e.source_reference?.message}
          hint="Where this requirement comes from. Shown with every result."
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Effective from" type="date" {...form.register('effective_from')} error={e.effective_from?.message} hint="Inclusive" />
          <TextField label="Effective until (optional)" type="date" {...form.register('effective_to')} error={e.effective_to?.message} hint="Exclusive" />
        </div>
        <TextField label="Description (optional)" {...form.register('description')} error={e.description?.message} />
        {create.isError && !Object.keys((create.error as ApiError).fieldErrors?.() ?? {}).length && (
          <p role="alert" className="text-[13px] font-medium text-fail">
            {errorMessage(create.error)}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending}>
            Create draft
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
