import { Loader2 } from 'lucide-react'
import { StatusPill } from '../../components/ui/StatusPill'
import type { ApplicationStatus, DocumentStatus } from '../../lib/types'
import { APP_STATUS, DOC_STATUS } from './statusMeta'

export function ApplicationStatusPill({ status }: { status: ApplicationStatus }) {
  const s = APP_STATUS[status]
  return <StatusPill status={s.pill}>{s.label}</StatusPill>
}

export function DocumentStatusPill({ status }: { status: DocumentStatus }) {
  const s = DOC_STATUS[status]
  const busy = status === 'queued' || status === 'processing'
  return (
    <StatusPill status={s.pill} icon={busy ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : undefined}>
      {s.label}
    </StatusPill>
  )
}
