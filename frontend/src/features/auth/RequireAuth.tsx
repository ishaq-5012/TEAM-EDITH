import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Logo } from '../../components/layout/Logo'
import type { Permission } from '../../lib/types'
import { useAuth } from './AuthProvider'
import { ShieldOff } from 'lucide-react'
import { EmptyState } from '../../components/ui/States'

export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') {
    return (
      <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading session">
        <div className="animate-pulse motion-reduce:animate-none">
          <Logo />
        </div>
      </div>
    )
  }
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

/** Client-side gate for UX only; the backend enforces the same permission on every endpoint. */
export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(permission)) {
    return (
      <EmptyState icon={<ShieldOff className="size-6" />} title="You don’t have access to this area">
        Your role does not include the <code className="rounded bg-navy-50 px-1 font-mono text-xs">{permission}</code> permission.
        Ask an administrator if you need it.
      </EmptyState>
    )
  }
  return <>{children}</>
}
