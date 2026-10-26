import { useQuery } from '@tanstack/react-query'
import { ArrowRight, FolderKanban, Network } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageContainer } from '../../components/layout/PageContainer'
import { Card } from '../../components/ui/Card'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { api } from '../../lib/api'
import { formatRelative } from '../../lib/format'
import { ApplicationStatusPill } from '../applications/status'

/** Module landing page: evidence is analysed per application, so start by choosing one. */
export function EvidenceIndexPage() {
  const q = useQuery({ queryKey: ['applications', { evidence: true }], queryFn: () => api.applications({ sort: 'updated_desc', limit: 50 }) })
  return (
    <PageContainer
      eyebrow="Evidence Intelligence Graph"
      title="Evidence Intelligence Graph"
      description="Cross-document reasoning is run per application. Choose an application to open its evidence graph."
    >
      <Card>
        {q.isPending ? (
          <LoadingRows rows={5} label="Loading applications" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <EmptyState icon={<FolderKanban className="size-6" />} title="No applications yet">
            Create an application and upload documents first.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {q.data.items.map((a) => (
              <li key={a.id}>
                <Link to={`/applications/${a.id}/evidence`} className="group flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3.5 hover:bg-navy-50/50">
                  <Network className="size-4 text-violet-400" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium group-hover:text-violet-700">{a.title}</span>
                    <span className="font-mono text-[11.5px] text-ink-subtle">{a.reference}</span>
                    <span className="text-[12px] text-ink-subtle"> · {a.document_count} documents · updated {formatRelative(a.updated_at)}</span>
                  </span>
                  <ApplicationStatusPill status={a.status} />
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
