import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, Download, Eye, FileImage, FileText, Files, Info, RotateCw, ScanText, ShieldQuestion } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { Dialog } from '../../components/ui/Dialog'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage, fetchDocumentBlob } from '../../lib/api'
import { formatBytes, formatDateTime, formatRelative } from '../../lib/format'
import type { DocumentOut, JobOut } from '../../lib/types'
import { DocumentStatusPill } from './status'

const PREVIEWABLE = new Set(['application/pdf', 'image/png', 'image/jpeg'])

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function PreviewDialog({ doc, onClose }: { doc: DocumentOut; onClose: () => void }) {
  const supported = PREVIEWABLE.has(doc.detected_mime)
  const blob = useQuery({
    queryKey: ['document-blob', doc.id],
    queryFn: () => fetchDocumentBlob(doc.application_id, doc.id),
    enabled: supported,
    gcTime: 0,
    staleTime: 0,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!blob.data) return
    const u = URL.createObjectURL(blob.data)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [blob.data])

  return (
    <Dialog open onClose={onClose} title={doc.original_filename} description={`${doc.detected_mime} · ${formatBytes(doc.size_bytes)}`} width="max-w-4xl">
      {!supported ? (
        <EmptyState icon={<FileImage className="size-6" />} title="Preview isn’t available for this format">
          Browsers can’t display {doc.detected_mime === 'image/tiff' ? 'TIFF images' : 'this file type'}. Download the file to view it.
        </EmptyState>
      ) : blob.isPending ? (
        <div className="skeleton h-[60vh] w-full" role="status" aria-label="Loading preview" />
      ) : blob.isError ? (
        <ErrorState error={blob.error} onRetry={() => blob.refetch()} />
      ) : url && doc.detected_mime === 'application/pdf' ? (
        <iframe src={url} title={`Preview of ${doc.original_filename}`} className="h-[70vh] w-full rounded-lg border border-line" />
      ) : url ? (
        <img src={url} alt={`Preview of ${doc.original_filename}`} className="mx-auto max-h-[70vh] rounded-lg border border-line object-contain" />
      ) : null}
    </Dialog>
  )
}

