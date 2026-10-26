import { lazy, type ComponentType } from 'react'
import { Compass } from 'lucide-react'
import { Link, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { MODULES } from './components/layout/modules'
import { EmptyState } from './components/ui/States'
import { LoginPage } from './features/auth/LoginPage'
import { RequireAuth, RequirePermission } from './features/auth/RequireAuth'

// Route-level code splitting: each page loads on first visit.
const AccountPage = lazy(() => import('./features/account/AccountPage').then((m) => ({ default: m.AccountPage })))
const ApplicationDetailPage = lazy(() => import('./features/applications/ApplicationDetailPage').then((m) => ({ default: m.ApplicationDetailPage })))
const ApplicationsPage = lazy(() => import('./features/applications/ApplicationsPage').then((m) => ({ default: m.ApplicationsPage })))
const ExtractionInspectorPage = lazy(() =>
  import('./features/extraction/ExtractionInspectorPage').then((m) => ({ default: m.ExtractionInspectorPage })),
)
const EvidencePage = lazy(() => import('./features/evidence/EvidencePage').then((m) => ({ default: m.EvidencePage })))
const EvidenceIndexPage = lazy(() =>
  import('./features/evidence/EvidenceIndexPage').then((m) => ({ default: m.EvidenceIndexPage })),
)
const CommandCenterPage = lazy(() => import('./features/command-center/CommandCenterPage').then((m) => ({ default: m.CommandCenterPage })))
const GovernancePage = lazy(() => import('./features/governance/GovernancePage').then((m) => ({ default: m.GovernancePage })))
const CompliancePage = lazy(() => import('./features/compliance/CompliancePage').then((m) => ({ default: m.CompliancePage })))
const RuleDetailPage = lazy(() => import('./features/compliance/RuleDetailPage').then((m) => ({ default: m.RuleDetailPage })))
const ReviewQueuePage = lazy(() => import('./features/review/ReviewQueuePage').then((m) => ({ default: m.ReviewQueuePage })))
const ReviewItemPage = lazy(() => import('./features/review/ReviewItemPage').then((m) => ({ default: m.ReviewItemPage })))
const TrustCenterPage = lazy(() => import('./features/trust/TrustCenterPage').then((m) => ({ default: m.TrustCenterPage })))
const DocumentTrustPage = lazy(() => import('./features/trust/DocumentTrustPage').then((m) => ({ default: m.DocumentTrustPage })))
const PlannedModulePage = lazy(() => import('./features/modules/PlannedModulePage').then((m) => ({ default: m.PlannedModulePage })))

const IMPLEMENTED: Record<string, ComponentType> = {
  '/': CommandCenterPage,
  '/applications': ApplicationsPage,
  '/evidence': EvidenceIndexPage,
  '/compliance': CompliancePage,
  '/review': ReviewQueuePage,
  '/trust': TrustCenterPage,
  '/governance': GovernancePage,
}

function NotFound() {
  return (
    <EmptyState
      icon={<Compass className="size-6" />}
      title="Page not found"
      action={
        <Link to="/" className="text-sm font-medium text-violet-700 hover:underline">
          Back to Command Center
        </Link>
      }
    >
      The page you requested doesn’t exist.
    </EmptyState>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          {MODULES.map((m) => {
            const Page = IMPLEMENTED[m.path]
            const element = (
              <RequirePermission permission={m.permission}>{Page ? <Page /> : <PlannedModulePage module={m} />}</RequirePermission>
            )
            return m.path === '/' ? <Route key={m.path} index element={element} /> : <Route key={m.path} path={m.path} element={element} />
          })}
          <Route
            path="/applications/:id"
            element={
              <RequirePermission permission="applications:read">
                <ApplicationDetailPage />
              </RequirePermission>
            }
          />
          <Route
            path="/applications/:id/documents/:docId"
            element={
              <RequirePermission permission="documents:read">
                <ExtractionInspectorPage />
              </RequirePermission>
            }
          />
          <Route
            path="/applications/:id/evidence"
            element={
              <RequirePermission permission="documents:read">
                <EvidencePage />
              </RequirePermission>
            }
          />
          <Route
            path="/compliance/rules/:ruleId"
            element={
              <RequirePermission permission="rules:read">
                <RuleDetailPage />
              </RequirePermission>
            }
          />
          <Route
            path="/review/:itemId"
            element={
              <RequirePermission permission="applications:read">
                <ReviewItemPage />
              </RequirePermission>
            }
          />
          <Route
            path="/applications/:id/documents/:docId/trust"
            element={
              <RequirePermission permission="documents:read">
                <DocumentTrustPage />
              </RequirePermission>
            }
          />
          <Route path="/account" element={<AccountPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  )
}
