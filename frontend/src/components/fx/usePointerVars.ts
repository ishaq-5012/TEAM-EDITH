import { useEffect } from 'react'

/**
 * Publishes the pointer position as CSS variables on <html> once per frame:
 * --px/--py in [-1, 1] for parallax layers, --cx/--cy in pixels for the cursor light.
 */
export function usePointerVars() {
  useEffect(() => {
    const root = document.documentElement
    let frame = 0
    const move = (e: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        root.style.setProperty('--px', ((e.clientX / window.innerWidth) * 2 - 1).toFixed(3))
        root.style.setProperty('--py', ((e.clientY / window.innerHeight) * 2 - 1).toFixed(3))
        root.style.setProperty('--cx', `${e.clientX}px`)
        root.style.setProperty('--cy', `${e.clientY}px`)
      })
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', move)
    }
  }, [])
}
