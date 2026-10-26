import type { Transition, Variants } from 'motion/react'

/**
 * Motion vocabulary. Short, purposeful, and the same everywhere. MotionConfig (main.tsx) applies the user's
 * reduced-motion preference: transforms and layout animation are skipped, opacity still changes, so state changes
 * stay perceivable without movement. Basic hover and focus feedback is CSS (index.css), not Motion.
 */
export const DURATION = { fast: 0.12, base: 0.18, slow: 0.26 } as const

export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1]

export const fade: Transition = { duration: DURATION.base, ease: EASE_OUT }

/** Dialogs, drawers and menus: a firm spring that settles in about 200 ms without overshoot. */
export const spring: Transition = { type: 'spring', stiffness: 520, damping: 40, mass: 0.8 }

/** Content swapped in place (tab panels, the evidence detail panel). */
export const panelSwap: Variants = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0, transition: fade },
  exit: { opacity: 0, transition: { duration: DURATION.fast } },
}

/** Notices that confirm or report the outcome of an action. */
export const notice: Variants = {
  initial: { opacity: 0, y: -6 },
  animate: { opacity: 1, y: 0, transition: fade },
  exit: { opacity: 0, y: -4, transition: { duration: DURATION.fast } },
}

/** Upper bound for list/graph stagger so large datasets never wait on choreography. */
export const stagger = (index: number, step = 0.03, max = 0.15) => Math.min(index * step, max)
