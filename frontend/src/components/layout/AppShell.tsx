import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Suspense, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useOutlet } from 'react-router-dom'
import { useAuth } from '../../features/auth/AuthProvider'
import { SessionExpiryBanner } from '../../features/auth/SessionExpiryBanner'
import { api } from '../../lib/api'
import { DURATION, EASE_OUT, spring } from '../../lib/motion'
import { useFocusTrap } from '../../lib/useFocusTrap'
import { cn } from '../ui/cn'
import { NetworkArt } from '../art/NetworkArt'
import { Scene } from '../fx/Scene'
import { Logo } from './Logo'
import { MODULES } from './modules'
import { Topbar } from './Topbar'

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth()
  return (
    <ul className="space-y-0.5">
      {MODULES.filter((m) => can(m.permission)).map((m) => (
        <li key={m.path}>
          <NavLink
            to={m.path}
            end={m.path === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'group relative flex h-11 items-center gap-2.5 rounded-xl px-2 text-[13px] font-semibold transition-[color,background-color,transform,box-shadow] duration-200',
                isActive
                  ? 'text-white'
                  : 'text-ink-muted hover:translate-x-1 hover:bg-white/[0.07] hover:text-white hover:shadow-[0_0_20px_-8px_rgb(255_153_51/0.6)] motion-reduce:hover:translate-x-0',
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="nav-active"
                    transition={spring}
                    className="absolute inset-0 rounded-xl bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] shadow-[0_1px_0_rgb(255_255_255/0.35)_inset,0_0_22px_-4px_rgb(255_79_216/0.65),0_10px_24px_-10px_rgb(255_153_51/0.7)]"
                  >
                    <span className="absolute inset-y-2.5 right-2 w-1.5 rounded-full bg-white shadow-[0_0_10px_rgb(255_255_255/0.9)]" aria-hidden />
                  </motion.span>
                )}
                <span
                  className={cn(
                    'relative grid size-8 shrink-0 place-items-center rounded-lg transition-colors',
                    isActive
                      ? 'bg-white/20 text-white shadow-[0_1px_0_rgb(255_255_255/0.3)_inset]'
                      : 'bg-white/[0.06] text-[#ffb366] ring-1 ring-white/10 shadow-[0_1px_0_rgb(255_255_255/0.08)_inset] group-hover:text-white group-hover:bg-white/10 group-hover:scale-110 group-hover:rotate-[-6deg] motion-reduce:group-hover:scale-100 motion-reduce:group-hover:rotate-0',
                  )}
                >
                  <m.icon className="size-[17px]" aria-hidden />
                </span>
                <span className="relative truncate" title={m.label}>
                  {m.label}
                </span>
                {m.status === 'planned' && (
                  <span className="relative ml-auto size-1.5 shrink-0 rounded-full bg-navy-100/30" title="Delivered in a later phase">
                    <span className="sr-only">(delivered in a later phase)</span>
                  </span>
                )}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  )
}

function SystemBadge() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000, retry: false })
  const ok = health.data?.status === 'ok'
  const label = health.isPending ? 'Checking backend…' : ok ? 'Backend online' : 'Backend unreachable'
  return (
    <div className="flex items-center gap-2 rounded-xl bg-white/[0.05] px-3 py-2 text-xs font-medium text-ink-muted ring-1 ring-white/10" role="status">
      <span className={cn('size-2 rounded-full', health.isPending ? 'bg-navy-100' : ok ? 'pulse-dot bg-emerald-400' : 'bg-rose-400')} aria-hidden />
      {label}
      {health.data && <span className="ml-auto font-mono text-[10px] text-ink-subtle">v{health.data.version}</span>}
    </div>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="glass-panel relative isolate flex h-full flex-col overflow-hidden rounded-[28px] px-3 py-4">
      {/* Ambient light inside the glass. */}
      <span className="pointer-events-none absolute -top-24 -left-20 -z-10 size-64 rounded-full bg-violet-400/25 blur-3xl" aria-hidden />
      <span className="pointer-events-none absolute -right-24 bottom-24 -z-10 size-64 rounded-full bg-cyan-300/25 blur-3xl" aria-hidden />
      <Link to="/" onClick={onNavigate} className="mb-6 px-2 py-1">
        <Logo />
      </Link>
      <p className="mb-2 px-3 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-subtle">Modules</p>
      <nav aria-label="Primary" className="flex-1 overflow-y-auto">
        <NavItems onNavigate={onNavigate} />
      </nav>
      <div className="hero-surface relative mb-3 overflow-hidden rounded-2xl px-3 pt-2 pb-3 shadow-[0_16px_30px_-16px_rgb(42_31_110/0.8)]">
        <NetworkArt className="-mx-2 -mb-2 h-20 w-[calc(100%+1rem)] opacity-90" />
        <p className="relative text-[12px] font-semibold text-white">Evidence, not guesses</p>
        <p className="relative text-[11px] leading-4 text-white/65">Every finding links back to its source.</p>
      </div>
      <SystemBadge />
    </div>
  )
}

function Drawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null)
  useFocusTrap(panel, open, onClose)
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <motion.div
            className="absolute inset-0 bg-navy-950/50"
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
            aria-label="Navigation"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 w-[280px] max-w-[85vw] p-2 outline-none"
            initial={{ x: -280 }}
            animate={{ x: 0, transition: spring }}
            exit={{ x: -280, transition: { duration: DURATION.base, ease: EASE_OUT } }}
          >
            <Sidebar onNavigate={onClose} />
            <button type="button" onClick={onClose} className="absolute top-4 right-3 rounded-md p-1.5 text-ink-muted transition-colors hover:bg-white/10 hover:text-white" aria-label="Close navigation">
              <X className="size-5" aria-hidden />
            </button>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

export function AppShell() {
  const location = useLocation()
  const outlet = useOutlet()
  const [drawer, setDrawer] = useState(false)
  const mainRef = useRef<HTMLElement>(null)
  const pageRef = useRef<HTMLDivElement>(null)

  // Layout effect: `inert` must be lifted before the drawer's focus trap restores focus to the menu button.
  useLayoutEffect(() => {
    // React 18's DOM types don't include `inert`; set the attribute directly.
    const el = pageRef.current
    if (!el) return
    if (drawer) el.setAttribute('inert', '')
    else el.removeAttribute('inert')
  }, [drawer])

  // Move focus to main content on navigation for keyboard and screen-reader users.
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[280px_1fr]">
      <a href="#main" className="sr-only z-50 rounded bg-navy-900 px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <Scene />
      <aside className="sticky top-0 hidden h-dvh p-3 pr-0 lg:block">
        <Sidebar />
      </aside>

      <Drawer open={drawer} onClose={() => setDrawer(false)} />

      {/* While the mobile drawer is open, the page behind it is inert (not focusable or clickable). */}
      <div ref={pageRef} className="flex min-w-0 flex-col">
        <Topbar onOpenNav={() => setDrawer(true)} />
        <main id="main" ref={mainRef} tabIndex={-1} className="flex-1 overflow-x-clip px-4 py-6 outline-none sm:px-8 sm:py-8">
          {/* Enter-only route transition: the next page mounts at once and fades in. Navigation never waits on an
              exit animation (which would stall if animation frames are paused, e.g. in a background tab). */}
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 26, rotateX: 7, scale: 0.985, filter: 'blur(6px)' }}
            animate={{
              opacity: 1, y: 0, rotateX: 0, scale: 1, filter: 'blur(0px)',
              transition: { type: 'spring', stiffness: 160, damping: 22, mass: 0.9 },
              transitionEnd: { filter: 'none' },
            }}
            style={{ transformPerspective: 1400, transformOrigin: '50% 0%' }}
            className="mx-auto max-w-[1280px]"
          >
            <Suspense
              fallback={
                <div role="status" aria-label="Loading page" className="space-y-4">
                  <div className="skeleton h-3 w-24" />
                  <div className="skeleton h-8 w-1/3" />
                  <div className="skeleton h-4 w-1/2" />
                  <div className="grid gap-4 pt-2 sm:grid-cols-3">
                    <div className="skeleton h-24" />
                    <div className="skeleton h-24" />
                    <div className="skeleton h-24" />
                  </div>
                  <div className="skeleton h-56 w-full" />
                </div>
              }
            >
              {outlet}
            </Suspense>
          </motion.div>
        </main>
      </div>
      <SessionExpiryBanner />
    </div>
  )
}
