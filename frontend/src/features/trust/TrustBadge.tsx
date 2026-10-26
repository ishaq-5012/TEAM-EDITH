import { Ban, CircleHelp } from 'lucide-react'
import { StatusPill } from '../../components/ui/StatusPill'
import type { TrustDimension, TrustState } from '../../lib/types'
import { DIMENSION, TRUST_STATE } from './trustMeta'

/** The one place trust states become badges, so "verified" styling can't leak to other states. */
export function TrustBadge({ state, dimension, compact }: { state: TrustState | undefined; dimension?: TrustDimension; compact?: boolean }) {
  const label = dimension ? (compact ? DIMENSION[dimension].short : DIMENSION[dimension].label) : undefined
  if (!state) {
    return (
      <StatusPill status="unknown" icon={<Ban className="size-3.5" aria-hidden />}>
        {label ? `${label}: n/a` : 'Not applicable'}
      </StatusPill>
    )
  }
  const meta = TRUST_STATE[state]
  return (
    <span title={meta.hint} data-trust-state={state}>
      <StatusPill status={meta.pill} icon={state === 'unsupported' ? <CircleHelp className="size-3.5" aria-hidden /> : undefined}>
        {label ? `${label}: ${meta.label.toLowerCase()}` : meta.label}
      </StatusPill>
    </span>
  )
}
