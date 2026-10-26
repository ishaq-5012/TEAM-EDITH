import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, FileUp, RotateCw, UploadCloud, X, XCircle } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from 'react'
import { Button } from '../../components/ui/Button'
import { cn } from '../../components/ui/cn'
import { ApiError, api, errorMessage, uploadDocument, type UploadHandle } from '../../lib/api'
import { formatBytes } from '../../lib/format'
import type { UploadLimits } from '../../lib/types'

type ItemState = 'pending' | 'uploading' | 'verifying' | 'done' | 'error' | 'cancelled'

interface Item {
  id: string
  file: File
  state: ItemState
  sent: number
  total: number
  error?: string
  /** False for deterministic rejections (wrong type, too large, duplicate): retrying cannot help. */
  retryable?: boolean
}

const CONCURRENCY = 2

/** Client-side pre-check for fast feedback only. The server re-validates everything. */
function precheck(file: File, limits: UploadLimits | undefined): string | null {
  if (!limits) return null
  const ext = file.name.includes('.') ? `.${file.name.split('.').pop()!.toLowerCase()}` : ''
  const accepted = Object.values(limits.accepted).flat()
  if (!accepted.includes(ext)) return `Unsupported file type. Accepted: ${accepted.join(', ')}`
  if (file.size > limits.max_upload_bytes) return `File is ${formatBytes(file.size)}; the limit is ${formatBytes(limits.max_upload_bytes)}`
  if (file.size === 0) return 'File is empty'
  return null
}

