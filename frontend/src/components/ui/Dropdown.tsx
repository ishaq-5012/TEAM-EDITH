import { Check, ChevronDown } from 'lucide-react'
import {
  Children,
  Fragment,
  forwardRef,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'
import { createPortal } from 'react-dom'
import { cn } from './cn'
import { controlClass, type ControlSize } from './controlClass'

interface Item {
  value: string
  label: string
  disabled: boolean
  group?: string
}

/** Flattens <option>, <optgroup> and fragments into a list. The markup stays the single source of truth. */
function parseOptions(children: ReactNode, group?: string, out: Item[] = []): Item[] {
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return
    const el = child as ReactElement<{ value?: string | number; disabled?: boolean; label?: string; children?: ReactNode }>
    if (el.type === 'optgroup') {
      parseOptions(el.props.children, el.props.label, out)
    } else if (el.type === 'option') {
      const text = Children.toArray(el.props.children).join('')
      out.push({ value: String(el.props.value ?? text), label: text, disabled: !!el.props.disabled, group })
    } else if (el.type === Fragment) {
      parseOptions(el.props.children, group, out)
    }
  })
  return out
}

type Sized = { size?: ControlSize; invalid?: boolean; full?: boolean }

/**
 * A designed dropdown: a button that opens a keyboard-accessible listbox (the "select-only combobox" pattern).
 *
 * It wraps a real, hidden <select>. That element keeps the value, the name, the ref and the change event, so
 * react-hook-form's `register`, controlled `value`/`onChange` and form submission all work exactly as they did with a
 * plain <select>; the visible control only drives it. The popup is drawn in a portal so cards and dialogs cannot clip it.
 */
