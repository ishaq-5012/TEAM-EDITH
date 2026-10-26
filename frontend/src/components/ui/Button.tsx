import { Loader2 } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type MouseEvent, type ReactNode } from 'react'
import { cn } from './cn'
import { Tooltip } from './Tooltip'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const variants: Record<Variant, string> = {
  primary:
    'btn-3d font-semibold text-white bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] shadow-[0_1px_0_rgb(255_255_255/0.35)_inset,0_0_22px_-4px_rgb(255_79_216/0.65),0_10px_24px_-10px_rgb(255_153_51/0.7)] hover:-translate-y-0.5 hover:brightness-110 hover:shadow-[0_1px_0_rgb(255_255_255/0.35)_inset,0_0_34px_-4px_rgb(255_79_216/0.85),0_14px_30px_-10px_rgb(255_153_51/0.85)] aria-disabled:hover:translate-y-0 aria-disabled:hover:brightness-100',
  secondary:
    'btn-3d text-ink border border-white/15 bg-white/[0.06] backdrop-blur-md shadow-[0_1px_0_rgb(255_255_255/0.08)_inset,0_6px_16px_-8px_rgb(0_0_0/0.7)] hover:-translate-y-0.5 hover:border-saffron/70 hover:bg-white/10 hover:text-white hover:shadow-[0_0_20px_-6px_rgb(255_153_51/0.7)] aria-disabled:hover:translate-y-0 aria-disabled:hover:border-line-strong aria-disabled:hover:text-ink',
  ghost: 'text-ink-muted hover:bg-white/[0.08] hover:text-white aria-disabled:hover:bg-transparent',
  danger:
    'btn-3d text-white bg-[linear-gradient(120deg,#ff4d6d,#c9184a)] shadow-[0_1px_0_rgb(255_255_255/0.3)_inset,0_0_22px_-6px_rgb(255_77_109/0.8)] hover:-translate-y-0.5 hover:brightness-110 aria-disabled:hover:translate-y-0 aria-disabled:hover:brightness-100',
}

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  /**
   * Why the action is unavailable. With `disabled`, the button stays focusable (aria-disabled), ignores clicks and
   * explains itself in a tooltip announced to screen readers. Use whenever the reason isn't obvious from context.
   */
  disabledReason?: string
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading, icon, className, children, disabled, disabledReason, type = 'button', onClick, ...rest },
  ref,
) {
  const explained = !!(disabled && disabledReason && !loading)
  const button = (
    <button
      ref={ref}
      type={type}
      // An explained disabled button must stay focusable so keyboard and screen-reader users can learn why.
      disabled={explained ? undefined : disabled || loading}
      aria-disabled={explained || undefined}
      aria-busy={loading || undefined}
      onClick={(e: MouseEvent<HTMLButtonElement>) => {
        if (explained) {
          e.preventDefault()
          return
        }
        onClick?.(e)
      }}
      className={cn(
        'inline-flex select-none items-center justify-center rounded-lg font-medium whitespace-nowrap',
        'transition-[background-color,color,border-color,filter,transform,box-shadow] duration-200 active:translate-y-px active:scale-[0.98]',
        'disabled:cursor-not-allowed disabled:opacity-55 disabled:active:translate-y-0',
        'aria-disabled:cursor-not-allowed aria-disabled:opacity-55 aria-disabled:active:translate-y-0',
        'motion-reduce:active:translate-y-0 motion-reduce:active:scale-100 motion-reduce:hover:translate-y-0',
        variants[variant],
        sizes[size],
        className,
      )}
      data-variant={variant}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
  // Keep the same wrapper whether or not the reason applies, so the button's DOM node (and keyboard focus)
  // survives the switch between unavailable and available.
  return disabledReason ? <Tooltip content={explained ? disabledReason : null}>{button}</Tooltip> : button
})
