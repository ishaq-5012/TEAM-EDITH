import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { TextField } from '../../components/ui/Field'
import { PageContainer } from '../../components/layout/PageContainer'
import { api, errorMessage } from '../../lib/api'
import { formatDateTime, passwordStrengthError, roleLabel } from '../../lib/format'
import { useAuth } from '../auth/AuthProvider'
import { SessionsCard } from './SessionsCard'

const schema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: z.string().superRefine((v, ctx) => {
      const err = passwordStrengthError(v)
      if (err) ctx.addIssue({ code: z.ZodIssueCode.custom, message: err })
    }),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' })
type Values = z.infer<typeof schema>

export function AccountPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [changed, setChanged] = useState(false)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const m = useMutation({
    mutationFn: (v: Values) => api.changePassword(v.current_password, v.new_password),
    // The server keeps this session and signs out every other one.
    onSuccess: () => {
      form.reset()
      setChanged(true)
      qc.invalidateQueries({ queryKey: ['my-sessions'] })
    },
    onError: (e) => {
      setChanged(false)
      setError(errorMessage(e))
    },
  })
  const { errors } = form.formState
  if (!user) return null

  return (
    <PageContainer eyebrow="Account" title={user.full_name} description={`${user.email} · ${roleLabel(user.role)}`} documentTitle="Account">
      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader title="Profile" description="Managed by your administrator." />
          <dl className="grid grid-cols-[140px_1fr] gap-y-3 p-5 text-[13px]">
            <dt className="text-ink-subtle">Email</dt>
            <dd>{user.email}</dd>
            <dt className="text-ink-subtle">Role</dt>
            <dd>{roleLabel(user.role)}</dd>
            <dt className="text-ink-subtle">Institution</dt>
            <dd>{user.institution ? `${user.institution.name} (${user.institution.code})` : '—'}</dd>
            <dt className="text-ink-subtle">Last sign-in</dt>
            <dd>{formatDateTime(user.last_login_at)}</dd>
            <dt className="text-ink-subtle">Permissions</dt>
            <dd className="flex flex-wrap gap-1">
              {user.permissions.map((p) => (
                <code key={p} className="rounded bg-navy-50 px-1.5 py-0.5 font-mono text-[11px] text-ink">
                  {p}
                </code>
              ))}
            </dd>
          </dl>
        </Card>
        <Card>
          <CardHeader icon={<KeyRound className="size-4" />} title="Change password" description="You stay signed in here; every other session is signed out." />
          <form
            noValidate
            className="space-y-4 p-5"
            onSubmit={form.handleSubmit((v) => {
              setError(null)
              m.mutate(v)
            })}
          >
            <TextField label="Current password" type="password" autoComplete="current-password" error={errors.current_password?.message} {...form.register('current_password')} />
            <TextField
              label="New password"
              type="password"
              autoComplete="new-password"
              hint="At least 12 characters, mixing three of: lowercase, uppercase, digits, symbols."
              error={errors.new_password?.message}
              {...form.register('new_password')}
            />
            <TextField label="Confirm new password" type="password" autoComplete="new-password" error={errors.confirm?.message} {...form.register('confirm')} />
            {error && (
              <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
                {error}
              </p>
            )}
            {changed && (
              <p role="status" className="rounded-lg bg-pass-bg px-3 py-2 text-[13px] text-pass">
                Password updated. Other sessions have been signed out.
              </p>
            )}
            <div className="flex justify-end">
              <Button type="submit" loading={m.isPending}>
                Update password
              </Button>
            </div>
          </form>
        </Card>
      </div>
      <SessionsCard />
    </PageContainer>
  )
}
