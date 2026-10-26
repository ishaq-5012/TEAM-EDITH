import { ChevronRight, Home } from 'lucide-react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useDynamicCrumbs } from './crumbStore'
import { MODULES } from './modules'

export interface Crumb {
  label: string
  to?: string
}

const EXTRA_ROUTES: Record<string, string> = { '/account': 'Account' }
const TAB_LABELS: Record<string, Record<string, string>> = {
  '/governance': {
    insights: 'Insights',
    review: 'Review & false positives',
    rules: 'Rules & validation',
    audit: 'Audit history',
    exports: 'Exports',
    users: 'Users & roles',
  },
}

/** Derives the trail from the route table so it can never drift from navigation. */
// eslint-disable-next-line react-refresh/only-export-components
export function useCrumbs(): Crumb[] {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const dynamic = useDynamicCrumbs()
  const crumbs: Crumb[] = [{ label: 'Command Center', to: '/' }]
  if (pathname === '/') return crumbs
  if (/^\/applications\/[^/]+(\/documents\/[^/]+(\/trust)?|\/evidence)?$/.test(pathname)) {
    crumbs.push({ label: 'Application Workspace', to: '/applications' })
    crumbs.push(...(dynamic ?? [{ label: 'Loading…' }]))
    return crumbs
  }
  if (/^\/review\/[^/]+$/.test(pathname)) {
    crumbs.push({ label: 'Review & Resolution', to: '/review' })
    crumbs.push(...(dynamic ?? [{ label: 'Loading…' }]))
    return crumbs
  }
  if (/^\/compliance\/rules\/[^/]+$/.test(pathname)) {
    crumbs.push({ label: 'Compliance Studio', to: '/compliance' })
    crumbs.push(...(dynamic ?? [{ label: 'Loading…' }]))
    return crumbs
  }
  const mod = MODULES.find((m) => m.path === pathname)
  const label = mod?.label ?? EXTRA_ROUTES[pathname] ?? 'Not found'
  crumbs.push({ label, to: pathname })
  const tab = params.get('tab')
  const tabLabel = tab ? TAB_LABELS[pathname]?.[tab] : undefined
  if (tabLabel) crumbs.push({ label: tabLabel })
  return crumbs
}

export function Breadcrumbs() {
  const crumbs = useCrumbs()
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1 text-[13px]">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1
          return (
            <li key={`${c.label}-${i}`} className={i < crumbs.length - 2 ? 'hidden items-center gap-1 sm:flex' : 'flex min-w-0 items-center gap-1'}>
              {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-ink-subtle" aria-hidden />}
              {last || !c.to ? (
                <span aria-current={last ? 'page' : undefined} className="truncate font-medium text-ink">
                  {c.label}
                </span>
              ) : (
                <Link to={c.to} className="flex min-h-6 min-w-6 items-center justify-center gap-1 truncate rounded text-ink-muted hover:text-violet-700">
                  {i === 0 && <Home className="size-3.5" aria-hidden />}
                  <span className={i === 0 ? 'sr-only sm:not-sr-only' : undefined}>{c.label}</span>
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
