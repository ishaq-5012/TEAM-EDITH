import { ExternalLink, Scale } from 'lucide-react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { panelSwap } from '../../lib/motion'
import { Card, CardHeader } from '../../components/ui/Card'
import { StatusPill } from '../../components/ui/StatusPill'
import type { EvidenceFinding, EvidenceReference, FieldRelationship } from '../../lib/types'
import { AiExplanationPanel } from '../ai/AiExplanationPanel'
import { EvidenceSnippet } from './EvidenceSnippet'
import type { Selection } from './EvidenceGraph'
import { FACTOR, METHOD, OUTCOME, QUALITY, REASON, SEVERITY } from './evidenceMeta'

function inspectorLink(applicationId: string, r: EvidenceReference) {
  const q = new URLSearchParams()
  if (r.page_number) q.set('page', String(r.page_number))
  q.set('field', r.field_key)
  return `/applications/${applicationId}/documents/${r.document_id}?${q}`
}

function ReferenceCard({ applicationId, reference: r, heading }: { applicationId: string; reference: EvidenceReference; heading?: string }) {
  return (
    <section className="min-w-0 space-y-2.5 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]" aria-label={heading ?? r.document_name}>
      {heading && <p className="text-[11px] font-semibold tracking-wider text-ink-subtle uppercase">{heading}</p>}
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 truncate text-[13px] font-semibold" title={r.document_name}>
          {r.document_name}
        </p>
        <Link to={inspectorLink(applicationId, r)} className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium text-violet-700 hover:underline">
          Inspect <ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">{r.document_name} at the source location</span>
        </Link>
      </div>
      <EvidenceSnippet applicationId={applicationId} reference={r} />
      <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-2 gap-y-1 text-[12px]">
        <dt className="text-ink-subtle">Compared</dt>
        <dd className="font-mono break-words whitespace-pre-wrap">{r.effective_value ?? '—'}</dd>
        <dt className="text-ink-subtle">Raw</dt>
        <dd className="font-mono break-words whitespace-pre-wrap">{r.raw_value ?? '—'}</dd>
        <dt className="text-ink-subtle">Normalized</dt>
        <dd className="font-mono break-words whitespace-pre-wrap">{r.normalized_value ?? '—'}</dd>
        <dt className="text-ink-subtle">Source</dt>
        <dd>{r.value_source === 'correction' ? 'Human correction' : r.value_source === 'extracted' ? `Extracted (${r.method === 'ocr_rule' ? 'OCR' : 'text layer'})` : 'No value'}</dd>
        <dt className="text-ink-subtle">Status</dt>
        <dd>{r.status.replace('_', ' ')}</dd>
        <dt className="text-ink-subtle">Quality</dt>
        <dd title={QUALITY[r.evidence_quality].hint}>
          {QUALITY[r.evidence_quality].label}
          {r.quality_flags.length > 0 && <span className="text-ink-subtle"> · {r.quality_flags.join(', ')}</span>}
        </dd>
      </dl>
    </section>
  )
}

