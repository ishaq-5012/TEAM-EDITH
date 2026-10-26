import { ChevronDown, KeyRound, LogOut, Menu } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../features/auth/AuthProvider'
import { roleLabel } from '../../lib/format'
import { Breadcrumbs } from './Breadcrumbs'

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const close = (restore: boolean) => {
    setOpen(false)
    if (restore) trigger.current?.focus()
  }
  useEffect(() => {
    if (!open) return
    // Menu pattern: focus moves to the first item; arrows/Home/End move between items; Escape returns to the trigger.
    const items = () => Array.from(menu.current?.querySelectorAll<HTMLElement>('[role=menuitem]') ?? [])
    items()[0]?.focus()
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => {
      const list = items()
      const i = list.indexOf(document.activeElement as HTMLElement)
      if (e.key === 'Escape') {
        e.preventDefault()
        close(true)
      } else if (e.key === 'Tab') {
        setOpen(false)
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const next = e.key === 'ArrowDown' ? (i + 1) % list.length : (i - 1 + list.length) % list.length
        list[next]?.focus()
      } else if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault()
        list[e.key === 'Home' ? 0 : list.length - 1]?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  if (!user) return null
  const initials = user.full_name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
  return (
    <div className="relative" ref={ref}>
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault()
            setOpen(true)
          }
        }}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Account menu for ${user.full_name}`}
        className="flex items-center gap-2.5 rounded-lg py-1 pr-2 pl-1 transition-colors hover:bg-navy-50"
      >
        <span className="grid size-9 place-items-center rounded-full bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] text-xs font-bold text-white shadow-[0_1px_0_rgb(255_255_255/0.35)_inset,0_6px_14px_-6px_rgb(109_68_236/0.8)] ring-2 ring-white/20">{initials}</span>
        <span className="hidden text-left sm:block">
          <span className="block text-[13px] leading-4 font-medium text-ink">{user.full_name}</span>
          <span className="block text-[11.5px] leading-4 text-ink-subtle">
            {roleLabel(user.role)}
            {user.institution && <span title={user.institution.name}> · {user.institution.code}</span>}
          </span>
        </span>
        <ChevronDown className="size-4 text-ink-subtle" aria-hidden />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={menu}
            role="menu"
            aria-label="Account"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 z-40 mt-2 w-60 rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow-raised)]"
          >
            <div className="border-b border-line px-3 py-2">
              <p className="truncate text-[13px] font-medium">{user.email}</p>
            </div>
            <Link
              role="menuitem"
              to="/account"
              onClick={() => setOpen(false)}
              className="mt-1 flex items-center gap-2 rounded-md px-3 py-2 text-[13px] transition-colors hover:bg-navy-50 focus-visible:bg-navy-50"
            >
              <KeyRound className="size-4 text-ink-subtle" aria-hidden /> Account & password
            </Link>
            <button role="menuitem" type="button" onClick={() => void logout()} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-[13px] text-fail transition-colors hover:bg-fail-bg focus-visible:bg-fail-bg">
              <LogOut className="size-4" aria-hidden /> Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function Topbar({ onOpenNav }: { onOpenNav: () => void }) {
  return (
    <header className="sticky top-3 z-30 mx-3 mt-3 flex h-16 items-center gap-3 rounded-2xl border border-white/10 bg-[rgb(10_13_38/0.6)] px-4 shadow-[0_1px_0_rgb(255_255_255/0.08)_inset,0_0_40px_-20px_rgb(255_79_216/0.6),0_16px_36px_-22px_rgb(55_40_140/0.45)] backdrop-blur-xl sm:mx-6 sm:px-6">
      <button type="button" onClick={onOpenNav} className="rounded-md p-2 text-ink-muted transition-colors hover:bg-navy-50 lg:hidden" aria-label="Open navigation">
        <Menu className="size-5" aria-hidden />
      </button>
      <div className="min-w-0 flex-1">
        <Breadcrumbs />
      </div>
      <UserMenu />
    </header>
  )
}
