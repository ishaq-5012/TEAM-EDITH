import { cn } from '../../components/ui/cn'

/** Compact, monospace rendering of an audit action with its outcome. */
export function ActionLabel({ action, outcome }: { action: string; outcome: string }) {
  const failed = outcome !== 'success'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[11.5px] font-medium',
        failed ? 'bg-fail-bg text-fail' : 'bg-navy-50 text-ink',
      )}
    >
      <span className={cn('size-1.5 rounded-full', failed ? 'bg-fail' : 'bg-violet-500')} aria-hidden />
      {action}
      {failed && <span className="sr-only">(failed)</span>}
    </span>
  )
}
