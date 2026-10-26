import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../features/auth/AuthProvider'
import { LoginPage } from '../features/auth/LoginPage'
import { RequireAuth } from '../features/auth/RequireAuth'
import { SessionExpiryBanner } from '../features/auth/SessionExpiryBanner'
import { api } from '../lib/api'
import { apiError, makeMe, mockApi } from './fixtures'

function Home() {
  const { logout } = useAuth()
  return (
    <div>
      <p>Protected home</p>
      <button onClick={() => void logout()}>Log out</button>
      <SessionExpiryBanner />
    </div>
  )
}

function renderApp(path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<Home />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('login flow', () => {
  it('redirects anonymous users to login', async () => {
    mockApi({ me: null })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('restores an existing cookie session on load', async () => {
    mockApi({ me: makeMe('reviewer') })
    renderApp('/')
    expect(await screen.findByText('Protected home')).toBeInTheDocument()
  })

  it('validates input client-side before calling the login API', async () => {
    const spy = mockApi({ me: null })
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Sign in' })
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Email is required')).toBeInTheDocument()
    expect(spy.mock.calls.some(([u]) => String(u).endsWith('/auth/login'))).toBe(false)
  })

  it('fills evaluator role credentials without signing in automatically', async () => {
    const spy = mockApi({ me: null, handlers: [(url) => url.endsWith('/auth/evaluator-credentials')
      ? new Response(JSON.stringify({ accounts: [
        { role: 'admin', label: 'Admin', email: 'sih.admin@example.org', password: 'Admin-Walkthrough-42' },
        { role: 'reviewer', label: 'Reviewer', email: 'reviewer.demo@example.org', password: 'Walkthrough-Pass-42' },
      ] }), { status: 200 })
      : undefined] })
    renderApp('/login')
    expect(await screen.findByText('Auto-fill credentials')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Auto-fill Admin credentials' }))
    expect(screen.getByLabelText('Work email')).toHaveValue('sih.admin@example.org')
    await userEvent.click(await screen.findByRole('button', { name: 'Auto-fill Reviewer credentials' }))
    expect(screen.getByLabelText('Work email')).toHaveValue('reviewer.demo@example.org')
    expect(screen.getByLabelText('Password')).toHaveValue('Walkthrough-Pass-42')
    expect(spy.mock.calls.some(([url]) => String(url).endsWith('/auth/login'))).toBe(false)
  })

  it('shows the server error on bad credentials', async () => {
    mockApi({
      me: null,
      handlers: [(url) => (url.endsWith('/auth/login') ? apiError(401, 'invalid_credentials', 'Invalid email or password') : undefined)],
    })
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Work email'), 'a@example.org')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
  })

  it('shows throttling responses', async () => {
    mockApi({
      me: null,
      handlers: [(url) => (url.endsWith('/auth/login') ? apiError(429, 'too_many_attempts', 'Too many failed sign-in attempts. Try again in 15 minute(s).') : undefined)],
    })
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Work email'), 'a@example.org')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many failed sign-in attempts')
  })

  it('signs in, reaches the protected route, and signs out on the server', async () => {
    const spy = mockApi({ me: null })
    renderApp('/')
    await userEvent.type(await screen.findByLabelText('Work email'), 'admin@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'Correct-Horse-42')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Protected home')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByText('You have been signed out.')).toBeInTheDocument()
    const logoutCall = spy.mock.calls.find(([u]) => String(u).endsWith('/auth/logout'))
    expect(logoutCall?.[1]?.method).toBe('POST')
  })

  it('returns to login with an explanation when the server ends the session', async () => {
    const spy = mockApi({ me: makeMe('reviewer') })
    renderApp('/')
    await screen.findByText('Protected home')
    spy.mockResolvedValue(apiError(401, 'session_expired', 'Your session has ended.'))
    await act(async () => {
      await api.mySessions().catch(() => undefined)
    })
    expect(await screen.findByText(/Your session ended/)).toBeInTheDocument()
  })

  it('warns before idle expiry and lets the user stay signed in', async () => {
    const soon = makeMe('reviewer')
    soon.session.idle_expires_at = new Date(Date.now() + 60_000).toISOString() // inside the 2-minute warning window
    const spy = mockApi({ me: soon })
    renderApp('/')
    expect(await screen.findByText('Your session is about to end')).toBeInTheDocument()
    spy.mockImplementation(async () => new Response(JSON.stringify(makeMe('reviewer')), { status: 200 }))
    await userEvent.click(screen.getByRole('button', { name: 'Stay signed in' }))
    await vi.waitFor(() => expect(screen.queryByText('Your session is about to end')).not.toBeInTheDocument())
  })
})
