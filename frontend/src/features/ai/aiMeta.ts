import type { Status } from '../../components/ui/StatusPill'
import type { AiEvidenceLink, AiEvidenceRef, AiHealthState, AiInteractionStatus, AiProviderState } from '../../lib/types'

export const INTERACTION_STATUS: Record<AiInteractionStatus, { label: string; pill: Status; detail: string }> = {
  succeeded: { label: 'All citations verified', pill: 'pass', detail: 'Every statement cites stored records that were checked against the database.' },
  partial: { label: 'Partly filtered', pill: 'review', detail: 'Some of the model’s answer failed VerifyFlow’s checks and was removed. What remains was verified.' },
  rejected: { label: 'Rejected', pill: 'fail', detail: 'Nothing in the model’s answer passed VerifyFlow’s checks, so none of it is shown.' },
  failed: { label: 'Failed', pill: 'fail', detail: 'The AI request did not produce a usable answer.' },
}

export const HEALTH: Record<AiHealthState, { label: string; pill: Status }> = {
  unknown: { label: 'No calls yet', pill: 'unknown' },
  healthy: { label: 'Healthy', pill: 'pass' },
  degraded: { label: 'Degraded', pill: 'review' },
  failing: { label: 'Failing', pill: 'fail' },
}

export function providerSummary(p: AiProviderState): { label: string; pill: Status } {
  if (!p.enabled) return { label: 'AI off', pill: 'missing' }
  if (p.health.state === 'failing') return { label: `${p.model ?? p.name} · failing`, pill: 'fail' }
  if (p.health.state === 'degraded') return { label: `${p.model ?? p.name} · degraded`, pill: 'review' }
  return { label: p.model ?? p.name, pill: 'info' }
}

export const REF_KIND: Record<AiEvidenceRef['kind'], string> = {
  rule_result: 'Rule result',
  rule_version: 'Rule version',
  field: 'Extracted field',
  correction: 'Correction',
  finding: 'Cross-document check',
  evidence_ref: 'Compared value',
  unknown: 'Record',
}

/** In-app route for an evidence link. Links come from the server's stored records, never from model text. */
export function evidenceHref(link: AiEvidenceLink | null): string | null {
  if (!link) return null
  switch (link.type) {
    case 'field': {
      if (!link.document_id) return `/applications/${link.application_id}`
      const q = new URLSearchParams({ page: String(link.page_number ?? 1) })
      if (link.field_key) q.set('field', link.field_key)
      return `/applications/${link.application_id}/documents/${link.document_id}?${q}`
    }
    case 'rule_result':
      return `/applications/${link.application_id}`
    case 'rule_version':
      return `/compliance/rules/${link.rule_id}`
    case 'finding':
      return `/applications/${link.application_id}/evidence`
  }
}

export const DROP_REASON: Record<string, string> = {
  unverified_reference: 'cited a record that could not be verified',
  authenticity_claim: 'made an authenticity claim',
  decision_claim: 'made an approval or rejection claim',
  override_claim: 'questioned or overrode a deterministic result',
  link: 'contained a link',
  secret_reference: 'mentioned credentials or secrets',
  instruction_echo: 'repeated instructions from a document',
  unknown_field: 'named an unknown field',
  page_not_sent: 'cited a page that was not sent',
  quote_not_found: 'quoted text that is not on the cited page',
  value_not_in_quote: 'gave a value that is not in its quote',
  invalid_value: 'failed the field’s normalizer',
  duplicate: 'duplicated another suggestion',
}

export const REF_REJECTION: Record<string, string> = {
  malformed: 'not a record id',
  not_found: 'no such record',
  other_application: 'belongs to another application',
  not_in_context: 'not among the records provided',
}

export const SIGNAL_LABEL: Record<string, string> = {
  ignore_instructions: 'asks to ignore instructions',
  role_override: 'tries to change the assistant’s role',
  system_prompt: 'mentions system prompts',
  secret_request: 'mentions keys, passwords or secrets',
  tool_request: 'asks to run tools or code',
  verdict_injection: 'asks for a verdict (authentic, approved, passed)',
  chat_markup: 'contains chat-style role markers',
}

export const CATEGORY_LABEL: Record<string, string> = {
  rule_metadata: 'rule metadata',
  finding_metadata: 'finding metadata',
  extracted_values: 'extracted values',
  document_names: 'file names',
  free_text: 'correction reasons and stored explanations',
  page_text: 'page text',
}

export function countBy<T extends string>(items: T[]): [T, number][] {
  const m = new Map<T, number>()
  for (const i of items) m.set(i, (m.get(i) ?? 0) + 1)
  return [...m.entries()]
}

export const usd = (n: number) => (n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`)
