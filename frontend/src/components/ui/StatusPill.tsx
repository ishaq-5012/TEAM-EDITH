import { AlertTriangle, CheckCircle2, CircleDashed, HelpCircle, Info, XCircle } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'
import { cn } from './cn'

/**
 * Verification status vocabulary used across every module. Each state has a distinct
 * icon and text label so meaning never depends on colour alone.
 */
export type Status = 'pass' | 'fail' | 'review' | 'missing' | 'info' | 'unknown'

const styles: Record<Status, { cls: string; icon: ReactNode }> = {
  pass: { cls: 'bg-pass-bg text-pass', icon: <CheckCircle2 className="size-3.5" aria-hidden /> },
  fail: { cls: 'bg-fail-bg text-fail', icon: <XCircle className="size-3.5" aria-hidden /> },
  review: { cls: 'bg-review-bg text-review', icon: <AlertTriangle className="size-3.5" aria-hidden /> },
  missing: { cls: 'bg-missing-bg text-missing', icon: <CircleDashed className="size-3.5" aria-hidden /> },
  info: { cls: 'bg-info-bg text-info', icon: <Info className="size-3.5" aria-hidden /> },
  unknown: { cls: 'bg-missing-bg text-missing', icon: <HelpCircle className="size-3.5" aria-hidden /> },
}

export function StatusPill({
  status,
  children,
  className,
  icon,
}: {
  status: Status
  children: ReactNode
  className?: string
  /** Overrides the default status icon (e.g. a spinner for in-progress work). */
  icon?: ReactNode
}) {
  const reduce = useReducedMotion()
  const s = styles[status]
  return (
    <motion.span
      key={status}
      initial={reduce ? false : { scale: 0.92, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap', s.cls, className)}
    >
      {icon ?? s.icon}
      {children}
    </motion.span>
  )
}