function JobHistory({ jobs }: { jobs: JobOut[] }) {
  return (
    <ol className="space-y-2">
      {[...jobs].reverse().map((j) => (
        <li key={j.id} className="rounded-lg border border-line bg-surface p-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
            <span className="font-medium">Attempt {j.attempt}</span>
            <span className={cn('font-mono text-[11.5px]', j.status === 'failed' ? 'text-fail' : j.status === 'succeeded' ? 'text-pass' : 'text-info')}>{j.status}</span>
            <span className="text-ink-subtle">
              {j.finished_at ? `finished ${formatDateTime(j.finished_at)}` : j.started_at ? `started ${formatRelative(j.started_at)}` : `queued ${formatRelative(j.created_at)}`}
            </span>
          </div>
          {j.error_code && (
            <p className="mt-1.5 text-[12.5px] text-fail">
              <span className="font-mono">{j.error_code}</span>: {j.error_message}
            </p>
          )}
          {j.result.findings && j.result.findings.length > 0 && (
            <ul className="mt-2 space-y-1">
              {j.result.findings.map((f) => (
                <li key={f.code} className="flex gap-2 text-[12.5px] text-ink-muted">
                  {f.severity === 'warning' ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-review" aria-hidden /> : <Info className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden />}
                  <span>
                    <span className="sr-only">{f.severity}: </span>
                    {f.message}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  )
}

function DocumentRow({ doc, approved, onPreview }: { doc: DocumentOut; approved: boolean; onPreview: () => void }) {
  const qc = useQueryClient()
  const reduce = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const detail = useQuery({
    queryKey: ['document', doc.id, doc.updated_at, doc.latest_job?.id],
    queryFn: () => api.document(doc.application_id, doc.id),
    enabled: open,
  })
  const retry = useMutation({
    mutationFn: () => api.retryDocument(doc.application_id, doc.id),
    onSuccess: () => {
      setActionError(null)
      qc.invalidateQueries({ queryKey: ['documents', doc.application_id] })
      qc.invalidateQueries({ queryKey: ['application', doc.application_id] })
    },
    onError: (e) => setActionError(errorMessage(e)),
  })
  const download = useMutation({
    mutationFn: () => fetchDocumentBlob(doc.application_id, doc.id),
    onSuccess: (blob) => saveBlob(blob, doc.original_filename),
    onError: (e) => setActionError(errorMessage(e)),
  })
  const findings = doc.latest_job?.result.findings ?? []
  const warnings = findings.filter((f) => f.severity === 'warning').length
  const Icon = doc.detected_mime === 'application/pdf' ? FileText : FileImage

  return (
    <li className="border-b border-line last:border-0">
      <div className="grid grid-cols-[36px_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-5 py-3 sm:gap-x-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-navy-50 text-ink" aria-hidden>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-medium" title={doc.original_filename}>
            {doc.original_filename}
          </p>
          <p className="break-words text-[12px] text-ink-muted">
            {formatBytes(doc.size_bytes)}
            {doc.page_count != null && ` · ${doc.page_count} page${doc.page_count === 1 ? '' : 's'}`} · uploaded {formatRelative(doc.created_at)} by {doc.uploaded_by.full_name}
            {warnings > 0 && <span className="text-review"> · {warnings} warning{warnings === 1 ? '' : 's'}</span>}
          </p>
        </div>
        <div className="col-start-2 flex min-w-0 flex-wrap items-center gap-2">
          {approved ? <StatusPill status="pass">Case approved by auditor</StatusPill> : <DocumentStatusPill status={doc.status} />}
        </div>
        <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-1 sm:col-start-2 sm:col-span-1">
          {doc.can_retry && (
            <Button size="sm" variant="secondary" loading={retry.isPending} onClick={() => retry.mutate()} icon={<RotateCw className="size-3.5" aria-hidden />}>
              Retry
            </Button>
          )}
          <Link
            to={`/applications/${doc.application_id}/documents/${doc.id}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-violet-700 hover:bg-violet-50"
            aria-label={`Inspect extraction for ${doc.original_filename}`}
          >
            <ScanText className="size-3.5" aria-hidden /> Inspect
          </Link>
          <Link
            to={`/applications/${doc.application_id}/documents/${doc.id}/trust`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-violet-700 hover:bg-violet-50"
            aria-label={`Verify ${doc.original_filename}`}
          >
            <ShieldQuestion className="size-3.5" aria-hidden /> Verify
          </Link>
          <Button size="sm" variant="ghost" onClick={onPreview} aria-label={`Preview ${doc.original_filename}`} icon={<Eye className="size-3.5" aria-hidden />}>
            Preview
          </Button>
          <Button size="sm" variant="ghost" loading={download.isPending} onClick={() => download.mutate()} aria-label={`Download ${doc.original_filename}`}>
            {!download.isPending && <Download className="size-3.5" aria-hidden />}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} details for ${doc.original_filename}`}>
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
          </Button>
        </div>
      </div>
      {actionError && (
        <p role="alert" className="mx-5 mb-3 rounded-lg bg-fail-bg px-3 py-2 text-[12.5px] text-fail">
          {actionError}
        </p>
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reduce ? { opacity: 1 } : { height: 'auto', opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="grid gap-4 bg-navy-50/50 px-5 py-4 text-[12.5px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-x-3 gap-y-1.5">
                <dt className="text-ink-subtle">SHA-256</dt>
                <dd className="font-mono break-all" title={doc.sha256}>
                  {doc.sha256}
                </dd>
                <dt className="text-ink-subtle">Detected type</dt>
                <dd className="font-mono">{doc.detected_mime}</dd>
                <dt className="text-ink-subtle">Declared type</dt>
                <dd className="font-mono">{doc.declared_mime ?? '—'}</dd>
                <dt className="text-ink-subtle">Document type</dt>
                <dd>{doc.document_type ?? '—'}</dd>
                <dt className="text-ink-subtle">Processing status</dt>
                <dd><DocumentStatusPill status={doc.status} /></dd>
                <dt className="text-ink-subtle">Uploaded</dt>
                <dd>
                  {formatDateTime(doc.created_at)} by {doc.uploaded_by.email}
                </dd>
              </dl>
              <div>
                <p className="mb-2 font-medium text-ink">Processing history</p>
                {detail.isPending ? (
                  <LoadingRows rows={1} label="Loading processing history" />
                ) : detail.isError ? (
                  <ErrorState compact error={detail.error} onRetry={() => detail.refetch()} />
                ) : (
                  <JobHistory jobs={detail.data.jobs} />
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

export function DocumentInventory({ applicationId, approved = false }: { applicationId: string; approved?: boolean }) {
  const qc = useQueryClient()
  const [previewing, setPreviewing] = useState<DocumentOut | null>(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const q = useQuery({
    queryKey: ['documents', applicationId],
    queryFn: () => api.documents(applicationId),
    // Poll only while something is still being processed.
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === 'queued' || d.status === 'processing') ? 2000 : false),
  })
  // When processing settles, the application's own status changes server-side: refresh it.
  const inFlight = !!q.data?.some((d) => d.status === 'queued' || d.status === 'processing')
  const wasInFlight = useRef(inFlight)
  useEffect(() => {
    if (wasInFlight.current && !inFlight) {
      qc.invalidateQueries({ queryKey: ['application', applicationId] })
      qc.invalidateQueries({ queryKey: ['applications'] })
    }
    wasInFlight.current = inFlight
  }, [inFlight, applicationId, qc])
  const counts = q.data?.reduce<Record<string, number>>((acc, d) => ({ ...acc, [d.status]: (acc[d.status] ?? 0) + 1 }), {})
  const visible = q.data?.filter((d) =>
    (status === 'all' || d.status === status) &&
    `${d.original_filename} ${d.document_type ?? ''} ${d.uploaded_by.full_name}`.toLowerCase().includes(search.trim().toLowerCase()),
  ) ?? []

  return (
    <Card>
      <CardHeader
        icon={<Files className="size-4" />}
        title="Documents"
        description={
          q.data && q.data.length > 0
            ? `${q.data.length} document${q.data.length === 1 ? '' : 's'}` +
              (counts?.failed ? ` · ${counts.failed} failed` : '') +
              (!approved && counts?.needs_review ? ` · ${counts.needs_review} need review` : '') +
              (approved ? ' · case approved by auditor' : '')
            : 'Every file is hashed, type-checked and inspected after upload.'
        }
      />
      {q.data && q.data.length > 0 && (
        <div className="flex flex-wrap gap-2 border-b border-line px-5 py-3">
          <input aria-label="Find a document" placeholder="Find document or uploader" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 min-w-44 flex-1 rounded-lg border border-line-strong bg-surface px-3 text-[13px]" />
          <select aria-label="Filter document processing status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 rounded-lg border border-line-strong bg-surface px-3 text-[13px]">
            <option value="all">All processing statuses</option>
            <option value="ready">Status: ready</option>
            <option value="needs_review">Status: needs review</option>
            <option value="failed">Status: failed</option>
            <option value="processing">Status: processing</option>
          </select>
          <span className="self-center text-[12px] text-ink-muted">{visible.length} of {q.data.length}</span>
        </div>
      )}
      {q.isPending ? (
        <LoadingRows rows={3} label="Loading documents" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyState icon={<Files className="size-6" />} title="No documents yet">
          Uploaded documents appear here with their processing status.
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState icon={<Files className="size-6" />} title="No matching documents">Clear the search or choose another status.</EmptyState>
      ) : (
        <ul>
          {visible.map((d) => (
            <DocumentRow key={d.id} doc={d} approved={approved} onPreview={() => setPreviewing(d)} />
          ))}
        </ul>
      )}
      {previewing && <PreviewDialog doc={previewing} onClose={() => setPreviewing(null)} />}
    </Card>
  )
}
