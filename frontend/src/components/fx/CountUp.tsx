import { animate, useReducedMotion } from 'motion/react'
import { useEffect, useRef } from 'react'

/**
 * Renders the final value, then counts up from zero the first time it scrolls into view. Without
 * IntersectionObserver (tests, very old browsers) or with reduced motion it simply shows the value.
 */
export function CountUp({ value, format = (n) => n.toLocaleString() }: { value: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const reduce = useReducedMotion()
  useEffect(() => {
    const el = ref.current
    if (!el || reduce || typeof IntersectionObserver === 'undefined' || !Number.isFinite(value) || value === 0) return
    let stop: (() => void) | undefined
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return
        io.disconnect()
        const c = animate(0, value, {
          duration: Math.min(1.6, 0.6 + Math.log10(Math.abs(value) + 1) * 0.35),
          ease: [0.16, 1, 0.3, 1],
          onUpdate: (v) => {
            el.textContent = format(Math.round(v))
          },
        })
        stop = () => c.stop()
      },
      { threshold: 0.4 },
    )
    io.observe(el)
    return () => {
      io.disconnect()
      stop?.()
      el.textContent = format(value)
    }
  }, [value, reduce, format])
  return <span ref={ref}>{format(value)}</span>
}
