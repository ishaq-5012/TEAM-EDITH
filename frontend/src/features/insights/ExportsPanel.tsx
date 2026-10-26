import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, Lock, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card, CardHeader } from '../../components/ui/Card'
import { ErrorState, LoadingRows } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, downloadExport, errorMessage, type ExportDownload } from '../../lib/api'
import type { ExportDataset } from '../../lib/types'
import { useInsightsWindow } from './insightsMeta'
import { WindowFilters } from './WindowFilters'
import { controlClass } from '../../components/ui/controlClass'

function save(file: ExportDownload) {
  const url = URL.createObjectURL(file.blob)
  const a = document.createElement('a')
  a.href = url
  a.download = file.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Authorized CSV/JSON exports. The server checks permissions, scopes the rows and records every export. */
export function ExportsPanel() {
  const q = useQuery({ queryKey: ['export-datasets'], queryFn: api.exportDatasets })
  return (
    <div className="space-y-5">
      <WindowFilters />
      <p className="text-[12.5px] text-ink-muted">
        Exports use the window and scope above, include only applications you can see, and are recorded in the audit history with a SHA-256 of the
        file. Raw page text and stored files are never exported.
      </p>
      {q.isPending ? (
        <LoadingRows rows={4} label="Loading export datasets" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {q.data.map((d) => (
            <DatasetCard key={d.key} d={d} />
          ))}
        </div>
      )}
    </div>
  )
}

function DatasetCard({ d }: { d: ExportDataset }) {
  const w = useInsightsWindow()
  const [format, setFormat] = useState<'csv' | 'json'>('csv')
  const [values, setValues] = useState(false)
  const [reason, setReason] = useState('')
  const [done, setDone] = useState<ExportDownload | null>(null)
  const sensitive = d.sensitive || (d.key === 'audit_events' && values)
  const reasonOk = !sensitive || reason.trim().length >= 10
  const run = useMutation({
    mutationFn: () =>
      downloadExport({
        dataset: d.key,
        format,
        date_from: w.query.from,
        date_to: w.query.to,
        application_type: w.query.application_type,
        include_synthetic: w.query.include_synthetic,
        include_document_values: sensitive ? true : undefined,
        reason: sensitive ? reason.trim() : undefined,
      }),
    onSuccess: (file) => {
      setDone(file)
      save(file)
    },
  })
  const canOfferValues = d.key === 'audit_events' && d.can_include_document_values
  return (
    <Card>
      <CardHeader
        icon={d.sensitive ? <ShieldAlert className="size-4" /> : <Download className="size-4" />}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {d.label} {d.sensitive && <StatusPill status="review">Contains document values</StatusPill>}
          </span>
        }
        description={d.description}
      />
      <div className="space-y-3 p-4 text-[13px]">
        {!d.allowed ? (
          <p className="flex items-center gap-2 text-ink-muted">
            <Lock className="size-4 text-ink-subtle" aria-hidden /> Your role can’t export this dataset (needs {d.requires.join(' and ')}).
          </p>
        ) : (
          <>
            <fieldset className="flex items-center gap-3">
              <legend className="sr-only">Format for {d.label}</legend>
              {(['csv', 'json'] as const).map((f) => (
                <label key={f} className="flex items-center gap-1.5">
                  <input type="radio" name={`format-${d.key}`} value={f} checked={format === f} onChange={() => setFormat(f)} className="accent-violet-600" />
                  {f.toUpperCase()}
                </label>
              ))}
            </fieldset>
            {canOfferValues && (
              <label className="flex items-start gap-2 text-[12.5px] text-ink-muted">
                <input type="checkbox" checked={values} onChange={(e) => setValues(e.target.checked)} className="mt-0.5 size-4 accent-violet-600" />
                Include event data (can contain before/after values from documents)
              </label>
            )}
            {sensitive && (
              <label className="block text-[12.5px] text-ink-muted">
                Reason for exporting document values (recorded in the audit history)
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  maxLength={500}
                  className={`mt-1 ${controlClass({ size: 'sm', multiline: true })}`}
                  aria-describedby={`reason-help-${d.key}`}
                />
                <span id={`reason-help-${d.key}`} className="text-[11.5px] text-ink-subtle">
                  At least 10 characters.
                </span>
              </label>
            )}
            <Button size="sm" loading={run.isPending} disabled={!reasonOk} disabledReason="Enter a reason of at least 10 characters. It is recorded with the export." icon={<Download className="size-3.5" aria-hidden />} onClick={() => run.mutate()}>
              Export {format.toUpperCase()}
            </Button>
            {run.isError && (
              <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[12.5px] text-fail">
                {errorMessage(run.error)}
              </p>
            )}
            {done && !run.isPending && (
              <p role="status" className="text-[12.5px] text-ink-muted">
                Downloaded {done.filename}: {done.rows} row{done.rows === 1 ? '' : 's'}
                {done.truncated ? ' (truncated at the 50,000-row limit; narrow the window)' : ''}. Recorded in the audit history.
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  )
}