function DetailsList({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0))
  if (!entries.length) return null
  return (
    <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-2 gap-y-1 rounded-lg bg-navy-50 p-3 text-[12px]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-subtle">{k.replace(/_/g, ' ')}</dt>
          <dd className="font-mono break-words">{Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function RelationshipDetail({ applicationId, finding, rel }: { applicationId: string; finding: EvidenceFinding; rel: FieldRelationship }) {
  const src = finding.references.find((r) => r.id === rel.source_reference_id)!
  const tgt = finding.references.find((r) => r.id === rel.target_reference_id)!
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={OUTCOME[rel.result].pill}>{OUTCOME[rel.result].label}</StatusPill>
        <span className="text-[12.5px] text-ink-muted">
          {METHOD[rel.method] ?? rel.method} · {REASON[rel.reason] ?? rel.reason}
          {rel.evidence_quality && ` · ${QUALITY[rel.evidence_quality].label.toLowerCase()} quality evidence`}
        </span>
      </div>
      <p className="text-[13px] leading-5">{rel.explanation}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <ReferenceCard applicationId={applicationId} reference={src} heading="Source" />
        <ReferenceCard applicationId={applicationId} reference={tgt} heading="Target" />
      </div>
      <DetailsList details={rel.details} />
    </div>
  )
}

function FindingDetail({ finding }: { finding: EvidenceFinding }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={OUTCOME[finding.outcome].pill}>{OUTCOME[finding.outcome].label}</StatusPill>
        <span className="rounded-full bg-navy-50 px-2 py-0.5 text-[11.5px] font-medium">Severity: {SEVERITY[finding.severity]}</span>
        <span className="rounded-full bg-navy-50 px-2 py-0.5 text-[11.5px] font-medium">
          Evidence quality: {finding.evidence_quality ? QUALITY[finding.evidence_quality].label : 'none'}
        </span>
      </div>
      <p className="text-[13px] leading-5">{finding.explanation}</p>
      <div>
        <p className="mb-2 flex items-center justify-between text-[13px] font-semibold">
          Priority {finding.priority_score}/100
          <span className="text-[11.5px] font-normal text-ink-subtle">Deterministic ordering aid, not a compliance decision</span>
        </p>
        <ul className="space-y-2">
          {finding.priority_factors.map((f) => (
            <li key={f.factor} className="text-[12px]">
              <div className="flex justify-between">
                <span className="font-medium">{FACTOR[f.factor] ?? f.factor}</span>
                <span className="tabular text-ink-muted">
                  +{f.contribution} / {f.max}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-navy-100" role="presentation">
                <div className="h-full rounded-full bg-violet-500" style={{ width: `${(f.contribution / f.max) * 100}%` }} />
              </div>
              <p className="mt-0.5 text-ink-subtle">{f.explanation}</p>
            </li>
          ))}
        </ul>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-center text-[12px]">
        {(['with_value', 'missing', 'not_extracted'] as const).map((k) => (
          <div key={k} className="rounded-lg bg-navy-50 py-2">
            <dt className="text-ink-subtle">{k.replace('_', ' ')}</dt>
            <dd className="tabular text-base font-semibold">{finding.coverage[k] ?? 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Title and body for the current selection; shared by the drawer and any inline panel. */
// eslint-disable-next-line react-refresh/only-export-components
export function evidenceDetail(applicationId: string, findings: EvidenceFinding[], selection: Selection): { title: string; eyebrow: string; body: ReactNode } | null {
  const finding = selection && findings.find((f) => f.id === selection.findingId)
  if (!finding || !selection) return null
  if (selection.kind === 'finding') {
    return {
      title: finding.group_label,
      eyebrow: 'Check',
      body: (
        <div className="space-y-5">
          <FindingDetail finding={finding} />
          <AiExplanationPanel subjectType="evidence_finding" subjectId={finding.id} />
        </div>
      ),
    }
  }
  if (selection.kind === 'relationship') {
    const rel = finding.relationships.find((r) => r.id === selection.id)
    if (!rel) return null
    return { title: `${finding.group_label}: comparison`, eyebrow: 'Comparison', body: <RelationshipDetail applicationId={applicationId} finding={finding} rel={rel} /> }
  }
  const ref = finding.references.find((r) => r.id === selection.id)
  if (!ref) return null
  return { title: `${finding.group_label}: ${ref.document_name}`, eyebrow: 'Evidence value', body: <ReferenceCard applicationId={applicationId} reference={ref} /> }
}

export function EvidenceDetailPanel({ applicationId, findings, selection }: { applicationId: string; findings: EvidenceFinding[]; selection: Selection }) {
  const detail = evidenceDetail(applicationId, findings, selection)
  const title = detail?.title ?? 'Evidence detail'
  const body = detail?.body ?? (
    <p className="text-[13px] text-ink-muted">Select a check, a value or a relationship in the graph or list to see its evidence, source locations and comparison details.</p>
  )
  return (
    <Card className="xl:sticky xl:top-20">
      <CardHeader icon={<Scale className="size-4" />} title={title} />
      <div className="p-4" aria-live="polite">
        {/* Enter-only fade: the new selection's evidence appears immediately, never waiting on an exit animation. */}
        <motion.div key={selection ? `${selection.kind}:${selection.findingId}:${'id' in selection ? selection.id : ''}` : 'none'} variants={panelSwap} initial="initial" animate="animate">
          {body}
        </motion.div>
      </div>
    </Card>
  )
}
