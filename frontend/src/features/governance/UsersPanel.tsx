import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, LogOut, Pencil, UserPlus, Users } from 'lucide-react'
import { useState } from 'react'
import { useForm, type FieldValues, type Path, type UseFormSetError } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { SelectField, TextField } from '../../components/ui/Field'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { ApiError, api, errorMessage } from '../../lib/api'
import { formatRelative, passwordStrengthError, roleLabel } from '../../lib/format'
import { ROLES, type Role, type User } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'

const roleValues = ROLES.map((r) => r.value) as [Role, ...Role[]]
const strongPassword = z.string().superRefine((v, ctx) => {
  const err = passwordStrengthError(v)
  if (err) ctx.addIssue({ code: z.ZodIssueCode.custom, message: err })
})
const reason = z.string().trim().min(3, 'Give a reason (at least 3 characters)').max(500)

/** Map backend 422 field errors onto form fields; returns the leftover message if none matched. */
function applyServerErrors<T extends FieldValues>(err: unknown, setError: UseFormSetError<T>, fields: string[]): string | null {
  if (err instanceof ApiError) {
    const fe = err.fieldErrors()
    let matched = false
    for (const [k, msg] of Object.entries(fe)) {
      if (fields.includes(k)) {
        setError(k as Path<T>, { message: msg })
        matched = true
      }
    }
    if (matched) return null
  }
  return errorMessage(err)
}

const roleHint = (r: Role) => ROLES.find((x) => x.value === r)?.description

const createSchema = z.object({
  full_name: z.string().trim().min(1, 'Name is required').max(200),
  email: z.string().trim().email('Enter a valid email address'),
  role: z.enum(roleValues),
  password: strongPassword,
})
type CreateValues = z.infer<typeof createSchema>

function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { role: 'reviewer' } })
  const m = useMutation({
    mutationFn: api.createUser,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
      form.reset()
      onClose()
    },
    onError: (e) => setFormError(applyServerErrors(e, form.setError, Object.keys(createSchema.shape))),
  })
  const { errors } = form.formState
  return (
    <Dialog open={open} onClose={onClose} title="Create user" description="The user signs in with this temporary password and should change it.">
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit((v) => {
          setFormError(null)
          m.mutate(v)
        })}
      >
        <TextField label="Full name" autoComplete="off" error={errors.full_name?.message} {...form.register('full_name')} />
        <TextField label="Email" type="email" autoComplete="off" error={errors.email?.message} {...form.register('email')} />
        <SelectField label="Role" error={errors.role?.message} hint={roleHint(form.watch('role'))} {...form.register('role')}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Temporary password"
          type="password"
          autoComplete="new-password"
          hint="At least 12 characters, mixing three of: lowercase, uppercase, digits, symbols."
          error={errors.password?.message}
          {...form.register('password')}
        />
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
            Create user
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

const editSchema = z.object({
  full_name: z.string().trim().min(1, 'Name is required').max(200),
  role: z.enum(roleValues),
  is_active: z.enum(['active', 'inactive']),
  reason,
})
type EditValues = z.infer<typeof editSchema>

function EditUserDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { full_name: user.full_name, role: user.role, is_active: user.is_active ? 'active' : 'inactive', reason: '' },
  })
  const m = useMutation({
    mutationFn: (v: EditValues) => {
      const active = v.is_active === 'active'
      return api.updateUser(user.id, {
        full_name: v.full_name !== user.full_name ? v.full_name : undefined,
        role: v.role !== user.role ? v.role : undefined,
        is_active: active !== user.is_active ? active : undefined,
        reason: v.reason,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
      onClose()
    },
    onError: (e) => setFormError(applyServerErrors(e, form.setError, ['full_name', 'role', 'reason'])),
  })
  const { errors } = form.formState
  return (
    <Dialog open onClose={onClose} title={`Edit ${user.email}`} description="Role or status changes immediately revoke the user’s active sessions.">
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit((v) => {
          setFormError(null)
          m.mutate(v)
        })}
      >
        <TextField label="Full name" error={errors.full_name?.message} {...form.register('full_name')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField label="Role" {...form.register('role')}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </SelectField>
          <SelectField label="Status" {...form.register('is_active')}>
            <option value="active">Active</option>
            <option value="inactive">Deactivated</option>
          </SelectField>
        </div>
        <TextField label="Reason for change" hint="Recorded in the audit history." error={errors.reason?.message} {...form.register('reason')} />
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
            Save changes
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

const resetSchema = z.object({ new_password: strongPassword, reason })
type ResetValues = z.infer<typeof resetSchema>

function ResetPasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ResetValues>({ resolver: zodResolver(resetSchema) })
  const m = useMutation({
    mutationFn: (v: ResetValues) => api.resetPassword(user.id, v.new_password, v.reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['audit'] })
      onClose()
    },
    onError: (e) => setFormError(applyServerErrors(e, form.setError, ['new_password', 'reason'])),
  })
  const { errors } = form.formState
  return (
    <Dialog open onClose={onClose} title={`Reset password for ${user.email}`} description="Signs the user out everywhere and clears any lockout.">
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit((v) => {
          setFormError(null)
          m.mutate(v)
        })}
      >
        <TextField label="New temporary password" type="password" autoComplete="new-password" error={errors.new_password?.message} {...form.register('new_password')} />
        <TextField label="Reason" error={errors.reason?.message} {...form.register('reason')} />
        {formError && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
            {formError}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" loading={m.isPending}>
            Reset password
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

const revokeSchema = z.object({ reason })
type RevokeValues = z.infer<typeof revokeSchema>

function RevokeSessionsDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const qc = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const [result, setResult] = useState<number | null>(null)
  const sessions = useQuery({ queryKey: ['user-sessions', user.id], queryFn: () => api.userSessions(user.id) })
  const form = useForm<RevokeValues>({ resolver: zodResolver(revokeSchema) })
  const m = useMutation({
    mutationFn: (v: RevokeValues) => api.revokeUserSessions(user.id, v.reason),
    onSuccess: (r) => {
      setResult(r.revoked)
      qc.invalidateQueries({ queryKey: ['user-sessions', user.id] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
    onError: (e) => setFormError(applyServerErrors(e, form.setError, ['reason'])),
  })
  return (
    <Dialog open onClose={onClose} title={`Sign ${user.email} out everywhere`} description="Ends every active session for this user immediately.">
      {result !== null ? (
        <div className="space-y-4">
          <p role="status" className="rounded-lg bg-pass-bg px-3 py-2 text-[13px] text-pass">
            {result === 0 ? 'The user had no active sessions.' : `Ended ${result} session(s).`}
          </p>
          <div className="flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <form
          noValidate
          className="space-y-4"
          onSubmit={form.handleSubmit((v) => {
            setFormError(null)
            m.mutate(v)
          })}
        >
          <p className="text-[13px] text-ink-muted">
            {sessions.isPending
              ? 'Checking active sessions…'
              : sessions.isError
                ? `Could not load sessions: ${errorMessage(sessions.error)}`
                : `${sessions.data.length} active session(s).`}
          </p>
          <TextField label="Reason" hint="Recorded in the audit history." error={form.formState.errors.reason?.message} {...form.register('reason')} />
          {formError && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
              {formError}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="danger" loading={m.isPending}>
              Sign out everywhere
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
}

export function UsersPanel() {
  const { can, user: me } = useAuth()
  const manage = can('users:manage')
  const manageSessions = can('sessions:manage')
  const q = useQuery({ queryKey: ['users'], queryFn: () => api.listUsers({ limit: 200 }) })
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [resetting, setResetting] = useState<User | null>(null)
  const [revoking, setRevoking] = useState<User | null>(null)

  return (
    <Card>
      <CardHeader
        icon={<Users className="size-4" />}
        title="Users & roles"
        description="Accounts are provisioned by administrators. Every change is audited."
        action={
          manage && (
            <Button size="sm" icon={<UserPlus className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
              New user
            </Button>
          )
        }
      />
      {q.isPending ? (
        <LoadingRows rows={4} label="Loading users" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.items.length === 0 ? (
        <EmptyState icon={<Users className="size-6" />} title="No users" />
      ) : (
        <div className="table-scroll relative">
          <table className="data-table min-w-[640px] text-[13px]">
            <caption className="sr-only">Users</caption>
            <thead>
              <tr>
                <th scope="col">User</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">Last sign-in</th>
                {manage && <th scope="col" className="text-right"><span className="sr-only">Actions</span></th>}
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((u) => (
                <tr key={u.id}>
                  <td className="py-3">
                    <p className="font-medium text-ink">
                      {u.full_name} {u.id === me?.id && <span className="text-xs font-normal text-ink-subtle">(you)</span>}
                    </p>
                    <p className="text-ink-subtle">{u.email}</p>
                  </td>
                  <td className="py-3">{roleLabel(u.role)}</td>
                  <td className="py-3">
                    <StatusPill status={u.is_active ? 'pass' : 'missing'}>{u.is_active ? 'Active' : 'Deactivated'}</StatusPill>
                  </td>
                  <td className="py-3 text-ink-muted">{u.last_login_at ? formatRelative(u.last_login_at) : 'Never'}</td>
                  {manage && (
                    <td className="py-3">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setEditing(u)} aria-label={`Edit ${u.email}`} icon={<Pencil className="size-3.5" aria-hidden />}>
                          Edit
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setResetting(u)} aria-label={`Reset password for ${u.email}`} icon={<KeyRound className="size-3.5" aria-hidden />}>
                          Reset
                        </Button>
                        {manageSessions && (
                          <Button size="sm" variant="ghost" onClick={() => setRevoking(u)} aria-label={`Sign ${u.email} out everywhere`} icon={<LogOut className="size-3.5" aria-hidden />}>
                            Sign out
                          </Button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CreateUserDialog open={creating} onClose={() => setCreating(false)} />
      {editing && <EditUserDialog user={editing} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />}
      {revoking && <RevokeSessionsDialog user={revoking} onClose={() => setRevoking(null)} />}
    </Card>
  )
}
