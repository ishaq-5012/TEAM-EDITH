import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { TextField } from '../../components/ui/Field'
import { ApiError, api, errorMessage } from '../../lib/api'
import type { ApplicationDetail } from '../../lib/types'

/** Suggestions only; the type is free text so organisations can use their own vocabulary. */
const DEFAULT_TYPES = ['onboarding', 'loan', 'grant', 'licence', 'permit', 'claim']

const schema = z.object({
  title: z.string().trim().min(3, 'Title must be at least 3 characters').max(200),
  application_type: z.string().trim().min(2, 'Type must be at least 2 characters').max(60),
  applicant_name: z.string().trim().max(200),
  description: z.string().trim().max(5000),
})
type Values = z.infer<typeof schema>

export function ApplicationFormDialog({
  open,
  onClose,
  onSaved,
  knownTypes = [],
  existing,
}: {
  open: boolean
  onClose: () => void
  onSaved: (app: ApplicationDetail) => void
  knownTypes?: string[]
  existing?: ApplicationDetail
}) {
  const qc = useQueryClient()
  const listId = useId()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    values: {
      title: existing?.title ?? '',
      application_type: existing?.application_type ?? '',
      applicant_name: existing?.applicant_name ?? '',
      description: existing?.description ?? '',
    },
  })
  const m = useMutation({
    mutationFn: (v: Values) => {
      if (!existing) return api.createApplication({ ...v, applicant_name: v.applicant_name || null })
      // Send only changed fields so the audit trail records exactly what was edited.
      const changes: Partial<Values> = {}
      for (const key of Object.keys(v) as (keyof Values)[]) {
        if ((existing[key] ?? '') !== v[key]) changes[key] = v[key]
      }
      return api.updateApplication(existing.id, changes)
    },
    onSuccess: (app) => {
      qc.invalidateQueries({ queryKey: ['applications'] })
      qc.setQueryData(['application', app.id], app)
      form.reset()
      onSaved(app)
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        const fields = e.fieldErrors()
        let matched = false
        for (const [k, msg] of Object.entries(fields)) {
          if (k in schema.shape) {
            form.setError(k as keyof Values, { message: msg })
            matched = true
          }
        }
        if (matched) return
      }
      setFormError(errorMessage(e))
    },
  })
  const { errors } = form.formState
  const types = [...new Set([...knownTypes, ...DEFAULT_TYPES])].sort()

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={existing ? `Edit ${existing.reference}` : 'New application'}
      description={existing ? 'Changes are recorded in the audit trail with before and after values.' : 'You will be the owner. Add documents on the next screen.'}
    >
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit((v) => {
          setFormError(null)
          m.mutate(v)
        })}
      >
        <TextField label="Title" placeholder="e.g. Business account onboarding" error={errors.title?.message} {...form.register('title')} />
        <TextField
          label="Application type"
          list={listId}
          placeholder="e.g. onboarding"
          hint="Pick a suggestion or type your own."
          error={errors.application_type?.message}
          {...form.register('application_type')}
        />
        <datalist id={listId}>
          {types.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <TextField label="Applicant name (optional)" error={errors.applicant_name?.message} {...form.register('applicant_name')} />
        <div className="space-y-1.5">
          <label htmlFor={`${listId}-desc`} className="block text-[13px] font-medium text-ink">
            Description (optional)
          </label>
          <textarea
            id={`${listId}-desc`}
            rows={3}
            className="w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm focus:border-violet-500 focus:ring-4 focus:ring-violet-100 focus:outline-none"
            {...form.register('description')}
          />
          {errors.description && <p className="text-xs font-medium text-fail">{errors.description.message}</p>}
        </div>
        {formError && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
            {formError}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={m.isPending}>
            {existing ? 'Save changes' : 'Create application'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
