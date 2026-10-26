import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, api, errorMessage, onSessionExpiry, onUnauthorized } from '../../lib/api'
import type { Me, Permission } from '../../lib/types'

/** Show the "about to expire" warning this long before the session ends. */
const EXPIRY_WARNING_MS = 2 * 60_000

export type SessionEnd = 'expired' | 'signed_out' | 'signed_out_offline' | null

interface AuthState {
  user: Me | null
  status: 'loading' | 'authenticated' | 'anonymous'
  /** Why the last session ended, for the login screen. */
  sessionEnd: SessionEnd
  /** When the server will end the session if there is no further activity. */
  expiresAt: Date | null
  expiringSoon: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Any authenticated request slides the idle window; used by "Stay signed in". */
  extendSession: () => Promise<void>
  can: (p: Permission) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

const sessionExpiry = (me: Me) => new Date(Math.min(Date.parse(me.session.idle_expires_at), Date.parse(me.session.expires_at)))

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [user, setUser] = useState<Me | null>(null)
  const [status, setStatus] = useState<AuthState['status']>('loading')
  const [sessionEnd, setSessionEnd] = useState<SessionEnd>(null)
  const [expiresAt, setExpiresAt] = useState<Date | null>(null)
  const [expiringSoon, setExpiringSoon] = useState(false)
  const statusRef = useRef(status)
  statusRef.current = status

  const endLocally = useCallback(
    (reason: SessionEnd) => {
      setUser(null)
      setStatus('anonymous')
      setExpiresAt(null)
      setExpiringSoon(false)
      setSessionEnd(reason)
      qc.clear()
    },
    [qc],
  )

  // Restore an existing session (the HttpOnly cookie survives reloads).
  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setExpiresAt(sessionExpiry(me))
        setStatus('authenticated')
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (!(e instanceof ApiError && e.status === 401)) console.warn('Session check failed:', errorMessage(e))
        setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Any 401 while signed in means the server ended the session (expiry, revocation, deactivation).
  useEffect(() => onUnauthorized(() => statusRef.current === 'authenticated' && endLocally('expired')), [endLocally])

  // Every authenticated response reports the slid expiry.
  useEffect(
    () =>
      onSessionExpiry((iso) => {
        const d = new Date(iso)
        if (!Number.isNaN(d.getTime())) setExpiresAt(d)
      }),
    [],
  )

  // Warn shortly before expiry; at expiry, confirm with the server (which answers 401 → expired).
  useEffect(() => {
    if (status !== 'authenticated' || !expiresAt) return
    const now = Date.now()
    const untilWarn = expiresAt.getTime() - EXPIRY_WARNING_MS - now
    const untilEnd = expiresAt.getTime() - now + 1000
    setExpiringSoon(untilWarn <= 0)
    const warn = untilWarn > 0 ? window.setTimeout(() => setExpiringSoon(true), untilWarn) : undefined
    const end = window.setTimeout(() => {
      api.me().catch(() => undefined) // a 401 here triggers onUnauthorized → 'expired'
    }, Math.max(untilEnd, 0))
    return () => {
      window.clearTimeout(warn)
      window.clearTimeout(end)
    }
  }, [status, expiresAt])

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.login(email, password)
      qc.clear()
      setUser(res.user)
      setExpiresAt(sessionExpiry(res.user))
      setSessionEnd(null)
      setStatus('authenticated')
    },
    [qc],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
      endLocally('signed_out')
    } catch (e) {
      // The server session could not be revoked (e.g. offline). It still expires on its own,
      // and the login screen says so rather than pretending the sign-out completed.
      console.warn('Server sign-out failed:', errorMessage(e))
      endLocally(e instanceof ApiError && e.status === 401 ? 'signed_out' : 'signed_out_offline')
    }
  }, [endLocally])

  const extendSession = useCallback(async () => {
    const me = await api.me()
    setUser(me)
    setExpiresAt(sessionExpiry(me))
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      status,
      sessionEnd,
      expiresAt,
      expiringSoon,
      login,
      logout,
      extendSession,
      can: (p) => !!user?.permissions.includes(p),
    }),
    [user, status, sessionEnd, expiresAt, expiringSoon, login, logout, extendSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
