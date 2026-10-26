import { AlertOctagon, CheckCircle2, Info, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'
import { notice } from '../../lib/motion'
import { cn } from './cn'

type Tone = 'success' | 'error' | 'info'

const tones: Record<Tone, { cls: string; icon: ReactNode; role: 'status' | 'alert' }> = {
  success: { cls: 'border-pass/20 bg-pass-bg/70 text-pass', icon: <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />, role: 'status' },
  error: { cls: 'border-fail/20 bg-fail-bg/70 text-fail', icon: <AlertOctagon className="mt-0.5 size-4 shrink-0" aria-hidden />, role: 'alert' },
  info: { cls: 'border-info/20 bg-info-bg/70 text-info', icon: <Info className="mt-0.5 size-4 shrink-0" aria-hidden />, role: 'status' },
}

/**
 * Inline outcome of an action the user just took (saved, recorded, failed). Success and info are announced
 * politely, errors assertively. Wrap in <NoticeSlot> to animate it in and out.
 */
export function Notice({ tone, title, children, onDismiss, className }: { tone: Tone; title: ReactNode; children?: ReactNode; onDismiss?: () => void; className?: string }) {
  const t = tones[tone]
  return (
    <motion.div
      role={t.role}
      variants={notice}
      initial="initial"
      animate="animate"
      exit="exit"
      layout="position"
      className={cn('flex items-start gap-2 rounded-xl border px-4 py-2.5 text-[13px]', t.cls, className)}
    >
      {t.icon}
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children && <div className="text-ink-muted">{children}</div>}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="rounded p-0.5 text-ink-subtle transition-colors hover:bg-white/10 hover:text-ink" aria-label="Dismiss message">
          <X className="size-3.5" aria-hidden />
        </button>
      )}
    </motion.div>
  )
}

export function NoticeSlot({ children }: { children: ReactNode }) {
  return <AnimatePresence initial={false}>{children}</AnimatePresence>
}
