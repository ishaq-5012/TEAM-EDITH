import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '../../components/ui/Button'

export function Pager({ total, limit, offset, onChange, label }: { total: number; limit: number; offset: number; onChange: (offset: number) => void; label: string }) {
  if (total <= limit && offset === 0) return null
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)
  return (
    <nav aria-label={label} className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-[12.5px] text-ink-muted">
      <span className="tabular">
        {from}–{to} of {total}
      </span>
      <span className="flex gap-1.5">
        <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))} icon={<ChevronLeft className="size-3.5" aria-hidden />}>
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={to >= total} onClick={() => onChange(offset + limit)}>
          Next <ChevronRight className="size-3.5" aria-hidden />
        </Button>
      </span>
    </nav>
  )
}
