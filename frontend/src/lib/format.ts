const dtf = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

export const formatDateTime = (iso: string | null | undefined) => (iso ? dtf.format(new Date(iso)) : '—')

export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = (new Date(iso).getTime() - now) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day')
  return formatDateTime(iso)
}

export const shortHash = (h: string | null | undefined, n = 10) => (h ? `${h.slice(0, n)}…` : '—')

export const roleLabel = (role: string) =>
  ({
    admin: 'System administrator',
    compliance_manager: 'Compliance manager',
    second_approver: 'Second approver',
    reviewer: 'Reviewer',
    auditor: 'Auditor',
  })[role] ?? role

/** Mirrors backend app.core.security.password_strength_error. */
export function passwordStrengthError(pw: string): string | null {
  if (pw.length < 12) return 'Password must be at least 12 characters'
  if (pw.length > 256) return 'Password must be at most 256 characters'
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length
  if (classes < 3) return 'Password must mix at least three of: lowercase, uppercase, digits, symbols'
  return null
}

/** Rough, display-only description of a user-agent string. Never used for security decisions. */
export function describeAgent(ua: string | null): string {
  if (!ua) return 'Unknown device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS X/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}
