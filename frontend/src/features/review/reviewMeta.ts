import type { Status } from '../../components/ui/StatusPill'
import type { ReviewActionType, ReviewCategory, ReviewStatus, SubmittableAction } from '../../lib/types'

export const REVIEW_STATUS: Record<ReviewStatus, { label: string; pill: Status; hint: string }> = {
  open: { label: 'Open', pill: 'review', hint: 'Waiting for a reviewer decision.' },
  awaiting_document: { label: 'Awaiting document', pill: 'info', hint: 'A document was requested; resume when it arrives.' },
  escalated: { label: 'Escalated', pill: 'fail', hint: 'Requires compliance-manager oversight.' },
  confirmed: { label: 'Confirmed', pill: 'missing', hint: 'A reviewer agreed the finding stands.' },
  dismissed: { label: 'Dismissed', pill: 'missing', hint: 'A reviewer decided the finding does not stand, with a recorded reason.' },
  resolved: { label: 'Resolved', pill: 'pass', hint: 'A later validation run no longer produced this finding.' },
}

export const CATEGORY: Record<ReviewCategory, { label: string; pill: Status; hint: string }> = {
  failure: { label: 'Rule failure', pill: 'fail', hint: 'The rule’s condition was not met.' },
  uncertain: { label: 'Uncertain', pill: 'review', hint: 'Low-confidence input, or the rule routes violations to a person.' },
  missing: { label: 'Missing evidence', pill: 'missing', hint: 'Required data was not found in any document.' },
}

export const ACTION_LABEL: Record<ReviewActionType, string> = {
  opened: 'Opened by validation',
  assigned: 'Assigned',
  unassigned: 'Unassigned',
  commented: 'Comment',
  escalated: 'Escalated',
  document_requested: 'Document requested',
  resumed: 'Resumed',
  confirmed: 'Finding confirmed',
  dismissed: 'Finding dismissed',
  reopened: 'Decision reopened',
  field_corrected: 'Extracted value corrected',
  revalidated: 'Revalidated',
}

/** Dialog copy and reason rules. Minimums mirror the server, which is the authority. */
export const ACTION_FORM: Record<
  Exclude<SubmittableAction, 'assigned' | 'unassigned'>,
  { title: string; button: string; reasonLabel: string; minReason: number; hint: string; danger?: boolean }
> = {
  commented: { title: 'Add comment', button: 'Add comment', reasonLabel: 'Comment', minReason: 1, hint: 'Comments are permanent and visible to everyone with access.' },
  escalated: { title: 'Escalate', button: 'Escalate', reasonLabel: 'Why does this need a manager?', minReason: 5, hint: 'After escalation a compliance manager must review it.' },
  document_requested: { title: 'Request a document', button: 'Request document', reasonLabel: 'Note (optional)', minReason: 0, hint: 'The item waits until you resume it.' },
  resumed: { title: 'Resume review', button: 'Resume', reasonLabel: 'Note', minReason: 0, hint: 'Returns the item to the open queue.' },
  confirmed: { title: 'Confirm finding', button: 'Confirm finding', reasonLabel: 'Reason', minReason: 5, hint: 'You agree the finding stands. This closes the item; it can be reopened with a reason.' },
  dismissed: { title: 'Dismiss finding', button: 'Dismiss finding', reasonLabel: 'Reason (at least 10 characters)', minReason: 10, hint: 'The finding and its result are kept; your reason is recorded permanently.', danger: true },
  reopened: { title: 'Reopen decision', button: 'Reopen', reasonLabel: 'Reason', minReason: 5, hint: 'Returns the item to the open queue. The earlier decision stays in history.' },
}

export const ACTIVE: ReviewStatus[] = ['open', 'awaiting_document', 'escalated']

/** A fresh idempotency key; reused for retries of the same submission. */
export const newRequestId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID().replace(/-/g, '') : `${Date.now()}${Math.random().toString(36).slice(2, 12)}`
