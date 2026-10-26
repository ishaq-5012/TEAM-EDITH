import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { MODULES } from '../components/layout/modules'
import { AuthProvider } from '../features/auth/AuthProvider'
import { CommandCenterPage } from '../features/command-center/CommandCenterPage'
import type { Role } from '../lib/types'
import { json, makeMe, mockApi } from './fixtures'

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('application shell', () => {
  it('defines exactly seven modules', () => {
    expect(MODULES).toHaveLength(7)
  })

  it.each(MODULES.filter((m) => m.status === 'planned'))('$label route renders its intentional empty state', async (m) => {
    mockApi({ me: makeMe('admin') })
    renderAt(m.path)
    expect(await screen.findByRole('heading', { level: 1, name: m.label })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: m.empty!.title })).toBeInTheDocument()
    expect(within(screen.getByRole('main')).queryAllByRole('button')).toHaveLength(0)
  })

  it('renders breadcrumbs with the current page marked', async () => {
    mockApi({ me: makeMe('admin') })
    renderAt('/governance?tab=users')
    const nav = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    expect(within(nav).getByRole('link', { name: 'Governance & Insights' })).toBeInTheDocument()
    expect(within(nav).getByText('Users & roles')).toHaveAttribute('aria-current', 'page')
  })

  it('shows a not-found state for unknown routes', async () => {
    mockApi({ me: makeMe('admin') })
    renderAt('/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

describe('permission-aware navigation', () => {
  it('gives admins live staff and handoff links on the command center', async () => {
    const handlers = [(url: string) => {
      if (url.includes('/users?')) return json(200, { items: [{ id: 'u1', is_active: true }], total: 1, limit: 100, offset: 0 })
      if (url.includes('/applications?')) return json(200, { items: [{ id: 'a1', review_stage: 'audit' }], total: 1, limit: 100, offset: 0 })
      if (url.includes('/reviews?')) return json(200, { items: [], total: 0, limit: 1, offset: 0 })
      return undefined
    }]
    mockApi({ me: makeMe('admin'), handlers })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><MemoryRouter><AuthProvider><CommandCenterPage /></AuthProvider></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: 'Admin operations' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Active staff accounts/ })).toHaveAttribute('href', '/governance?tab=users')
    expect(screen.getByRole('link', { name: /Compliance escalations/ })).toHaveAttribute('href', '/review?status=escalated')
    expect(screen.getByText('At auditor')).toBeInTheDocument()
  })

  const visibleModules = async (role: Role) => {
    mockApi({ me: makeMe(role) })
    renderAt('/')
    const primary = await screen.findByRole('navigation', { name: 'Primary' })
    return within(primary)
      .getAllByRole('link')
      .map((a) => a.textContent?.replace('(delivered in a later phase)', '').trim())
  }

  it('reviewer sees case-work modules but not governance', async () => {
    const mods = await visibleModules('reviewer')
    expect(mods).toContain('Review & Resolution')
    expect(mods).not.toContain('Governance & Insights')
  })

  it('auditor sees governance and the review queue (read-only oversight)', async () => {
    const mods = await visibleModules('auditor')
    expect(mods).toContain('Governance & Insights')
    expect(mods).toContain('Review & Resolution')
  })

  it('direct navigation to a forbidden module shows an access message, not the module', async () => {
    mockApi({ me: makeMe('reviewer') })
    renderAt('/governance')
    expect(await screen.findByText('You don’t have access to this area')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Governance & Insights' })).not.toBeInTheDocument()
  })

  it('user-management controls render only with users:manage', async () => {
    const user = { id: 'u2', email: 'x@example.com', full_name: 'X', role: 'reviewer', is_active: true, last_login_at: null, password_changed_at: null, created_at: '2026-01-01T00:00:00Z' }
    const handlers = [(url: string) => (url.includes('/users?') ? json(200, { items: [user], total: 1, limit: 200, offset: 0 }) : undefined)]

    mockApi({ me: makeMe('auditor'), handlers })
    const auditorView = renderAt('/governance?tab=users')
    expect(await screen.findByText('x@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New user' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Sign x@example.com out everywhere/ })).not.toBeInTheDocument()
    auditorView.unmount()

    mockApi({ me: makeMe('admin'), handlers })
    renderAt('/governance?tab=users')
    expect(await screen.findByRole('button', { name: /Sign x@example.com out everywhere/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New user' })).toBeInTheDocument()
  })
})
