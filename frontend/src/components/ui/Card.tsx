import type { HTMLAttributes, ReactNode } from 'react'
import { useTilt } from '../fx/useTilt'
import { cn } from './cn'

/** Surface for grouped content: a metallic edge, layered 3D shadow, and a tilt toward the pointer. */
export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ref = useTilt<HTMLDivElement>()
  return (
    <div
      ref={ref}
      className={cn('tilt-surface metal rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]', className)}
      {...rest}
    />
  )
}

export function CardHeader({
  title,
  description,
  action,
  icon,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span
            className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] text-white shadow-[0_0_16px_-4px_rgb(255_79_216/0.7),0_1px_0_rgb(255_255_255/0.4)_inset,0_6px_14px_-6px_rgb(109_68_236/0.8)]"
            aria-hidden
          >
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] leading-5 text-ink-muted">{description}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
