import { AlertOctagon, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { errorMessage } from '../../lib/api'
import { Button } from './Button'
import { cn } from './cn'

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton h-4', className)} aria-hidden />
}

export function LoadingRows({ rows = 4, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3 p-5">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        </div>
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon: ReactNode
  title: string
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center px-6 py-12 text-center', className)}>
      <div className="relative mb-4 grid size-14 place-items-center rounded-2xl bg-gradient-to-b from-violet-50 to-navy-50 text-violet-400 ring-1 ring-violet-100" aria-hidden>
        {icon}
      </div>
      <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
      {children && <div className="mt-1.5 max-w-md text-sm leading-6 text-ink-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  return (
    <div role="alert" className={cn('flex items-start gap-3 rounded-xl border border-fail/20 bg-fail-bg/60 text-sm', compact ? 'm-0 p-3' : 'm-5 p-4')}>
      <AlertOctagon className="mt-0.5 size-4 shrink-0 text-fail" aria-hidden />
      <div className="flex-1">
        <p className="font-medium text-fail">Couldn’t load this</p>
        <p className="mt-0.5 text-ink-muted">{errorMessage(error)}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} icon={<RotateCw className="size-3.5" aria-hidden />}>
          Retry
        </Button>
      )}
    </div>
  )
}
