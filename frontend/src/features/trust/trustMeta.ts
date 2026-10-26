import type { Status } from '../../components/ui/StatusPill'
import type { TrustDimension, TrustState } from '../../lib/types'

/**
 * The only mapping from trust states to visual status. "pass" (green) is reserved for "verified";
 * unsupported and inconclusive are deliberately neutral or amber, never green.
 */
export const TRUST_STATE: Record<TrustState, { label: string; pill: Status; hint: string }> = {
  verified: { label: 'Verified', pill: 'pass', hint: 'The check ran and positively confirmed what it tests — and only that.' },
  failed: { label: 'Failed', pill: 'fail', hint: 'The check ran and found a definite problem.' },
  inconclusive: { label: 'Inconclusive', pill: 'review', hint: 'The check ran but could not reach a verdict.' },
  unsupported: { label: 'Not checked', pill: 'unknown', hint: 'This deployment cannot perform this check for this file or configuration.' },
}

export const DIMENSIONS: TrustDimension[] = ['file_integrity', 'signature_integrity', 'certificate_trust', 'revocation', 'timestamp', 'external_registry']

export const DIMENSION: Record<TrustDimension, { label: string; question: string; short: string }> = {
  file_integrity: { label: 'File integrity', short: 'Integrity', question: 'Is the stored file exactly the one that was uploaded?' },
  signature_integrity: { label: 'Signature integrity', short: 'Signature', question: 'Are the signed bytes unchanged, and does the cryptographic signature verify?' },
  certificate_trust: { label: 'Certificate trust', short: 'Certificate', question: 'Does the signer’s certificate chain to an issuer this deployment trusts?' },
  revocation: { label: 'Revocation', short: 'Revocation', question: 'Had the signer’s certificate been revoked?' },
  timestamp: { label: 'Timestamp', short: 'Timestamp', question: 'Is there trusted proof of when the signature was made?' },
  external_registry: { label: 'Issuer / registry', short: 'Registry', question: 'Does an approved external source confirm the document’s details?' },
}

export const CAPABILITY_STATUS: Record<string, { label: string; pill: Status }> = {
  enabled: { label: 'Enabled', pill: 'info' },
  disabled: { label: 'Disabled', pill: 'unknown' },
  not_configured: { label: 'Not configured', pill: 'missing' },
  not_implemented: { label: 'Not implemented', pill: 'unknown' },
}

export const EVIDENCE_LABEL: Record<string, string> = {
  recorded_sha256: 'SHA-256 recorded at upload',
  observed_sha256: 'SHA-256 now',
  size_bytes: 'Size (bytes)',
  digest_algorithm: 'Digest algorithm',
  coverage: 'Signature coverage',
  modification_level: 'Changes after signing',
  intact: 'Signed bytes intact',
  cryptographically_valid: 'Signature verifies',
  sub_filter: 'Signature format',
  signer: 'Signer',
  trust_anchors_configured: 'Trust anchors configured',
  indication: 'ETSI indication',
  chain: 'Certificate chain (anchor first)',
  sources: 'Revocation sources',
  revocation_date: 'Revoked on',
  reason: 'Revocation reason',
  signer_reported_time: 'Signing time claimed by signer',
  timestamp: 'Timestamp',
  tsa: 'Timestamp authority',
  document_number: 'Document number queried',
  found: 'Record found',
  status: 'Registry status',
  matched_fields: 'Matching fields',
  mismatched_fields: 'Differing fields',
  registry_values: 'Registry values (differing)',
  http_status: 'HTTP status',
  error: 'Error',
}
