import { motion } from 'motion/react'
import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import { cn } from '../../components/ui/cn'
import { panelSwap } from '../../lib/motion'
import { LoadingRows } from '../../components/ui/States'
import { PageContainer } from '../../components/layout/PageContainer'
import type { Permission } from '../../lib/types'
import { useAuth } from '../auth/AuthProvider'
import { AuditLog } from './AuditLog'
import { UsersPanel } from './UsersPanel'

// Each insights tab (and its charting code) loads on first visit.
const InsightsPanel = lazy(() => import('../insights/InsightsPanel').then((m) => ({ default: m.InsightsPanel })))
const ReviewInsightsPanel = lazy(() => import('../insights/ReviewInsightsPanel').then((m) => ({ default: m.ReviewInsightsPanel })))
const RuleInsightsPanel = lazy(() => import('../insights/RuleInsightsPanel').then((m) => ({ default: m.RuleInsightsPanel })))
const ExportsPanel = lazy(() => import('../insights/ExportsPanel').then((m) => ({ default: m.ExportsPanel })))

type Tab = 'insights' | 'review' | 'rules' | 'audit' | 'exports' | 'users'

const TABS: { id: Tab; label: string; permission: Permission }[] = [
  { id: 'insights', label: 'Insights', permission: 'system:read' },
  { id: 'review', label: 'Review & false positives', permission: 'applications:read' },
  { id: 'rules', label: 'Rules & validation', permission: 'rules:read' },
  { id: 'audit', label: 'Audit history', permission: 'audit:read' },
  { id: 'exports', label: 'Exports', permission: 'exports:create' },
  { id: 'users', label: 'Users & roles', permission: 'users:read' },
]

export function GovernancePage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const visible = TABS.filter((t) => can(t.permission))
  const requested = params.get('tab') as Tab | null
  const active = visible.find((t) => t.id === requested)?.id ?? visible[0]?.id
  const select = (tab: Tab) => {
    // Keep the window and scope filters when switching tabs.
    const next = new URLSearchParams(params)
    next.set('tab', tab)
    setParams(next, { replace: true })
  }

  return (
    <PageContainer
      eyebrow="Governance & Insights"
      title="Governance & Insights"
      description="Metrics computed from stored records, with their definitions; reviewer outcomes; rule and validation history; the tamper-evident audit trail; and audited exports."
    >
      <div role="tablist" aria-label="Governance sections" className="flex max-w-full flex-wrap gap-1 rounded-xl border border-line bg-surface p-1 shadow-[var(--shadow-card)] sm:inline-flex">
        {visible.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => select(t.id)}
            className={cn('relative h-8 rounded-lg px-3.5 text-[13px] font-medium transition-colors', active === t.id ? 'text-white' : 'text-ink-muted hover:text-ink')}
          >
            {active === t.id && <motion.span layoutId="gov-tab" className="absolute inset-0 rounded-lg bg-navy-900" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
            <span className="relative">{t.label}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {/* Enter-only: the selected tab renders immediately and fades in; nothing waits on an exit. */}
        <motion.div key={active} variants={panelSwap} initial="initial" animate="animate">
            <Suspense fallback={<LoadingRows rows={6} label="Loading section" />}>
              {active === 'insights' && <InsightsPanel />}
              {active === 'review' && <ReviewInsightsPanel />}
              {active === 'rules' && <RuleInsightsPanel />}
              {active === 'audit' && <AuditLog />}
              {active === 'exports' && <ExportsPanel />}
              {active === 'users' && <UsersPanel />}
            </Suspense>
        </motion.div>
      </div>
    </PageContainer>
  )
}
