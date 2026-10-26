import { Clock } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { errorMessage } from '../../lib/api'
import { useAuth } from './AuthProvider'

function useCountdown(target: Date | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!target) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [target])
  return target ? Math.max(0, Math.round((target.getTime() - now) / 1000)) : 0
}

/** Warns before the idle timeout ends the session; the user can extend or sign out. */
export function SessionExpiryBanner() {
  const { expiringSoon, expiresAt, extendSession, logout } = useAuth()
  const reduce = useReducedMotion()
  const seconds = useCountdown(expiringSoon ? expiresAt : null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const stay = async () => {
    setBusy(true)
    setError(null)
    try {
      await extendSession()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const mm = Math.floor(seconds / 60)
  const ss = String(seconds % 60).padStart(2, '0')

  return (
    <AnimatePresence>
      {expiringSoon && (
        <motion.div
          role="alertdialog"
          aria-live="assertive"
          aria-labelledby="session-expiry-title"
          initial={reduce ? { opacity: 0 } : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, y: 24 }}
          className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-xl flex-col gap-3 rounded-2xl bg-navy-950 p-4 text-white shadow-[var(--shadow-raised)] sm:flex-row sm:items-center"
        >
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white/10" aria-hidden>
            <Clock className="size-5 text-violet-400" />
          </span>
          <div className="flex-1">
            <p id="session-expiry-title" className="text-sm font-semibold">
              Your session is about to end
            </p>
            <p className="text-[13px] text-white/70">
              You’ll be signed out for inactivity in <span className="tabular font-mono">{mm}:{ss}</span>.
              {error && <span className="block text-rose-300">{error}</span>}
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" className="text-white/80 hover:bg-white/10 hover:text-white" onClick={() => void logout()}>
              Sign out
            </Button>
            <Button size="sm" loading={busy} onClick={() => void stay()}>
              Stay signed in
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
