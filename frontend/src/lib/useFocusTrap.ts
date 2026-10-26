import { useEffect, useRef, type RefObject } from 'react'

export const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]):not([inert]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

/**
 * Keep keyboard focus inside `ref` while `active`: moves focus in on open (first form field, else first focusable,
 * else the container), cycles Tab/Shift+Tab, calls `onEscape` on Escape, and restores focus to the element that
 * had it before opening. If that element is gone (it was in content that re-rendered), focus moves to <main>.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, onEscape?: () => void, opts: { lockScroll?: boolean } = {}) {
  const escapeRef = useRef(onEscape)
  useEffect(() => {
    escapeRef.current = onEscape
  })

  useEffect(() => {
    if (!active) return
    const previous = document.activeElement as HTMLElement | null
    const root = ref.current
    const field = root?.querySelector<HTMLElement>('input:not([type=hidden]):not([disabled]),select:not([disabled]):not([inert]),[role=combobox]:not([disabled]),textarea:not([disabled])')
    const target = field ?? root?.querySelector<HTMLElement>(FOCUSABLE) ?? root
    target?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && escapeRef.current) {
        e.stopPropagation()
        escapeRef.current()
      } else if (e.key === 'Tab' && ref.current) {
        const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.closest('[inert]'))
        if (!items.length) {
          e.preventDefault()
          return
        }
        const [head, tail] = [items[0], items[items.length - 1]]
        if (e.shiftKey && (document.activeElement === head || !ref.current.contains(document.activeElement))) {
          e.preventDefault()
          tail.focus()
        } else if (!e.shiftKey && (document.activeElement === tail || !ref.current.contains(document.activeElement))) {
          e.preventDefault()
          head.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    if (opts.lockScroll !== false) document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      if (opts.lockScroll !== false) document.body.style.overflow = overflow
      if (previous && document.contains(previous)) previous.focus()
      else document.getElementById('main')?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])
}
