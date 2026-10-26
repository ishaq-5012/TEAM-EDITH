import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FileSearch, History, MapPin, PenLine } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { cn } from '../../components/ui/cn'
import { Dialog } from '../../components/ui/Dialog'
import { controlClass } from '../../components/ui/controlClass'
import { TextField } from '../../components/ui/Field'
import { StatusPill } from '../../components/ui/StatusPill'
import { api, errorMessage } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { FieldOut } from '../../lib/types'
import { FIELD_STATUS, FLAG_LABELS, METHOD_LABELS, VALUE_HINTS } from './fieldMeta'

const schema = z.object({
  value: z.string().trim().min(1, 'Enter a value').max(2000),
  reason: z.string().trim().min(3, 'Give a reason (at least 3 characters)').max(500),
})
type Values = z.infer<typeof schema>

function CorrectionDialog({ field, applicationId, documentId, onClose }: { field: FieldOut; applicationId: string; documentId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { value: field.effective_value ?? '', reason: '' } })
  const m = useMutation({
    mutationFn: (v: Values) => api.correctField(applicationId, documentId, field.id, v.value, v.reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['extraction', documentId] })
      onClose()
    },
    onError: (e) => setError(errorMessage(e)),
  })
  const multiline = field.field_type === 'address'
  return (
    <Dialog open onClose={onClose} title={`Correct ${field.label}`} description="The extracted value is kept unchanged; your correction is recorded alongside it with your name and reason.">
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit((v) => {
          setError(null)
          m.mutate(v)
        })}
      >
        <div className="rounded-lg bg-navy-50 px-3 py-2 text-[12.5px]">
          <span className="text-ink-subtle">Extracted (raw): </span>
          <span className="font-mono whitespace-pre-wrap">{field.raw_value ?? '— not found —'}</span>
        </div>
        {multiline ? (
          <div className="space-y-1.5">
            <label htmlFor="correction-value" className="block text-[13px] font-medium">
              Correct value
            </label>
            <textarea id="correction-value" rows={4} className={controlClass({ multiline: true })} {...form.register('value')} />
            <p className="text-xs text-ink-subtle">{VALUE_HINTS[field.field_type]}</p>
            {form.formState.errors.value && <p className="text-xs font-medium text-fail">{form.formState.errors.value.message}</p>}
          </div>
        ) : (
          <TextField label="Correct value" hint={VALUE_HINTS[field.field_type]} error={form.formState.errors.value?.message} {...form.register('value')} />
        )}
        <TextField label="Reason" hint="Recorded in the audit trail." error={form.formState.errors.reason?.message} {...form.register('reason')} />
        {error && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-[13px] text-fail">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={m.isPending}>
            Save correction
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function Mono({ children, empty = '—' }: { children: string | null; empty?: string }) {
  return children == null ? <span className="text-ink-subtle">{empty}</span> : <span className="font-mono text-[12.5px] break-words whitespace-pre-wrap">{children}</span>
}

function FieldCard({
  field,
  selected,
  onSelect,
  onGoToPage,
  canCorrect,
  onCorrect,
}: {
  field: FieldOut
  selected: boolean
  onSelect: () => void
  onGoToPage: (page: number) => void
  canCorrect: boolean
  onCorrect: () => void
}) {
  const reduce = useReducedMotion()
  const [open, setOpen] = useState(false)
  const s = FIELD_STATUS[field.status]
  const corrected = field.effective_source === 'correction'
  return (
    <li className={cn('rounded-xl border bg-surface transition-colors', selected ? 'border-violet-500 shadow-[0_0_0_3px_rgb(129_96_245/0.15)]' : 'border-line')}>
      <div className="flex items-start gap-3 p-3.5">
        <button onClick={onSelect} className="min-w-0 flex-1 text-left" aria-pressed={selected} aria-label={`Select ${field.label}`}>
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold text-ink">{field.label}</span>
            <StatusPill status={s.pill}>{s.label}</StatusPill>
            {corrected && <StatusPill status="info">Corrected</StatusPill>}
          </span>
          <span className={cn('mt-1 block text-[14px] break-words whitespace-pre-wrap', field.effective_value ? 'text-ink' : 'text-ink-subtle italic')}>
            {field.effective_value ?? (field.status === 'missing' ? 'Not found' : 'No valid value')}
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          {field.page_number && (
            <Button size="sm" variant="ghost" onClick={() => onGoToPage(field.page_number!)} aria-label={`Show ${field.label} on page ${field.page_number}`} icon={<MapPin className="size-3.5" aria-hidden />}>
              p.{field.page_number}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} details for ${field.label}`}>
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
          </Button>
        </div>
      </div>
      {(field.quality_flags.length > 0 || field.normalization_note || field.correction_based_on_other_value) && (
        <ul className="flex flex-wrap gap-1.5 px-3.5 pb-3">
          {field.correction_based_on_other_value && (
            <li className="rounded-md bg-review-bg px-2 py-0.5 text-[11.5px] text-review">The correction was made against a different extracted value</li>
          )}
          {field.normalization_note && <li className="rounded-md bg-navy-50 px-2 py-0.5 text-[11.5px] text-ink-muted">{field.normalization_note}</li>}
          {field.quality_flags
            .filter((f) => f !== 'ocr_source')
            .map((f) => (
              <li key={f} className="rounded-md bg-review-bg px-2 py-0.5 text-[11.5px] text-review">
                {FLAG_LABELS[f] ?? f}
              </li>
            ))}
        </ul>
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reduce ? { opacity: 1 } : { height: 'auto', opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="space-y-3 border-t border-line px-3.5 py-3 text-[12.5px]">
              <table className="w-full text-left">
                <caption className="sr-only">Raw and normalized values for {field.label}</caption>
                <tbody className="align-top">
                  <tr>
                    <th scope="row" className="w-28 py-1 pr-3 font-medium text-ink-subtle">
                      Raw (source)
                    </th>
                    <td className="py-1">
                      <Mono empty="— not found —">{field.raw_value}</Mono>
                    </td>
                  </tr>
                  <tr>
                    <th scope="row" className="py-1 pr-3 font-medium text-ink-subtle">
                      Normalized
                    </th>
                    <td className="py-1">
                      <Mono>{field.normalized_value}</Mono>
                    </td>
                  </tr>
                  {corrected && (
                    <tr>
                      <th scope="row" className="py-1 pr-3 font-medium text-ink-subtle">
                        Corrected
                      </th>
                      <td className="py-1">
                        <Mono>{field.effective_value}</Mono>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <dl className="grid grid-cols-[112px_1fr] gap-x-3 gap-y-1 text-ink-muted">
                <dt className="text-ink-subtle">Method</dt>
                <dd>{field.method ? METHOD_LABELS[field.method] ?? field.method : '—'}</dd>
                {field.matched_label && (
                  <>
                    <dt className="text-ink-subtle">Matched label</dt>
                    <dd>“{field.matched_label}”</dd>
                  </>
                )}
                <dt className="text-ink-subtle">Score</dt>
                <dd>{field.confidence == null ? '—' : `${Math.round(field.confidence * 100)} / 100 (heuristic, not a probability)`}</dd>
                {field.bbox && (
                  <>
                    <dt className="text-ink-subtle">Location</dt>
                    <dd className="font-mono text-[11.5px]">
                      p.{field.page_number} [{field.bbox.map((v) => v.toFixed(1)).join(', ')}]
                    </dd>
                  </>
                )}
              </dl>
              {field.alternatives.length > 0 && (
                <div>
                  <p className="mb-1 font-medium text-ink">Other values found</p>
                  <ul className="space-y-1">
                    {field.alternatives.map((a, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 rounded-md bg-navy-50 px-2 py-1">
                        <Mono>{a.raw_value}</Mono>
                        <Button size="sm" variant="ghost" onClick={() => onGoToPage(a.page_number)}>
                          p.{a.page_number}
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {field.corrections.length > 0 && (
                <div>
                  <p className="mb-1 flex items-center gap-1.5 font-medium text-ink">
                    <History className="size-3.5" aria-hidden /> Correction history
                  </p>
                  <ol className="space-y-1.5">
                    {[...field.corrections].reverse().map((c) => (
                      <li key={c.id} className="rounded-md border border-line px-2 py-1.5">
                        <Mono>{c.normalized_value}</Mono>
                        <p className="mt-0.5 text-[11.5px] text-ink-subtle">
                          {c.actor.full_name} · {formatDateTime(c.created_at)} · “{c.reason}”
                        </p>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {canCorrect && (
                <Button size="sm" variant="secondary" icon={<PenLine className="size-3.5" aria-hidden />} onClick={onCorrect}>
                  {field.status === 'missing' ? 'Enter value' : 'Correct value'}
                </Button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

export function FieldList({
  fields,
  applicationId,
  documentId,
  selectedKey,
  onSelect,
  onGoToPage,
  canCorrect,
}: {
  fields: FieldOut[]
  applicationId: string
  documentId: string
  selectedKey: string | null
  onSelect: (key: string) => void
  onGoToPage: (page: number) => void
  canCorrect: boolean
}) {
  const [correcting, setCorrecting] = useState<FieldOut | null>(null)
  if (fields.length === 0) {
    return (
      <div className="flex flex-col items-center py-10 text-center text-[13px] text-ink-muted">
        <FileSearch className="mb-2 size-6 text-ink-subtle" aria-hidden />
        No fields are configured for this document type.
      </div>
    )
  }
  return (
    <>
      <ul className="space-y-2.5">
        {fields.map((f) => (
          <FieldCard
            key={f.id}
            field={f}
            selected={f.field_key === selectedKey}
            onSelect={() => {
              onSelect(f.field_key)
              if (f.page_number) onGoToPage(f.page_number)
            }}
            onGoToPage={(p) => {
              onSelect(f.field_key)
              onGoToPage(p)
            }}
            canCorrect={canCorrect}
            onCorrect={() => setCorrecting(f)}
          />
        ))}
      </ul>
      {correcting && <CorrectionDialog field={correcting} applicationId={applicationId} documentId={documentId} onClose={() => setCorrecting(null)} />}
    </>
  )
}
