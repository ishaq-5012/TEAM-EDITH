import { useEffect, useSyncExternalStore } from 'react'

export interface DynamicCrumb {
  label: string
  to?: string
}

/** Trail for dynamic route segments (e.g. application reference, document name), set by the page. */
let trail: DynamicCrumb[] | null = null
const listeners = new Set<() => void>()

const set = (next: DynamicCrumb[] | null) => {
  trail = next
  listeners.forEach((l) => l())
}

export function useDynamicCrumbs(): DynamicCrumb[] | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => trail,
  )
}

/** Set the dynamic trail while the calling page is mounted. Pass undefined until data has loaded. */
export function useBreadcrumbTrail(value: DynamicCrumb[] | undefined) {
  const key = value ? JSON.stringify(value) : ''
  useEffect(() => {
    set(key ? (JSON.parse(key) as DynamicCrumb[]) : null)
    return () => set(null)
  }, [key])
}
