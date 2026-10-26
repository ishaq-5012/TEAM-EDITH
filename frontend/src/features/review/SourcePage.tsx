import { useQuery } from '@tanstack/react-query'
import { FileQuestion } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ErrorState } from '../../components/ui/States'
import { fetchPageImage } from '../../lib/api'
import type { ReviewField } from '../../lib/types'

const SCALE = 1.5

/** The original document page as rendered by the server, with the extracted value's box highlighted. */
export function SourcePage({ applicationId, field }: { applicationId: string; field: ReviewField }) {
  const { page_number: page, bbox, page_width: pw, page_height: ph } = field
  const q = useQuery({
    queryKey: ['page-image', field.document_id, page, SCALE],
    queryFn: () => fetchPageImage(applicationId, field.document_id, page!, SCALE),
    enabled: !!page,
    staleTime: 5 * 60_000,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!q.data) return
    const u = URL.createObjectURL(q.data)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [q.data])

  if (!page) {
    return (
      <div className="grid place-items-center rounded-xl border border-dashed border-line-strong bg-navy-50/50 px-6 py-16 text-center">
        <FileQuestion className="mb-2 size-6 text-ink-subtle" aria-hidden />
        <p className="text-[13px] text-ink-muted">“{field.label}” was not found on any page of {field.document_name}, so there is no location to show.</p>
      </div>
    )
  }
  if (q.isPending) return <div className="skeleton aspect-[1/1.3] w-full rounded-xl" aria-label="Loading page" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
  return (
    <figure className="m-0">
      <div className="relative overflow-hidden rounded-xl border border-line bg-white shadow-[var(--shadow-card)]">
        {url && <img src={url} alt={`Page ${page} of ${field.document_name}`} className="block w-full" draggable={false} />}
        {bbox && pw && ph && (
          <span
            aria-hidden
            className="absolute rounded-[2px] border-2 border-violet-600 bg-violet-500/15 shadow-[0_0_0_4px_rgb(109_68_236/0.15)]"
            style={{ left: `${(bbox[0] / pw) * 100}%`, top: `${(bbox[1] / ph) * 100}%`, width: `${((bbox[2] - bbox[0]) / pw) * 100}%`, height: `${((bbox[3] - bbox[1]) / ph) * 100}%` }}
          />
        )}
      </div>
      <figcaption className="mt-1.5 text-[11.5px] text-ink-subtle">
        {field.document_name} · page {page}
        {bbox ? ` · highlighted: ${field.label}` : ' · no box recorded for this value'}
      </figcaption>
    </figure>
  )
}
