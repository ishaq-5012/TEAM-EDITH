import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Route pages are lazy-loaded chunks; the first import in a test run can take over the 1s default.
configure({ asyncUtilTimeout: 3000 })

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  vi.restoreAllMocks()
})

// jsdom lacks matchMedia, used by Motion's reduced-motion detection.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

// jsdom lacks ResizeObserver, used by Recharts' ResponsiveContainer.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// jsdom does not implement scrolling; the shell scrolls to top on navigation.
window.scrollTo = (() => {}) as typeof window.scrollTo

// jsdom lacks object URLs (used for page images and previews).
if (!URL.createObjectURL) {
  URL.createObjectURL = () => 'blob:test-object-url'
  URL.revokeObjectURL = () => {}
}
