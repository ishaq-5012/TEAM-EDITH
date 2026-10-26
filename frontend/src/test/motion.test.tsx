import { act, render, screen, waitFor } from '@testing-library/react'
import { MotionConfig } from 'motion/react'
import { useState } from 'react'
// @ts-expect-error -- Node's fs in the vitest (Node) runtime; the app itself has no Node types.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import { Dialog } from '../components/ui/Dialog'

// Vitest does not load stylesheets, so read the source directly.
const css: string = readFileSync('src/index.css', 'utf8') // vitest runs from frontend/
const original = window.matchMedia

function preferReducedMotion(reduce: boolean) {
  window.matchMedia = (query: string) =>
    ({
      matches: reduce && query.includes('prefers-reduced-motion'), // Motion asks for "(prefers-reduced-motion)"
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <MotionConfig reducedMotion="user">
      <button onClick={() => setOpen(true)}>Open</button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Confirm finding">
        <button type="button">Confirm</button>
      </Dialog>
    </MotionConfig>
  )
}

/** The dialog panel is the motion element that carries the entry transform. */
const panelTransform = () => (screen.getByRole('dialog').closest('[style]') as HTMLElement | null)?.style.transform ?? ''

afterEach(() => {
  window.matchMedia = original
})

describe('Reduced motion', () => {
  // Motion renders the `initial` frame, then with reduced motion jumps straight to the end state. Recording every
  // transform the panel goes through shows whether there was any movement in between, independent of timing.
  it('opens dialogs without movement when the user prefers reduced motion', async () => {
    preferReducedMotion(true)
    render(<Harness />)
    act(() => screen.getByRole('button', { name: 'Open' }).click())
    const panel = screen.getByRole('dialog', { name: 'Confirm finding' }).closest('[style]') as HTMLElement
    const seen = new Set<string>([panel.style.transform])
    const observer = new MutationObserver(() => seen.add(panel.style.transform))
    observer.observe(panel, { attributes: true, attributeFilter: ['style'] })
    await waitFor(() => expect(panel.style.transform).not.toMatch(/translate|scale/))
    observer.disconnect()
    const between = [...seen].filter((t) => t && t !== 'none' && t !== 'translateY(16px) scale(0.98)')
    expect(between).toEqual([])
  })

  it('starts the same dialog offset and scaled when motion is allowed', () => {
    preferReducedMotion(false)
    render(<Harness />)
    act(() => screen.getByRole('button', { name: 'Open' }).click())
    expect(screen.getByRole('dialog', { name: 'Confirm finding' })).toBeInTheDocument()
    expect(panelTransform()).toMatch(/translate|scale/)
  })

  it('stops CSS transitions, shimmer and press movement under prefers-reduced-motion', () => {
    const block = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(block).toContain('transition-duration: 0.01ms !important')
    expect(block).toContain('animation-duration: 0.01ms !important')
    expect(block).toMatch(/\.skeleton \{ animation: none; \}/)
    expect(block).toMatch(/\.interactive:active \{ transform: none; \}/)
  })
})

describe('Responsive tables', () => {
  it('scroll inside their container instead of widening the page', () => {
    expect(css).toMatch(/\.table-scroll \{ overflow-x: auto;/)
  })
})
