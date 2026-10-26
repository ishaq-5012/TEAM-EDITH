import type { ReactNode } from 'react'
import { cn } from '../ui/cn'
import { useTilt } from './useTilt'

/**
 * A tilt-surface wrapper for cards whose own element already animates `transform` (motion entrances,
 * layout animations): the wrapper tilts, the motion element inside keeps its transform.
 */
export function Tilt({ className, max, lift, children }: { className?: string; max?: number; lift?: number; children: ReactNode }) {
  const ref = useTilt<HTMLDivElement>({ max, lift })
  return (
    <div ref={ref} className={cn('tilt-surface', className)}>
      {children}
    </div>
  )
}
