import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Cable, FileLock2, Info, Server, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageContainer } from '../../components/layout/PageContainer'
import { Card, CardHeader } from '../../components/ui/Card'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api } from '../../lib/api'
import { formatBytes, formatRelative, shortHash } from '../../lib/format'
import { TrustBadge } from './TrustBadge'
import { CAPABILITY_STATUS, DIMENSIONS } from './trustMeta'

export function TrustCenterPage() {
  const caps = useQuery({ queryKey: ['trust-capabilities'], queryFn: api.trustCapabilities })
  const docs = useQuery({ queryKey: ['trust-documents'], queryFn: () => api.trustDocuments({ limit: 100 }) })
  return (
    <PageContainer
      eyebrow="Trust & Authentication"
      title="Trust & Authentication Center"
      description="Technical verification of uploaded files, kept as separate questions: file integrity, signature integrity, certificate trust and external-source verification. None of them proves a document’s contents are true."
    >
      {caps.data && (
        <p role="note" className="flex items-start gap-2 rounded-xl border border-info/20 bg-info-bg/60 px-4 py-3 text-[13px] leading-5 text-ink-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          {caps.data.statement}
        </p>
      )}

      <Card>
        <CardHeader icon={<Server className="size-4" />} title="Verification capabilities" description="What this deployment can check today, and what needs external infrastructure." />
        {caps.isPending ? (
          <LoadingRows rows={4} label="Loading capabilities" />
        ) : caps.isError ? (
          <ErrorState error={caps.error} onRetry={() => caps.refetch()} />
        ) : (
          <div className="grid gap-px bg-line md:grid-cols-2">
            {caps.data.capabilities.map((c) => (
              <div key={c.key} className="bg-surface px-5 py-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{c.label}</span>
                  <StatusPill status={CAPABILITY_STATUS[c.status].pill}>{CAPABILITY_STATUS[c.status].label}</StatusPill>
                  {c.requires_external && (
                    <span className="inline-flex items-center gap-1 text-[11.5px] text-ink-subtle">
                      <Cable className="size-3" aria-hidden /> needs external infrastructure
                    </span>
                  )}
                </div>
                <p className="mt-1 text-[12.5px] leading-5 text-ink-muted">{c.detail}</p>
              </div>
            ))}
          </div>
        )}
        {caps.data && caps.data.trust_material.problems.length > 0 && (
          <p role="alert" className="border-t border-line bg-review-bg/50 px-5 py-2.5 text-[12.5px] text-review">
            Configuration problems: {caps.data.trust_material.problems.join('; ')}
          </p>
        )}
        {caps.data && <p className="border-t border-line px-5 py-2 font-mono text-[11px] text-ink-subtle">{caps.data.engine_version}</p>}
      </Card>

      <Card>
        <CardHeader icon={<FileLock2 className="size-4" />} title="Documents" description="Latest verification per document. Open a document to run checks and see the full history." />
        {docs.isPending ? (
          <LoadingRows rows={5} label="Loading documents" />
        ) : docs.isError ? (
          <ErrorState error={docs.error} onRetry={() => docs.refetch()} />
        ) : docs.data.items.length === 0 ? (
          <EmptyState icon={<ShieldCheck className="size-6" />} title="No documents yet">
            Upload documents to an application to verify them here.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {docs.data.items.map(({ document: d, application: a, latest }) => (
              <li key={d.id}>
                <Link to={`/applications/${a.id}/documents/${d.id}/trust`} className="group flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 hover:bg-navy-50/50">
                  <span className="min-w-56 flex-1">
                    <span className="block text-sm font-medium group-hover:text-violet-700">{d.original_filename}</span>
                    <span className="text-[12px] text-ink-subtle">
                      <span className="font-mono">{a.reference}</span> · {formatBytes(d.size_bytes)} · SHA-256 <span className="font-mono">{shortHash(d.sha256, 12)}</span>
                    </span>
                  </span>
                  {latest ? (
                    <span className="flex flex-wrap items-center gap-1.5">
                      {DIMENSIONS.filter((k) => latest.summary[k]).map((k) => (
                        <TrustBadge key={k} state={latest.summary[k]} dimension={k} compact />
                      ))}
                      <span className="text-[11.5px] text-ink-subtle">checked {formatRelative(latest.created_at)}</span>
                    </span>
                  ) : (
                    <span className="text-[12.5px] text-ink-subtle">Never verified</span>
                  )}
                  <ArrowRight className="size-4 text-ink-subtle group-hover:text-violet-700" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </PageContainer>
  )
}
