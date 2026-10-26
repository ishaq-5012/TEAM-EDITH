import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import type { Status } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import type { InsightsParams, MetricDefinition, SimOutcome } from '../../lib/types'
import { RULE_OUTCOME } from '../compliance/ruleMeta'

export const DEFAULT_DAYS = 30

const iso = (d: Date) => d.toISOString().slice(0, 10)

export function daysAgo(n: number, from = new Date()): string {
  const d = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate()))
  d.setUTCDate(d.getUTCDate() - n)
  return iso(d)
}

export const todayUtc = () => daysAgo(0)

/** The insights window and scope, kept in the URL so every view is linkable. Dates are UTC days, both inclusive. */
export function useInsightsWindow() {
  const [params, setParams] = useSearchParams()
  const value: Required<Pick<InsightsParams, 'from' | 'to' | 'include_synthetic'>> & { application_type: string } = {
    from: params.get('from') ?? daysAgo(DEFAULT_DAYS - 1),
    to: params.get('to') ?? todayUtc(),
    application_type: params.get('type') ?? '',
    include_synthetic: params.get('synthetic') !== 'exclude',
  }
  const update = (patch: Partial<typeof value>) => {
    const next = { ...value, ...patch }
    const p = new URLSearchParams(params)
    p.set('from', next.from)
    p.set('to', next.to)
    if (next.application_type) p.set('type', next.application_type)
    else p.delete('type')
    if (next.include_synthetic) p.delete('synthetic')
    else p.set('synthetic', 'exclude')
    setParams(p, { replace: true })
  }
  const query: InsightsParams = {
    from: value.from,
    to: value.to,
    application_type: value.application_type || undefined,
    include_synthetic: value.include_synthetic,
  }
  return { value, update, query }
}

export function useDefinitions() {
  const q = useQuery({ queryKey: ['metric-definitions'], queryFn: api.metricDefinitions, staleTime: Infinity })
  const byKey = new Map<string, MetricDefinition>((q.data ?? []).map((d) => [d.key, d]))
  return { ...q, byKey }
}

export function pct(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—'
  const v = rate * 100
  return `${v < 10 && v !== 0 ? v.toFixed(1) : Math.round(v)}%`
}

/** Mark colors for state rows. Each row also carries a text label and icon, so color never carries identity alone. */
export const STATUS_FILL: Record<Status, string> = {
  pass: 'var(--color-pass)',
  fail: 'var(--color-fail)',
  review: 'var(--color-review)',
  missing: 'var(--color-missing)',
  info: 'var(--color-info)',
  unknown: 'var(--color-line-strong)',
}

/** Categorical slots 1 and 2 of the validated reference palette (adjacent CVD ΔE 24.7, normal ΔE 33.6, ≥3:1). */
export const SERIES = ['#2a78d6', '#eb6834'] as const

export const OUTCOME_CATEGORY: Record<string, string> = { fail: 'failure', review: 'uncertain', insufficient: 'missing' }

export const SEVERITIES = ['critical', 'high', 'medium', 'low'] as const

export const AGE_LABEL: Record<string, string> = {
  under_1_day: 'Under 1 day',
  '1_to_7_days': '1–7 days',
  '7_to_30_days': '7–30 days',
  over_30_days: 'Over 30 days',
}

export const FIELD_STATUS: Record<string, { label: string; pill: Status }> = {
  found: { label: 'Found', pill: 'pass' },
  ambiguous: { label: 'Ambiguous', pill: 'review' },
  invalid: { label: 'Invalid', pill: 'fail' },
  missing: { label: 'Missing', pill: 'missing' },
}

export const OCR_LABEL: Record<string, string> = {
  not_needed: 'Not needed (text layer)',
  completed: 'OCR completed',
  low_confidence: 'OCR low confidence',
  unavailable: 'OCR unavailable',
  failed: 'OCR failed',
  skipped_limit: 'Skipped (page limit)',
}

export const EVENT_LABEL: Record<string, { label: string; pill: Status }> = {
  created: { label: 'Draft created', pill: 'info' },
  submitted: { label: 'Submitted', pill: 'review' },
  approved: { label: 'Approved', pill: 'pass' },
  rejected: { label: 'Rejected', pill: 'fail' },
  retired: { label: 'Retired', pill: 'missing' },
}

export const RULE_OUTCOMES: SimOutcome[] = ['fail', 'review', 'insufficient', 'pass', 'not_applicable']

export function outcomeRows(byOutcome: Record<string, number>, link = true) {
  return RULE_OUTCOMES.filter((o) => byOutcome[o] !== undefined).map((o) => ({
    key: o,
    label: RULE_OUTCOME[o].label,
    pill: RULE_OUTCOME[o].pill,
    count: byOutcome[o] ?? 0,
    to: link && OUTCOME_CATEGORY[o] ? `/review?category=${OUTCOME_CATEGORY[o]}` : undefined,
  }))
}
