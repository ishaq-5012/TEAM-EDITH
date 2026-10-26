import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Bot, FileSearch, Info, RefreshCw, RotateCw, ScanText } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useBreadcrumbTrail } from '../../components/layout/crumbStore'
import { PageContainer } from '../../components/layout/PageContainer'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { cn } from '../../components/ui/cn'
import { EmptyState, ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { ApiError, api, errorMessage } from '../../lib/api'
import { formatDateTime, shortHash } from '../../lib/format'
import type { ExtractionView } from '../../lib/types'
import { DocumentAssistPanel } from '../ai/DocumentAssistPanel'
import { DocumentStatusPill } from '../applications/status'
import { OCR_STATUS, TEXT_SOURCE } from './fieldMeta'
import { FieldList } from './FieldList'
import { PageViewer } from './PageViewer'

const IN_FLIGHT = new Set(['queued', 'processing'])

function PageTextPanel({ applicationId, documentId, page }: { applicationId: string; documentId: string; page: number }) {
  const [mode, setMode] = useState<'normalized' | 'raw'>('normalized')
  const q = useQuery({ queryKey: ['page-text', documentId, page], queryFn: () => api.pageText(applicationId, documentId, page) })
  return (
    <Card>
      <CardHeader
        icon={<ScanText className="size-4" />}
        title={`Page ${page} text`}
        description="Raw text exactly as read. Normalized: whitespace tidied for reading only."
        action={
          <div role="radiogroup" aria-label="Text version" className="inline-flex rounded-lg border border-line-strong p-0.5">
            {(['normalized', 'raw'] as const).map((m) => (
              <button
                key={m}
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className={cn('h-7 rounded-md px-2.5 text-[12px] font-medium capitalize', mode === m ? 'bg-navy-900 text-white' : 'text-ink-muted hover:text-ink')}
              >
                {m}
              </button>
            ))}
          </div>
        }
      />
      {q.isPending ? (
        <LoadingRows rows={2} label="Loading page text" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (q.data[mode === 'raw' ? 'raw_text' : 'normalized_text'] || '').length === 0 ? (
        <p className="p-5 text-[13px] text-ink-muted">No text was read from this page.</p>
      ) : (
        <pre className="max-h-72 overflow-auto p-5 font-mono text-[12px] leading-5 whitespace-pre-wrap text-ink">
          {mode === 'raw' ? q.data.raw_text : q.data.normalized_text}
        </pre>
      )}
    </Card>
  )
}

function QualityPanel({ view, page }: { view: ExtractionView; page: number }) {
  const p = view.pages.find((x) => x.page_number === page)
  const attention = view.run.summary.pages_needing_attention ?? []
  return (
    <div className="space-y-2">
      {view.run.status === 'partial' && (
        <p role="status" className="flex gap-2 rounded-lg bg-review-bg px-3 py-2 text-[13px] text-review">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          Partial extraction: page(s) {(view.run.summary.pages_without_text ?? []).join(', ')} had no readable text. Values on those pages are reported as missing, not absent.
        </p>
      )}
      {p && (
        <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="text-ink-subtle">Page {page}:</span>
          <StatusPill status={p.text_source === 'none' ? 'missing' : 'pass'}>{TEXT_SOURCE[p.text_source]}</StatusPill>
          <StatusPill status={OCR_STATUS[p.ocr_status].pill}>{OCR_STATUS[p.ocr_status].label}</StatusPill>
          {p.ocr_confidence != null && <span className="text-ink-muted">OCR confidence {Math.round(p.ocr_confidence)}/100</span>}
          {p.rotation !== 0 && <span className="text-ink-muted">Rotated {p.rotation}°</span>}
        </div>
      )}
      {p?.warnings.map((w) => (
        <p key={w.code} className="flex gap-2 rounded-lg border border-review/30 bg-review-bg/50 px-3 py-2 text-[12.5px] text-ink">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-review" aria-hidden />
          {w.message}
        </p>
      ))}
      {attention.length > 0 && !attention.every((n) => n === page) && (
        <p className="text-[12px] text-ink-muted">Other pages needing attention: {attention.filter((n) => n !== page).join(', ')}</p>
      )}
    </div>
  )
}

export function ExtractionInspectorPage() {
  const { id = '', docId = '' } = useParams()
  const qc = useQueryClient()
  const doc = useQuery({
    queryKey: ['document', docId, 'inspector'],
    queryFn: () => api.document(id, docId),
    refetchInterval: (q) => (q.state.data && IN_FLIGHT.has(q.state.data.status) ? 2000 : false),
  })
  const app = useQuery({ queryKey: ['application', id], queryFn: () => api.application(id) })
  const processing = !!doc.data && IN_FLIGHT.has(doc.data.status)
  const view = useQuery({
    queryKey: ['extraction', docId],
    queryFn: () => api.extraction(id, docId),
    retry: false,
    refetchInterval: processing ? 2000 : false,
  })
  // Deep links (e.g. from evidence findings): ?page=2&field=date_of_birth
  const [search] = useSearchParams()
  const [page, setPage] = useState(() => Math.max(1, Number(search.get('page')) || 1))
  const [selected, setSelected] = useState<string | null>(() => search.get('field'))
  const [actionError, setActionError] = useState<string | null>(null)

  useBreadcrumbTrail(
    app.data && doc.data ? [{ label: app.data.reference, to: `/applications/${id}` }, { label: doc.data.original_filename }] : undefined,
  )

  // Refresh the extraction once processing settles.
  const wasProcessing = useRef(processing)
  useEffect(() => {
    if (wasProcessing.current && !processing) {
      qc.invalidateQueries({ queryKey: ['extraction', docId] })
      qc.invalidateQueries({ queryKey: ['page-image', docId] })
      qc.invalidateQueries({ queryKey: ['page-text', docId] })
    }
    wasProcessing.current = processing
  }, [processing, qc, docId])

  const afterQueue = () => {
    setActionError(null)
    qc.invalidateQueries({ queryKey: ['document', docId] })
    qc.invalidateQueries({ queryKey: ['documents', id] })
    qc.invalidateQueries({ queryKey: ['application', id] })
  }
  const reprocess = useMutation({ mutationFn: (force: boolean) => api.reprocessDocument(id, docId, force), onSuccess: afterQueue, onError: (e) => setActionError(errorMessage(e)) })
  const retry = useMutation({ mutationFn: () => api.retryDocument(id, docId), onSuccess: afterQueue, onError: (e) => setActionError(errorMessage(e)) })

  if (doc.isPending) return <LoadingRows rows={6} label="Loading document" />
  if (doc.isError) {
    if (doc.error instanceof ApiError && doc.error.status === 404) {
      return (
        <EmptyState icon={<FileSearch className="size-6" />} title="Document not found" action={<Link to={`/applications/${id}`} className="text-sm font-medium text-violet-700 hover:underline">Back to the application</Link>}>
          It doesn’t exist, or you don’t have access to it.
        </EmptyState>
      )
    }
    return <ErrorState error={doc.error} onRetry={() => doc.refetch()} />
  }

  const d = doc.data
  const notExtracted = view.isError && view.error instanceof ApiError && view.error.code === 'not_extracted'
  const v = view.data

  return (
    <PageContainer
      eyebrow={app.data?.reference ?? 'Document'}
      title={d.original_filename}
      documentTitle={`Inspect ${d.original_filename}`}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <DocumentStatusPill status={d.status} />
          <span>
            {d.detected_mime} · SHA-256 <span className="font-mono" title={d.sha256}>{shortHash(d.sha256, 12)}</span>
          </span>
        </span>
      }
      actions={
        <>
          {d.can_retry && (
            <Button size="sm" loading={retry.isPending} icon={<RotateCw className="size-3.5" aria-hidden />} onClick={() => retry.mutate()}>
              Retry processing
            </Button>
          )}
          {(v?.can_reprocess || (notExtracted && app.data?.permissions.can_edit && !processing)) && (
            <>
              <Button size="sm" variant="secondary" loading={reprocess.isPending && reprocess.variables === false} icon={<RefreshCw className="size-3.5" aria-hidden />} onClick={() => reprocess.mutate(false)}>
                Reprocess
              </Button>
              <Button size="sm" variant="ghost" loading={reprocess.isPending && reprocess.variables === true} onClick={() => reprocess.mutate(true)}>
                Force re-extract
              </Button>
            </>
          )}
        </>
      }
    >
      {actionError && (
        <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
          {actionError}
        </p>
      )}
      {processing && (
        <p role="status" className="flex items-center gap-2 rounded-xl border border-info/20 bg-info-bg px-4 py-3 text-[13px] text-info">
          <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Processing. Results will appear when inspection and extraction finish.
        </p>
      )}

      {view.isPending ? (
        <LoadingRows rows={6} label="Loading extraction" />
      ) : notExtracted ? (
        <Card>
          <EmptyState icon={<ScanText className="size-6" />} title={processing ? 'Extraction in progress' : 'Not extracted yet'}>
            {processing
              ? 'This page updates automatically.'
              : d.status === 'failed'
                ? 'Processing failed before extraction. Use “Retry processing”.'
                : 'This document was processed before extraction existed, or its results were superseded. Use “Reprocess” to extract it.'}
          </EmptyState>
        </Card>
      ) : view.isError ? (
        <ErrorState error={view.error} onRetry={() => view.refetch()} />
      ) : (
        v && (
          <>
            <div className="flex gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-muted">
              {v.extractor.kind === 'ai' ? <Bot className="mt-0.5 size-4 shrink-0 text-violet-400" aria-hidden /> : <Info className="mt-0.5 size-4 shrink-0 text-violet-400" aria-hidden />}
              <div>
                <p className="font-medium text-ink">
                  {v.extractor.name} {v.extractor.version} · run {formatDateTime(v.run.finished_at)} · OCR engine: {v.run.ocr_engine === 'none' ? 'not available' : v.run.ocr_engine}
                </p>
                <p>{v.extractor.limitations}</p>
              </div>
            </div>
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-4">
                <QualityPanel view={v} page={page} />
                <PageViewer
                  applicationId={id}
                  documentId={docId}
                  pages={v.pages}
                  page={page}
                  onPage={setPage}
                  fields={v.fields}
                  selectedKey={selected}
                  onSelect={setSelected}
                />
                <PageTextPanel applicationId={id} documentId={docId} page={page} />
              </div>
              <div className="min-w-0 space-y-4">
                <Card>
                  <CardHeader
                    title="Extracted fields"
                    description={`${v.run.summary.fields?.found ?? 0} found · ${v.run.summary.fields?.missing ?? 0} missing · ${(v.run.summary.fields?.invalid ?? 0) + (v.run.summary.fields?.ambiguous ?? 0)} need checking`}
                  />
                  <div className="p-4">
                    <FieldList
                      fields={v.fields}
                      applicationId={id}
                      documentId={docId}
                      selectedKey={selected}
                      onSelect={setSelected}
                      onGoToPage={setPage}
                      canCorrect={v.can_correct}
                    />
                  </div>
                </Card>
                <DocumentAssistPanel
                  applicationId={id}
                  documentId={docId}
                  onShowField={(key, p) => {
                    setSelected(key)
                    setPage(p)
                  }}
                />
              </div>
            </div>
          </>
        )
      )}
    </PageContainer>
  )
}
