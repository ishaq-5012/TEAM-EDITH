import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Laptop, LogOut, MonitorSmartphone } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage } from '../../lib/api'
import { describeAgent, formatDateTime, formatRelative } from '../../lib/format'

export function SessionsCard() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['my-sessions'], queryFn: api.mySessions })
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const done = (msg: string) => {
    setError(null)
    setNotice(msg)
    qc.invalidateQueries({ queryKey: ['my-sessions'] })
  }
  const revokeOne = useMutation({
    mutationFn: api.revokeSession,
    onSuccess: () => done('Session signed out.'),
    onError: (e) => setError(errorMessage(e)),
  })
  const revokeOthers = useMutation({
    mutationFn: api.revokeOtherSessions,
    onSuccess: (r) => done(r.revoked === 0 ? 'No other sessions were active.' : `Signed out ${r.revoked} other session(s).`),
    onError: (e) => setError(errorMessage(e)),
  })
  const others = q.data?.filter((s) => !s.current).length ?? 0

  return (
    <Card>
      <CardHeader
        icon={<MonitorSmartphone className="size-4" />}
        title="Active sessions"
        description="Where you're signed in. Sign out any session you don't recognise."
        action={
          <Button
            size="sm"
            variant="secondary"
            disabled={others === 0}
            disabledReason="You have no other active sessions."
            loading={revokeOthers.isPending}
            onClick={() => revokeOthers.mutate()}
            icon={<LogOut className="size-3.5" aria-hidden />}
          >
            Sign out other sessions
          </Button>
        }
      />
      {(notice || error) && (
        <p role={error ? 'alert' : 'status'} className={`mx-5 mt-4 rounded-lg px-3 py-2 text-[13px] ${error ? 'bg-fail-bg text-fail' : 'bg-pass-bg text-pass'}`}>
          {error ?? notice}
        </p>
      )}
      {q.isPending ? (
        <LoadingRows rows={2} label="Loading sessions" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <ul className="divide-y divide-line">
          {q.data.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
              <span className="grid size-9 place-items-center rounded-lg bg-navy-50 text-ink" aria-hidden>
                <Laptop className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {describeAgent(s.user_agent)}
                  {s.current && <StatusPill status="pass">This device</StatusPill>}
                </p>
                <p className="text-[12.5px] text-ink-muted">
                  {s.ip_address ?? 'Unknown IP'} · signed in {formatDateTime(s.created_at)} · active {formatRelative(s.last_seen_at)}
                </p>
              </div>
              {!s.current && (
                <Button size="sm" variant="ghost" loading={revokeOne.isPending && revokeOne.variables === s.id} onClick={() => revokeOne.mutate(s.id)}>
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
