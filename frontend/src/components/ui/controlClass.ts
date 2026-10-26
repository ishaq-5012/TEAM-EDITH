import { cn } from './cn'

export type ControlSize = 'sm' | 'md'

/**
 * The one form-control look: border, violet focus halo, muted disabled state. `sm` (36px) for filter bars and
 * dense editors, `md` (40px) for forms. Use the bare Input/Select/Textarea when the label lives elsewhere
 * (filter bars, table cells); use TextField/SelectField/TextareaField for labelled form fields.
 */
export function controlClass({
  size = 'md',
  invalid = false,
  multiline = false,
  full = true,
}: { size?: ControlSize; invalid?: boolean; multiline?: boolean; full?: boolean } = {}) {
  // cn() only joins strings, so width is an option rather than an override that would fight w-full.
  return cn(
    'control rounded-[var(--radius-control)] border bg-white/[0.05] text-ink backdrop-blur-sm placeholder:text-ink-subtle',
    full && 'w-full',
    'shadow-[inset_0_1px_2px_rgb(0_0_0/0.4)] transition-[border-color,box-shadow,transform] duration-200 hover:border-white/30 focus:-translate-y-px focus:border-saffron focus:bg-white/[0.08] focus:ring-4 focus:ring-saffron/20 focus:shadow-[0_0_26px_-6px_rgb(255_153_51/0.6)] focus:outline-none motion-reduce:focus:translate-y-0',
    'disabled:cursor-not-allowed disabled:bg-navy-50 disabled:text-ink-muted',
    size === 'sm' ? 'px-2.5 text-[13px]' : 'px-3 text-sm',
    multiline ? 'py-2' : size === 'sm' ? 'h-9' : 'h-10',
    invalid ? 'border-fail' : 'border-line-strong',
  )
}
