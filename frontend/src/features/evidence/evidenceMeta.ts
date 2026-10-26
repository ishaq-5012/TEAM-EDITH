import {
  AlertTriangle, CalendarDays, CheckCircle2, CircleDashed, Hash, IdCard, Landmark, MapPin, ScanSearch, UserRound, XCircle,
  type LucideIcon,
} from 'lucide-react'
import type { Status } from '../../components/ui/StatusPill'
import type { EvidenceQuality, Outcome, Severity } from '../../lib/types'

export const OUTCOME: Record<Outcome, { label: string; short: string; pill: Status; stroke: string; dash?: string }> = {
  pass: { label: 'Consistent', short: 'match', pill: 'pass', stroke: 'var(--color-pass)' },
  fail: { label: 'Contradiction', short: 'differs', pill: 'fail', stroke: 'var(--color-fail)' },
  review: { label: 'Review required', short: 'review', pill: 'review', stroke: 'var(--color-review)' },
  insufficient: { label: 'Insufficient evidence', short: 'no data', pill: 'missing', stroke: 'var(--color-missing)', dash: '5 4' },
}

export const QUALITY: Record<EvidenceQuality, { label: string; hint: string }> = {
  high: { label: 'High', hint: 'Human-corrected, or clean text-layer extraction' },
  medium: { label: 'Medium', hint: 'OCR without quality flags, or a moderate extraction score' },
  low: { label: 'Low', hint: 'Low OCR confidence, possible look-alike characters, or an ambiguous value' },
}

export const SEVERITY: Record<Severity, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }

export const REASON: Record<string, string> = {
  equal: 'Identical',
  equal_after_normalization: 'Equal after approved normalization',
  equal_after_token_reorder: 'Equal after allowed word reorder',
  within_tolerance: 'Within configured tolerance',
  different_values: 'Values differ',
  near_match: 'Near match (possible typo)',
  token_order_differs: 'Same words, different order',
  possible_initials: 'Possible initial',
  partial_token_match: 'Partly matching words',
  possible_day_month_swap: 'Possible day/month swap',
  possible_ocr_confusion: 'Possible OCR look-alikes',
  separators_differ: 'Only separators differ',
  partial_address_match: 'Partly matching address',
  ambiguous_input: 'Ambiguous source value',
  low_quality_evidence: 'Differs, but evidence is low quality',
  missing_value: 'Value missing',
  invalid_value: 'Value invalid',
  not_extracted: 'Document not extracted',
}

export const METHOD: Record<string, string> = {
  exact: 'Exact comparison',
  approved_normalization: 'Approved normalization',
  configured_tolerance: 'Configured tolerance',
  edit_distance: 'Character difference',
  token_comparison: 'Word comparison',
  token_overlap: 'Word overlap',
  ocr_lookalike_check: 'OCR look-alike check',
  day_month_swap_check: 'Day/month swap check',
  none: 'Not compared',
}

export const FACTOR: Record<string, string> = {
  severity: 'Severity',
  outcome: 'Outcome',
  evidence_quality: 'Evidence quality',
  breadth: 'Documents involved',
  impact: 'Downstream impact',
}

/** Visual identity per outcome for the showcase views. Colour is always paired with the icon and label. */
export const OUTCOME_LOOK: Record<Outcome, { icon: LucideIcon; tile: string; ring: string; bright: string; soft: string; text: string }> = {
  fail: { icon: XCircle, tile: 'from-[#b42335] to-[#e0475a]', ring: 'var(--color-fail)', bright: '#ff7a8a', soft: 'bg-fail-bg', text: 'text-fail' },
  review: { icon: AlertTriangle, tile: 'from-[#9a5b00] to-[#d99a22]', ring: 'var(--color-review)', bright: '#f7b84b', soft: 'bg-review-bg', text: 'text-review' },
  insufficient: { icon: CircleDashed, tile: 'from-[#4b5574] to-[#7c86a6]', ring: 'var(--color-missing)', bright: '#aab3d1', soft: 'bg-missing-bg', text: 'text-missing' },
  pass: { icon: CheckCircle2, tile: 'from-[#0f7a55] to-[#2fb383]', ring: 'var(--color-pass)', bright: '#43d6a0', soft: 'bg-pass-bg', text: 'text-pass' },
}

export const OUTCOME_ORDER: Outcome[] = ['fail', 'review', 'insufficient', 'pass']

const GROUP_ICON: Record<string, LucideIcon> = {
  person_name: UserRound,
  date_of_birth: CalendarDays,
  national_id: IdCard,
  account_number: Landmark,
  address: MapPin,
  document_number: Hash,
}

export const groupIcon = (key: string): LucideIcon => GROUP_ICON[key] ?? ScanSearch
