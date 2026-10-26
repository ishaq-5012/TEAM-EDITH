import { AnimatePresence, motion } from 'motion/react'
import { cloneElement, isValidElement, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { DURATION } from '../../lib/motion'
import { cn } from './cn'

/**
 * Accessible tooltip: opens on hover (after a short delay) and on keyboard focus, closes on Escape, blur or
 * pointer leave, and is linked to its trigger with aria-describedby so screen readers announce it. The trigger must
 * be focusable; for a disabled action use Button's `disabledReason`, which keeps the button focusable.
 * Supplementary only: never put the sole copy of essential information in a tooltip.
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: {
  content: ReactNode
  children: ReactElement<{ 'aria-describedby'?: string }>
  side?: 'top' | 'bottom'
  className?: string
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  const show = (delay: number) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), delay)
  }
  const hide = () => {
    window.clearTimeout(timer.current)
    setOpen(false)
  }
  if (!isValidElement(children)) return children
  if (!content) {
    // Same wrapper element as the open state so the child keeps its identity when content appears or goes away.
    return <span className={cn('relative inline-flex', className)}>{children}</span>
  }
  const describedBy = [children.props['aria-describedby'], id].filter(Boolean).join(' ')
  return (
    <span
      className={cn('relative inline-flex', className)}
      onPointerEnter={() => show(300)}
      onPointerLeave={hide}
      onFocus={() => show(0)}
      onBlur={hide}
    >
      {cloneElement(children, { 'aria-describedby': describedBy })}
      {/* Always in the DOM (visually hidden when closed) so aria-describedby resolves for screen readers. */}
      <span id={id} className="sr-only">
        {content}
      </span>
      <AnimatePresence>
        {open && (
          <motion.span
            role="tooltip"
            aria-hidden
            initial={{ opacity: 0, y: side === 'top' ? 2 : -2 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.fast }}
            className={cn(
              'pointer-events-none absolute left-1/2 z-50 w-max max-w-64 -translate-x-1/2 rounded-lg bg-navy-900 px-2.5 py-1.5 text-left text-[12px] leading-[1.45] font-normal text-white shadow-[var(--shadow-raised)]',
              side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
            )}
          >
            {content}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}
