import type { Status } from '../../components/ui/StatusPill'
import type { ApplicationStatus, DocumentStatus } from '../../lib/types'

export const APP_STATUS: Record<ApplicationStatus, { label: string; pill: Status; hint: string }> = {
  draft: { label: 'Draft', pill: 'missing', hint: 'No documents processed yet' },
  processing: { label: 'Processing', pill: 'info', hint: 'Documents are being inspected' },
  needs_review: { label: 'Needs review', pill: 'review', hint: 'Ready for a reviewer' },
  completed: { label: 'Completed', pill: 'pass', hint: 'Marked complete by a reviewer' },
  archived: { label: 'Archived', pill: 'unknown', hint: 'Read-only' },
}

export const DOC_STATUS: Record<DocumentStatus, { label: string; pill: Status }> = {
  queued: { label: 'Queued', pill: 'info' },
  processing: { label: 'Processing', pill: 'info' },
  ready: { label: 'Ready', pill: 'pass' },
  needs_review: { label: 'Needs review', pill: 'review' },
  failed: { label: 'Failed', pill: 'fail' },
}

export const APP_STATUSES = Object.keys(APP_STATUS) as ApplicationStatus[]
