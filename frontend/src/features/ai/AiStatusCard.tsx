import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Sparkles, XCircle } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage } from '../../lib/api'
import { formatRelative } from '../../lib/format'
import { useAuth } from '../auth/AuthProvider'
import { ProviderBadge } from './AiParts'
import { HEALTH, usd } from './aiMeta'

/** Provider state, health, egress policy, limits and today's spend. Credentials are never sent to the browser. */
export function AiStatusCard() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['ai-status'], queryFn: api.aiStatus })
  const check = useMutation({ mutationFn: api.aiCheck, onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-status'] }) })

  return (
    <Card>
      <CardHeader
        icon={<Sparkles className="size-4" />}
        title="AI assistance"
        description="Advisory explanations and suggestions. Validation, trust checks and review never depend on it."
        action={
          can('users:manage') &&
          q.data?.provider.enabled && (
            <Button size="sm" variant="secondary" loading={check.isPending} onClick={() => check.mutate()}>
              Check connection
            </Button>
          )
        }
      />
      {q.isPending ? (
        <LoadingRows rows={4} label="Loading AI status" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
      ) : (
        <div className="space-y-3 p-5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <ProviderBadge provider={q.data.provider} />
            {q.data.provider.enabled && <StatusPill status={HEALTH[q.data.provider.health.state].pill}>{HEALTH[q.data.provider.health.state].label}</StatusPill>}
            <span className="text-ink-muted">{q.data.provider.detail}</span>
          </div>
          {q.data.provider.enabled && q.data.provider.health.last_error_code && (
            <p className="text-[12.5px] text-ink-muted">
              Last error <span className="font-mono">{q.data.provider.health.last_error_code}</span>
              {q.data.provider.health.last_error_at && ` · ${formatRelative(q.data.provider.health.last_error_at)}`} ·{' '}
              {q.data.provider.health.consecutive_failures} consecutive failure(s)
            </p>
          )}
          {check.data && (
            <p role="status" className="flex items-center gap-1.5 text-[12.5px]">
              {check.data.ok ? <CheckCircle2 className="size-4 text-pass" aria-hidden /> : <XCircle className="size-4 text-fail" aria-hidden />}
              {check.data.detail}
            </p>
          )}
          {check.isError && <p role="alert" className="text-[12.5px] text-fail">{errorMessage(check.error)}</p>}
          <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12.5px]">
            <dt className="text-ink-subtle">Data egress</dt>
            <dd>
              <span className="font-mono">{q.data.egress.policy}</span> — {q.data.egress.description}
              {q.data.egress.mask_identifiers && ' Identifiers are masked.'}
            </dd>
            <dt className="text-ink-subtle">Budget today</dt>
            <dd>
              {usd(q.data.budget.spent_today_usd)} of {usd(q.data.budget.daily_usd)} spent
            </dd>
            <dt className="text-ink-subtle">Limits</dt>
            <dd>
              {q.data.limits.timeout_seconds}s timeout · {q.data.limits.max_retries} retries · {q.data.limits.rate_limit_per_minute}/min ·{' '}
              {q.data.limits.user_rate_limit_per_hour}/user/hour
            </dd>
          </dl>
          <ul className="space-y-1 text-[12.5px]" aria-label="AI tasks">
            {q.data.tasks.map((t) => (
              <li key={t.key} className="flex items-start gap-2">
                {t.available ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-pass" aria-label="available" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-ink-subtle" aria-label="unavailable" />}
                <span>
                  {t.label}
                  {t.reason && <span className="text-ink-muted"> — {t.reason}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}
