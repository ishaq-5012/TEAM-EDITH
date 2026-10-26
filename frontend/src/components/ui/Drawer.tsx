import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { DURATION, spring } from '../../lib/motion'
import { useFocusTrap } from '../../lib/useFocusTrap'

/**
 * Side sheet for detail that needs room (evidence, comparisons). Slides in from the right on wide screens and up
 * from the bottom on phones. Same accessibility contract as Dialog: focus trap, Escape, focus restored on close.
 */
export function Drawer({
  open,
  onClose,
  title,
  eyebrow,
  icon,
  children,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  eyebrow?: ReactNode
  icon?: ReactNode
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useFocusTrap(panel, open, onClose)

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-end sm:items-stretch">
          <motion.div
            className="absolute inset-0 bg-navy-950/50 backdrop-blur-[3px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className="relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-canvas shadow-[var(--shadow-raised)] outline-none sm:max-h-none sm:w-[min(760px,92vw)] sm:rounded-none sm:rounded-l-3xl"
            initial={{ x: '8%', opacity: 0 }}
            animate={{ x: 0, opacity: 1, transition: spring }}
            exit={{ x: '6%', opacity: 0, transition: { duration: DURATION.fast } }}
          >
            <header className="hero-surface flex shrink-0 items-start justify-between gap-4 px-6 py-5">
              <div className="flex min-w-0 items-start gap-3">
                {icon && <span className="glass grid size-10 shrink-0 place-items-center rounded-xl text-white">{icon}</span>}
                <div className="min-w-0">
                  {eyebrow && <p className="text-[11px] font-semibold tracking-[0.14em] text-cyan-400 uppercase">{eyebrow}</p>}
                  <h2 id={titleId} className="text-lg font-semibold tracking-[-0.01em] text-white">
                    {title}
                  </h2>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="glass rounded-lg p-1.5 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
                aria-label="Close panel"
              >
                <X className="size-4" aria-hidden />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
