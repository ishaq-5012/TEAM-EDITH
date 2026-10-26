import { useReducedMotion } from 'motion/react'
import { useEffect, useRef } from 'react'

/**
 * 3D tilt toward the mouse with a lift and a moving glare (CSS vars --gx/--gy read by `.tilt-surface::before`).
 * Writes the transform directly (no re-render), so pages with many cards stay smooth. The angle scales down with
 * the element's size, so a wide table barely moves while a small tile tilts clearly. Off for touch, while a field
 * inside has focus, and under reduced motion.
 */
export function useTilt<T extends HTMLElement>({ max, lift }: { max?: number; lift?: number } = {}) {
  const ref = useRef<T>(null)
  const reduce = useReducedMotion()
  useEffect(() => {
    const el = ref.current
    if (!el || reduce) return
    if (!window.matchMedia?.('(hover: hover) and (pointer: fine)').matches) return
    let frame = 0
    const move = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse' || el.matches(':focus-within')) return
      const r = el.getBoundingClientRect()
      const px = (e.clientX - r.left) / r.width
      const py = (e.clientY - r.top) / r.height
      const amp = max ?? Math.max(0.6, Math.min(8, 1700 / Math.max(r.width, r.height)))
      const up = lift ?? (amp > 3 ? 6 : 2)
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        el.style.setProperty('--gx', `${(px * 100).toFixed(1)}%`)
        el.style.setProperty('--gy', `${(py * 100).toFixed(1)}%`)
        el.style.transform = `perspective(1100px) rotateX(${((0.5 - py) * amp).toFixed(2)}deg) rotateY(${((px - 0.5) * amp).toFixed(2)}deg) translate3d(0, ${-up}px, 0)`
        el.classList.add('is-tilting')
      })
    }
    const leave = () => {
      cancelAnimationFrame(frame)
      el.style.transform = ''
      el.classList.remove('is-tilting')
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    el.addEventListener('focusin', leave)
    return () => {
      cancelAnimationFrame(frame)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', leave)
      el.removeEventListener('focusin', leave)
    }
  }, [reduce, max, lift])
  return ref
}