export const Dropdown = forwardRef<HTMLSelectElement, Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & Sized>(function Dropdown(
  { size, invalid, full = true, className, children, id, disabled, title, 'aria-label': ariaLabel, 'aria-describedby': describedBy, 'aria-labelledby': labelledBy, ...rest },
  forwardedRef,
) {
  const native = useRef<HTMLSelectElement | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const listId = useId()
  const items = useMemo(() => parseOptions(children), [children])
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [active, setActive] = useState(-1)
  const [place, setPlace] = useState<{ left: number; top?: number; bottom?: number; width: number; maxHeight: number } | null>(null)
  const typed = useRef({ text: '', at: 0 })

  const setRefs = useCallback(
    (el: HTMLSelectElement | null) => {
      native.current = el
      // `inert` takes the element out of the tab order and out of focus-trap queries; React 18 has no typed prop for it.
      el?.setAttribute('inert', '')
      if (typeof forwardedRef === 'function') forwardedRef(el)
      else if (forwardedRef) forwardedRef.current = el
    },
    [forwardedRef],
  )

  // The hidden select owns the value. Mirror it after every render (covers controlled values, defaults, and
  // react-hook-form writing `ref.value` directly) so the visible label never lags behind it.
  // Runs every render on purpose and only sets state when the value differs, so it cannot loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const v = native.current?.value ?? ''
    setCurrent((prev) => (prev === v ? prev : v))
  })

  const selected = items.find((i) => i.value === current)
  const enabled = useMemo(() => items.map((it, i) => (it.disabled ? -1 : i)).filter((i) => i >= 0), [items])

  const measure = useCallback(() => {
    const r = trigger.current?.getBoundingClientRect()
    if (!r) return
    const below = window.innerHeight - r.bottom - 12
    const above = r.top - 12
    const flip = below < 200 && above > below
    const maxHeight = Math.max(120, Math.min(300, flip ? above : below))
    setPlace(
      flip
        ? { left: r.left, bottom: window.innerHeight - r.top + 6, width: r.width, maxHeight }
        : { left: r.left, top: r.bottom + 6, width: r.width, maxHeight },
    )
  }, [])

  const openList = useCallback(() => {
    if (disabled) return
    measure()
    const start = items.findIndex((i) => i.value === current && !i.disabled)
    setActive(start >= 0 ? start : (enabled[0] ?? -1))
    setOpen(true)
  }, [disabled, measure, items, current, enabled])

  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) trigger.current?.focus()
  }, [])

  const choose = useCallback(
    (i: number) => {
      const item = items[i]
      const el = native.current
      if (!item || item.disabled || !el) return
      if (el.value !== item.value) {
        el.value = item.value
        el.dispatchEvent(new Event('change', { bubbles: true }))
        setCurrent(item.value)
      }
      close(true)
    },
    [items, close],
  )

  // Outside click, resize and scroll while open.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!list.current?.contains(t) && !trigger.current?.contains(t)) setOpen(false)
    }
    const onMove = () => measure()
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
  }, [open, measure])

  // Keep the highlighted option in view.
  useEffect(() => {
    if (open && active >= 0) list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active])

  const move = (delta: number) => {
    if (!enabled.length) return
    const at = enabled.indexOf(active)
    const next = at === -1 ? 0 : Math.min(enabled.length - 1, Math.max(0, at + delta))
    setActive(enabled[next])
  }

  const onKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        openList()
      }
      return
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        move(1)
        break
      case 'ArrowUp':
        e.preventDefault()
        move(-1)
        break
      case 'Home':
        e.preventDefault()
        setActive(enabled[0] ?? -1)
        break
      case 'End':
        e.preventDefault()
        setActive(enabled[enabled.length - 1] ?? -1)
        break
      case 'Enter':
      case ' ':
        e.preventDefault()
        if (active >= 0) choose(active)
        break
      case 'Escape':
        e.preventDefault()
        e.stopPropagation()
        close(true)
        break
      case 'Tab':
        setOpen(false)
        break
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          // Type-ahead: successive letters within a second extend the search.
          const now = Date.now()
          typed.current.text = now - typed.current.at > 900 ? e.key.toLowerCase() : typed.current.text + e.key.toLowerCase()
          typed.current.at = now
          const hit = items.findIndex((i) => !i.disabled && i.label.toLowerCase().startsWith(typed.current.text))
          if (hit >= 0) setActive(hit)
        }
    }
  }

  const activeId = open && active >= 0 ? `${listId}-opt-${active}` : undefined
  let lastGroup: string | undefined

  return (
    <span className={cn('relative', full ? 'block w-full' : 'inline-block')}>
      <button
        ref={trigger}
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={activeId}
        aria-label={ariaLabel}
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        disabled={disabled}
        title={title}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onKeyDown}
        onBlur={() => native.current?.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))}
        className={cn(
          controlClass({ size, invalid, full }),
          'flex items-center justify-between gap-2 pr-2.5 text-left',
          open && 'border-saffron ring-4 ring-saffron/20',
          className,
        )}
      >
        <span className={cn('min-w-0 flex-1 truncate', !selected && 'text-ink-subtle')}>{selected?.label ?? 'Select…'}</span>
        <ChevronDown aria-hidden className={cn('size-4 shrink-0 text-ink-subtle transition-transform duration-200 motion-reduce:transition-none', open && 'rotate-180 text-saffron')} />
      </button>
      <select ref={setRefs} hidden aria-hidden tabIndex={-1} disabled={disabled} {...rest}>
        {children}
      </select>
      {open &&
        place &&
        createPortal(
          <ul
            ref={list}
            id={listId}
            role="listbox"
            aria-label={ariaLabel}
            tabIndex={-1}
            style={{ left: place.left, top: place.top, bottom: place.bottom, minWidth: place.width, maxHeight: place.maxHeight }}
            className="fixed z-[100] max-w-[min(32rem,calc(100vw-16px))] overflow-y-auto rounded-xl border border-white/15 bg-[rgb(10_13_38/0.96)] p-1.5 shadow-[0_0_0_1px_rgb(255_255_255/0.05),0_24px_50px_-12px_rgb(0_0_0/0.85),0_0_40px_-14px_rgb(255_79_216/0.5)] backdrop-blur-xl motion-safe:animate-[dropdown-in_0.14s_ease-out]"
          >
            {items.map((it, i) => {
              const header = it.group !== lastGroup && it.group ? it.group : null
              lastGroup = it.group
              const isSelected = it.value === current
              return (
                <Fragment key={`${it.value}-${i}`}>
                  {header && (
                    <li role="presentation" className="px-2.5 pt-2 pb-1 text-[10.5px] font-semibold tracking-[0.12em] text-ink-subtle uppercase">
                      {header}
                    </li>
                  )}
                  <li
                    id={`${listId}-opt-${i}`}
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={it.disabled || undefined}
                    data-index={i}
                    onMouseEnter={() => !it.disabled && setActive(i)}
                    onMouseDown={(e) => e.preventDefault() /* keep focus on the trigger */}
                    onClick={() => choose(i)}
                    className={cn(
                      'flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink',
                      i === active && 'bg-saffron/15 text-white',
                      isSelected && 'font-semibold',
                      it.disabled && 'cursor-not-allowed opacity-45',
                    )}
                  >
                    <span className="min-w-0 flex-1 break-words">{it.label}</span>
                    {isSelected && <Check aria-hidden className="size-4 shrink-0 text-saffron" />}
                  </li>
                </Fragment>
              )
            })}
          </ul>,
          document.body,
        )}
    </span>
  )
})
