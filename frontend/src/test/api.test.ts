import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, onSessionExpiry, onUnauthorized, readCsrfToken } from '../lib/api'
import { passwordStrengthError } from '../lib/format'
import { apiError, json } from './fixtures'

function setCookie(name: string, value: string) {
  document.cookie = `${name}=${value}; path=/`
}

afterEach(() => {
  for (const name of ['vf_csrf', '__Host-vf_csrf']) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`
})

describe('api client', () => {
  it('uses same-origin credentials and never sends a bearer token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { status: 'ok', database: 'ok', version: '0.1.0' }))
    await api.health()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/health')
    expect(init?.credentials).toBe('same-origin')
    expect(new Headers(init?.headers).has('Authorization')).toBe(false)
  })

  it('echoes the CSRF cookie in a header on state-changing requests only', async () => {
    setCookie('vf_csrf', 'csrf-abc')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(204, undefined))
    await api.logout()
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('X-CSRF-Token')).toBe('csrf-abc')
    fetchMock.mockResolvedValue(json(200, []))
    await api.mySessions()
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).has('X-CSRF-Token')).toBe(false)
  })

  it('reads the __Host- prefixed CSRF cookie', () => {
    // jsdom (non-secure origin) correctly refuses to store __Host- cookies, so stub the getter.
    vi.spyOn(document, 'cookie', 'get').mockReturnValue('other=1; __Host-vf_csrf=host-token; x=y')
    expect(readCsrfToken()).toBe('host-token')
  })

  it('maps the backend error envelope and field errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json(422, {
        error: {
          code: 'validation_error',
          message: 'Invalid request',
          details: [{ loc: ['body', 'password'], msg: 'Value error, Password must be at least 12 characters', type: 'value_error' }],
        },
      }),
    )
    const err = await api.createUser({ email: 'a@b.co', full_name: 'A', role: 'reviewer', password: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.fieldErrors()).toEqual({ password: 'Password must be at least 12 characters' })
  })

  it('notifies listeners on 401, except for the login endpoint itself', async () => {
    const listener = vi.fn()
    const off = onUnauthorized(listener)
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => apiError(401, 'session_expired'))
    await expect(api.me()).rejects.toBeInstanceOf(ApiError)
    expect(listener).toHaveBeenCalledOnce()
    expect(listener.mock.calls[0][0].code).toBe('session_expired')
    await expect(api.login('a@b.co', 'x')).rejects.toBeInstanceOf(ApiError)
    expect(listener).toHaveBeenCalledOnce()
    off()
  })

  it('publishes the session expiry header', async () => {
    const listener = vi.fn()
    const off = onSessionExpiry(listener)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, [], { 'X-Session-Expires': '2026-10-22T12:00:00+00:00' }))
    await api.mySessions()
    expect(listener).toHaveBeenCalledWith('2026-10-22T12:00:00+00:00')
    off()
  })

  it('reports network failures distinctly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    const err = await api.health().catch((e) => e)
    expect(err.code).toBe('network_error')
  })

  it('encodes path params and query strings', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { items: [], total: 0, limit: 25, offset: 0 }))
    await api.auditEvents({ action: 'auth.login', limit: 25, offset: 0 })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/audit/events?action=auth.login&limit=25&offset=0')
    fetchMock.mockResolvedValue(json(204, undefined))
    await api.revokeSession('../x')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/sessions/..%2Fx')
  })
})

describe('password policy parity with backend', () => {
  it.each([
    ['short1A!', 'at least 12'],
    ['alllowercaseletters', 'mix'],
    ['Correct-Horse-42', null],
    ['UPPER lower 1234', null],
  ])('%s', (pw, expected) => {
    const res = passwordStrengthError(pw)
    if (expected === null) expect(res).toBeNull()
    else expect(res).toContain(expected)
  })
})
