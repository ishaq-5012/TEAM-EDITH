import type { Status } from '../../components/ui/StatusPill'
import type { FieldStatus, OcrStatus, TextSource } from '../../lib/types'

export const FIELD_STATUS: Record<FieldStatus, { label: string; pill: Status; hint: string }> = {
  found: { label: 'Found', pill: 'pass', hint: 'Value located and normalized' },
  missing: { label: 'Missing', pill: 'missing', hint: 'No labelled value found in readable text' },
  invalid: { label: 'Invalid', pill: 'fail', hint: 'Found, but the value is not valid for this field' },
  ambiguous: { label: 'Ambiguous', pill: 'review', hint: 'Found, but it can be read more than one way' },
}

export const TEXT_SOURCE: Record<TextSource, string> = {
  text_layer: 'Text layer',
  ocr: 'OCR',
  none: 'No text',
}

export const OCR_STATUS: Record<OcrStatus, { label: string; pill: Status }> = {
  not_needed: { label: 'OCR not needed', pill: 'pass' },
  completed: { label: 'OCR completed', pill: 'pass' },
  low_confidence: { label: 'OCR low confidence', pill: 'review' },
  unavailable: { label: 'OCR unavailable', pill: 'missing' },
  failed: { label: 'OCR failed', pill: 'fail' },
  skipped_limit: { label: 'OCR skipped (limit)', pill: 'missing' },
}

/** Human-readable explanations of quality flags. Unknown flags fall back to their code. */
export const FLAG_LABELS: Record<string, string> = {
  ocr_source: 'Read by OCR',
  low_ocr_confidence: 'Low OCR confidence',
  possible_ocr_confusion: 'Possible OCR look-alike characters (O/0, I/l/1). Check the source',
  ambiguous_day_month: 'Day and month could be swapped',
  conflicting_candidates: 'Different values found elsewhere in the document',
  pages_without_text: 'Some pages had no readable text',
  required_missing: 'Required for this document type',
  address_truncated: 'Address had more lines than configured; extra lines omitted',
}

export const METHOD_LABELS: Record<string, string> = {
  text_layer_rule: 'Label rule on the PDF text layer',
  ocr_rule: 'Label rule on OCR text',
}

export const VALUE_HINTS: Record<string, string> = {
  date: 'Enter as YYYY-MM-DD, e.g. 1990-03-03.',
  identifier: 'Enter exactly as printed. Separators are kept unless the field is configured to remove them.',
  address: 'One address line per line.',
  name: 'Enter the full name as printed.',
  document_number: 'Enter exactly as printed.',
}
