import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { fetchPageImage } from '../../lib/api'
import type { EvidenceReference } from '../../lib/types'

const SCALE = 1.5
const PAD = 0.6 // padding around the box, as a fraction of its height

/**
 * Shows the region of the rendered source page around a referenced value, with the box highlighted.
 * Uses the same displayed-page coordinate space as extraction (page_width/page_height from the API).
 */
export function EvidenceSnippet({ applicationId, reference }: { applicationId: string; reference: EvidenceReference }) {
  const { bbox, page_number: page, page_width: pw, page_height: ph } = reference
  const enabled = !!bbox && !!page && !!pw && !!ph
  const q = useQuery({
    queryKey: ['page-image', reference.document_id, page, SCALE],
    queryFn: () => fetchPageImage(applicationId, reference.document_id, page!, SCALE),
    enabled,
    staleTime: 5 * 60_000,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!q.data) return
    const u = URL.createObjectURL(q.data)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [q.data])

  if (!enabled) {
    return <p className="rounded-lg bg-navy-50 px-3 py-4 text-center text-[12px] text-ink-subtle">No source location (value not found on any page)</p>
  }
  const [x0, y0, x1, y1] = bbox!
  const pad = (y1 - y0) * PAD
  const cx0 = Math.max(0, x0 - pad * 3)
  const cy0 = Math.max(0, y0 - pad)
  const cx1 = Math.min(pw!, x1 + pad * 3)
  const cy1 = Math.min(ph!, y1 + pad)
  const cw = cx1 - cx0
  const ch = cy1 - cy0

  if (q.isPending) return <div className="skeleton w-full" style={{ aspectRatio: `${cw} / ${ch}` }} aria-hidden />
  if (q.isError || !url) return <p className="text-[12px] text-fail">Source page could not be rendered.</p>

  return (
    <figure className="m-0">
      <div className="relative w-full overflow-hidden rounded-lg border border-line bg-white" style={{ aspectRatio: `${cw} / ${ch}` }}>
        <img
          src={url}
          alt={`Excerpt of page ${page} of ${reference.document_name} showing ${reference.field_label}`}
          className="absolute max-w-none"
          style={{ width: `${(pw! / cw) * 100}%`, left: `${(-cx0 / cw) * 100}%`, top: `${(-cy0 / ch) * 100}%` }}
          draggable={false}
        />
        <span
          aria-hidden
          className="absolute rounded-[2px] border-2 border-violet-600 bg-violet-500/15"
          style={{ left: `${((x0 - cx0) / cw) * 100}%`, top: `${((y0 - cy0) / ch) * 100}%`, width: `${((x1 - x0) / cw) * 100}%`, height: `${((y1 - y0) / ch) * 100}%` }}
        />
      </div>
      <figcaption className="mt-1 text-[11px] text-ink-subtle">
        Page {page} · box [{bbox!.map((v) => v.toFixed(1)).join(', ')}]
      </figcaption>
    </figure>
  )
}
