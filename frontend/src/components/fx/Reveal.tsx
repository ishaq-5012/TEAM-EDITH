import { motion, useReducedMotion, type Variants } from 'motion/react'
import type { ReactNode } from 'react'

const variants: Variants = {
  hidden: { opacity: 0, y: 34, rotateX: -10, scale: 0.975, filter: 'blur(8px)' },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    rotateX: 0,
    scale: 1,
    filter: 'blur(0px)',
    // A leftover filter would make this element the containing block for fixed-position children.
    transitionEnd: { filter: 'none' },
    transition: { type: 'spring', stiffness: 170, damping: 22, mass: 0.9, delay: Math.min(i * 0.07, 0.42) },
  }),
}

/**
 * Section entrance: rises and flips into place in 3D the first time it scrolls into view. Under reduced
 * motion, or without IntersectionObserver (tests, very old browsers), the content simply renders in place.
 */
export function Reveal({ children, index = 0, className }: { children: ReactNode; index?: number; className?: string }) {
  const reduce = useReducedMotion()
  if (reduce || typeof IntersectionObserver === 'undefined') return <div className={className}>{children}</div>
  return (
    <motion.div
      className={className}
      style={{ transformPerspective: 1200, transformOrigin: '50% 0%' }}
      variants={variants}
      custom={index}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.08, margin: '0px 0px -40px 0px' }}
    >
      {children}
    </motion.div>
  )
}