export function UploadZone({ applicationId }: { applicationId: string }) {
  const qc = useQueryClient()
  const reduce = useReducedMotion()
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const limits = useQuery({ queryKey: ['upload-limits'], queryFn: api.uploadLimits, staleTime: Infinity })
  const [items, setItems] = useState<Item[]>([])
  const [dragging, setDragging] = useState(false)
  const handles = useRef(new Map<string, UploadHandle>())

  const patch = useCallback((id: string, p: Partial<Item>) => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...p } : x))), [])

  const start = useCallback(
    (item: Item) => {
      patch(item.id, { state: 'uploading', sent: 0, total: item.file.size, error: undefined })
      const handle = uploadDocument(applicationId, item.file, null, (sent, total) => {
        // Once every byte is sent the server validates the file before responding.
        patch(item.id, sent >= total ? { sent, total, state: 'verifying' } : { sent, total })
      })
      handles.current.set(item.id, handle)
      handle.promise
        .then(() => {
          patch(item.id, { state: 'done' })
          qc.invalidateQueries({ queryKey: ['documents', applicationId] })
          qc.invalidateQueries({ queryKey: ['application', applicationId] })
          qc.invalidateQueries({ queryKey: ['applications'] })
        })
        .catch((e: unknown) => {
          const cancelled = e instanceof ApiError && e.code === 'aborted'
          // Network failures, server errors and rate limits may succeed later; validation rejections will not.
          const retryable = !(e instanceof ApiError) || e.status === 0 || e.status >= 500 || e.status === 429
          patch(item.id, { state: cancelled ? 'cancelled' : 'error', error: cancelled ? undefined : errorMessage(e), retryable })
        })
        .finally(() => handles.current.delete(item.id))
    },
    [applicationId, patch, qc],
  )

  // Simple queue: keep at most CONCURRENCY uploads in flight.
  useEffect(() => {
    const active = items.filter((i) => i.state === 'uploading' || i.state === 'verifying').length
    const next = items.filter((i) => i.state === 'pending').slice(0, Math.max(0, CONCURRENCY - active))
    next.forEach(start)
  }, [items, start])

  // Abort in-flight uploads if the user leaves the page.
  useEffect(() => {
    const map = handles.current
    return () => map.forEach((h) => h.abort())
  }, [])

  const addFiles = (files: FileList | File[]) => {
    const added: Item[] = Array.from(files).map((file) => {
      const problem = precheck(file, limits.data)
      return {
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
        file,
        state: problem ? 'error' : 'pending',
        sent: 0,
        total: file.size,
        error: problem ?? undefined,
      }
    })
    setItems((xs) => [...added, ...xs])
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const accept = limits.data ? Object.values(limits.data.accepted).flat().join(',') : '.pdf,.png,.jpg,.jpeg,.tif,.tiff'
  const finished = items.filter((i) => i.state === 'done' || i.state === 'cancelled').length

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
          dragging ? 'border-violet-500 bg-violet-50' : 'border-line-strong bg-navy-50/40 hover:border-violet-400',
        )}
      >
        <motion.span
          animate={dragging && !reduce ? { y: -4, scale: 1.06 } : { y: 0, scale: 1 }}
          className="mb-3 grid size-12 place-items-center rounded-2xl bg-surface text-violet-400 shadow-[var(--shadow-card)]"
          aria-hidden
        >
          <UploadCloud className="size-6" />
        </motion.span>
        <p className="text-sm font-medium text-ink">
          Drag files here, or{' '}
          <label htmlFor={inputId} className="cursor-pointer text-violet-700 underline-offset-2 hover:underline">
            browse
          </label>
        </p>
        <p className="mt-1 text-[12.5px] text-ink-muted">
          PDF, PNG, JPEG or TIFF
          {limits.data && ` · up to ${formatBytes(limits.data.max_upload_bytes)} · PDFs up to ${limits.data.max_pdf_pages} pages`}
        </p>
        <p className="mt-1 text-[11.5px] text-ink-subtle">The file type is checked from its contents, not its name.</p>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          multiple
          accept={accept}
          className="sr-only"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {items.length > 0 && (
        <div className="rounded-xl border border-line">
          <div className="flex items-center justify-between border-b border-line px-4 py-2 text-[12.5px] text-ink-muted">
            <span>Uploads</span>
            {finished > 0 && (
              <button className="font-medium hover:text-ink" onClick={() => setItems((xs) => xs.filter((i) => i.state !== 'done' && i.state !== 'cancelled'))}>
                Clear finished
              </button>
            )}
          </div>
          <ul aria-live="polite">
            <AnimatePresence initial={false}>
              {items.map((it) => {
                const pct = it.total ? Math.round((it.sent / it.total) * 100) : 0
                return (
                  <motion.li
                    key={it.id}
                    layout={!reduce}
                    initial={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
                    animate={reduce ? { opacity: 1 } : { opacity: 1, height: 'auto' }}
                    exit={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
                    className="overflow-hidden border-b border-line last:border-0"
                  >
                    <div className="flex items-center gap-3 px-4 py-2.5">
                      <span className="shrink-0" aria-hidden>
                        {it.state === 'done' ? (
                          <CheckCircle2 className="size-4 text-pass" />
                        ) : it.state === 'error' ? (
                          <XCircle className="size-4 text-fail" />
                        ) : (
                          <FileUp className="size-4 text-ink-subtle" />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-3">
                          <p className="truncate text-[13px] font-medium" title={it.file.name}>
                            {it.file.name}
                          </p>
                          <span className="tabular shrink-0 text-[11.5px] text-ink-subtle">
                            {it.state === 'uploading' && `${formatBytes(it.sent)} / ${formatBytes(it.total)}`}
                            {it.state === 'verifying' && 'Verifying on server…'}
                            {it.state === 'pending' && 'Waiting…'}
                            {it.state === 'done' && 'Uploaded'}
                            {it.state === 'cancelled' && 'Cancelled'}
                            {it.state === 'error' && formatBytes(it.file.size)}
                          </span>
                        </div>
                        {(it.state === 'uploading' || it.state === 'verifying') && (
                          <div
                            className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-navy-100"
                            role="progressbar"
                            aria-label={`Uploading ${it.file.name}`}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={pct}
                          >
                            <div
                              className={cn('h-full rounded-full bg-violet-600 transition-[width] duration-200', it.state === 'verifying' && 'animate-pulse motion-reduce:animate-none')}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        )}
                        {it.error && <p className="mt-0.5 text-[12px] text-fail">{it.error}</p>}
                      </div>
                      {it.state === 'uploading' && (
                        <Button size="sm" variant="ghost" aria-label={`Cancel upload of ${it.file.name}`} onClick={() => handles.current.get(it.id)?.abort()}>
                          <X className="size-4" aria-hidden />
                        </Button>
                      )}
                      {(it.state === 'cancelled' || (it.state === 'error' && it.retryable)) && (
                        <Button size="sm" variant="ghost" icon={<RotateCw className="size-3.5" aria-hidden />} onClick={() => patch(it.id, { state: 'pending', error: undefined })}>
                          Retry
                        </Button>
                      )}
                      {it.state === 'error' && (
                        <Button size="sm" variant="ghost" aria-label={`Dismiss ${it.file.name}`} onClick={() => setItems((xs) => xs.filter((x) => x.id !== it.id))}>
                          <X className="size-4" aria-hidden />
                        </Button>
                      )}
                    </div>
                  </motion.li>
                )
              })}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </div>
  )
}
