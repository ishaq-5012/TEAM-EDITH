import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { ModuleArt, type ArtVariant } from '../art/ModuleArt'
import { useTilt } from '../fx/useTilt'

const ART_BY_SECTION: Record<string, ArtVariant> = {
  '': 'command',
  applications: 'applications',
  evidence: 'evidence',
  compliance: 'compliance',
  review: 'review',
  trust: 'trust',
  governance: 'governance',
  account: 'account',
}

/** The module a path belongs to, for its illustration (evidence and trust pages live under /applications). */
function artFor(pathname: string): ArtVariant {
  if (pathname.endsWith('/evidence')) return 'evidence'
  if (pathname.endsWith('/trust')) return 'trust'
  return ART_BY_SECTION[pathname.split('/')[1] ?? ''] ?? 'command'
}

/** Page hero: dark navy banner with the module's animated illustration, title, description and actions. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  const { pathname } = useLocation()
  const ref = useTilt<HTMLElement>({ max: 3, lift: 4 })
  return (
    <header ref={ref} className="hero-surface tilt-lite rise-in mb-7 rounded-[26px] px-6 py-7 shadow-[0_30px_60px_-28px_rgb(42_31_110/0.7)] sm:px-8 sm:py-8">
      <div className="depth-art absolute top-1/2 right-2 hidden h-[125%] w-[46%] max-w-[420px] -translate-y-1/2 md:block">
        <ModuleArt variant={artFor(pathname)} className="size-full opacity-90" />
      </div>
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0 md:max-w-[58%]">
          {eyebrow && <p className="mb-1.5 text-[11px] font-semibold tracking-[0.16em] text-cyan-400 uppercase">{eyebrow}</p>}
          <h1 className="text-shimmer text-[28px] leading-tight font-bold tracking-[-0.03em] text-white sm:text-[36px]">{title}</h1>
          {description && <p className="mt-2 max-w-2xl text-[13.5px] leading-6 text-white/70">{description}</p>}
        </div>
        {actions && <div className="hero-actions relative flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}
