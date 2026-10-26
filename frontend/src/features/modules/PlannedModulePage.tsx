import { CheckCircle2, Construction } from 'lucide-react'
import { PageContainer } from '../../components/layout/PageContainer'
import type { ModuleDef } from '../../components/layout/modules'
import { Card, CardHeader } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/States'
import { StatusPill } from '../../components/ui/StatusPill'

/**
 * Intentional initial empty state for modules whose workflows ship in later phases.
 * Deliberately contains no interactive controls: nothing here pretends to work.
 */
export function PlannedModulePage({ module: m }: { module: ModuleDef }) {
  return (
    <PageContainer
      eyebrow={m.label}
      title={m.label}
      description={m.summary}
      actions={<StatusPill status="info">Delivered in a later phase</StatusPill>}
    >
      <Card>
        <EmptyState icon={<m.icon className="size-6" />} title={m.empty?.title ?? 'Nothing here yet'} className="py-14">
          {m.empty?.body}
          <span className="mt-2 block text-xs text-ink-subtle">This module is not active in the current build. No data on this page is simulated.</span>
        </EmptyState>
      </Card>
      <Card>
        <CardHeader icon={<Construction className="size-4" />} title="Scope of this module" description="What this module will do once its phase is delivered." />
        <ul className="grid gap-x-6 gap-y-3 p-5 md:grid-cols-2">
          {m.capabilities.map((c) => (
            <li key={c} className="flex gap-3 text-[13.5px] leading-6 text-ink-muted">
              <CheckCircle2 className="mt-1 size-4 shrink-0 text-navy-600/50" aria-hidden />
              {c}
            </li>
          ))}
        </ul>
      </Card>
    </PageContainer>
  )
}
