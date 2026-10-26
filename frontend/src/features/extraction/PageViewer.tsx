import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FileWarning } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { cn } from '../../components/ui/cn'
import { ErrorState } from '../../components/ui/States'
import { fetchPageImage } from '../../lib/api'
import type { FieldOut, PageOut } from '../../lib/types'
import { TEXT_SOURCE } from './fieldMeta'

const RENDER_SCALE = 1.5

/**
 * Renders a page as displayed and overlays field boxes from stored coordinates.
 * Boxes are positioned in percent of the page's displayed width/height, so they are independent
 * of the render scale and of the on-screen size.
 */
export function PageViewer({
  applicationId,
  documentId,
  pages,
  page,
  onPage,
  fields,
  selectedKey,
  onSelect,
}: {
  applicationId: string
  documentId: string
  pages: PageOut[]
  page: number
  onPage: (n: number) => void
  fields: FieldOut[]
  selectedKey: string | null
  onSelect: (key: string) => void
}) {
  const reduce = useReducedMotion()
  const meta = pages.find((p) => p.page_number === page)
  const image = useQuery({
    queryKey: ['page-image', documentId, page, RENDER_SCALE],
    queryFn: () => fetchPageImage(applicationId, documentId, page, RENDER_SCALE),
    staleTime: 5 * 60_000,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!image.data) return
    const u = URL.createObjectURL(image.data)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [image.data])

  const onThisPage = fields.filter((f) => f.page_number === page && f.bbox)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <span className="tabular text-[13px] text-ink-muted" aria-live="polite">
          Page {page} of {pages.length}
        </span>
        <Button size="sm" variant="secondary" disabled={page >= pages.length} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight className="size-4" aria-hidden />
        </Button>
        <div className="ml-auto flex flex-wrap gap-1" role="group" aria-label="Pages">
          {pages.map((p) => {
            const attention = p.warnings.length > 0
            return (
              <button
                key={p.page_number}
                onClick={() => onPage(p.page_number)}
                aria-current={p.page_number === page ? 'page' : undefined}
                title={`Page ${p.page_number}: ${TEXT_SOURCE[p.text_source]}${attention ? ' — needs attention' : ''}`}
                className={cn(
                  'relative h-7 min-w-7 rounded-md border px-1.5 text-[12px] font-medium tabular',
                  p.page_number === page ? 'border-violet-500 bg-violet-50 text-violet-700' : 'border-line text-ink-muted hover:border-line-strong',
                )}
              >
                {p.page_number}
                {attention && <span className="absolute -top-1 -right-1 size-2 rounded-full bg-review" aria-hidden />}
                {attention && <span className="sr-only"> (needs attention)</span>}
              </button>
            )
          })}
        </div>
      </div>

      <div className="relative overflow-hidden rounded-xl border border-line bg-navy-50/40">
        {image.isPending ? (
          <div
            className="skeleton w-full"
            style={{ aspectRatio: meta ? `${meta.width} / ${meta.height}` : '595 / 842' }}
            role="status"
            aria-label={`Rendering page ${page}`}
          />
        ) : image.isError ? (
          <ErrorState error={image.error} onRetry={() => image.refetch()} />
        ) : (
          url &&
          meta && (
            <div className="relative">
              <img src={url} alt={`Page ${page} of the document`} className="block h-auto w-full select-none" draggable={false} />
              {meta.text_source === 'none' && (
                <div className="absolute inset-x-3 top-3 flex items-center gap-2 rounded-lg bg-surface/95 px-3 py-2 text-[12.5px] shadow-[var(--shadow-card)]">
                  <FileWarning className="size-4 shrink-0 text-review" aria-hidden />
                  No readable text on this page, so nothing could be extracted from it.
                </div>
              )}
              {onThisPage.map((f) => {
                const [x0, y0, x1, y1] = f.bbox!
                const selected = f.field_key === selectedKey
                return (
                  <motion.button
                    key={f.id}
                    onClick={() => onSelect(f.field_key)}
                    aria-label={`${f.label}: ${f.effective_value ?? f.raw_value ?? ''}`}
                    aria-pressed={selected}
                    initial={false}
                    animate={{ opacity: selected ? 1 : 0.55 }}
                    transition={{ duration: reduce ? 0 : 0.15 }}
                    className={cn(
                      'absolute rounded-[3px] border-2 transition-colors',
                      selected ? 'z-10 border-violet-600 bg-violet-500/20 ring-4 ring-violet-500/20' : 'border-violet-400/80 bg-violet-400/10 hover:opacity-100',
                    )}
                    style={{
                      left: `${(x0 / meta.width) * 100}%`,
                      top: `${(y0 / meta.height) * 100}%`,
                      width: `${((x1 - x0) / meta.width) * 100}%`,
                      height: `${((y1 - y0) / meta.height) * 100}%`,
                    }}
                  >
                    {selected && (
                      <span className="absolute -top-6 left-0 rounded bg-violet-600 px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap text-white">
                        {f.label}
                      </span>
                    )}
                  </motion.button>
                )
              })}
            </div>
          )
        )}
      </div>
    </div>
  )
}
