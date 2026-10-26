import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from './cn'
import { controlClass, type ControlSize } from './controlClass'
import { Dropdown } from './Dropdown'

type Sized = { size?: ControlSize; invalid?: boolean; full?: boolean }

export const Input = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> & Sized>(function Input(
  { size, invalid, full, className, ...rest },
  ref,
) {
  return <input ref={ref} aria-invalid={invalid || undefined} className={cn(controlClass({ size, invalid, full }), className)} {...rest} />
})

/** The app's dropdown. Same API as a native <select> (options as children); see Dropdown for how it works. */
export const Select = forwardRef<HTMLSelectElement, Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & Sized>(function Select(
  { size, invalid, full, className, children, ...rest },
  ref,
) {
  return (
    <Dropdown ref={ref} size={size} invalid={invalid} full={full} className={className} {...rest}>
      {children}
    </Dropdown>
  )
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & Sized>(function Textarea(
  { size, invalid, full, className, ...rest },
  ref,
) {
  return <textarea ref={ref} aria-invalid={invalid || undefined} className={cn(controlClass({ size, invalid, full, multiline: true }), className)} {...rest} />
})

interface FieldShellProps {
  label: string
  error?: string
  hint?: ReactNode
  children: (id: string, describedBy: string | undefined) => ReactNode
}

function FieldShell({ label, error, hint, children }: FieldShellProps) {
  const id = useId()
  const hintId = `${id}-hint`
  const errId = `${id}-err`
  const describedBy = [hint ? hintId : null, error ? errId : null].filter(Boolean).join(' ') || undefined
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink">
        {label}
      </label>
      {children(id, describedBy)}
      {hint && !error && (
        <p id={hintId} className="text-xs text-ink-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="text-xs font-medium text-fail">
          {error}
        </p>
      )}
    </div>
  )
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: ReactNode }

export const TextField = forwardRef<HTMLInputElement, InputProps>(function TextField({ label, error, hint, className, ...rest }, ref) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {(id, describedBy) => (
        <input
          ref={ref}
          id={id}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy}
          className={cn(controlClass({ invalid: !!error }), className)}
          {...rest}
        />
      )}
    </FieldShell>
  )
})

type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & { label: string; error?: string; hint?: ReactNode }

export const SelectField = forwardRef<HTMLSelectElement, SelectProps>(function SelectField(
  { label, error, hint, className, children, ...rest },
  ref,
) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {(id, describedBy) => (
        <Dropdown ref={ref} id={id} invalid={!!error} aria-describedby={describedBy} className={className} {...rest}>
          {children}
        </Dropdown>
      )}
    </FieldShell>
  )
})

type TextareaFieldProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string; hint?: ReactNode }

export const TextareaField = forwardRef<HTMLTextAreaElement, TextareaFieldProps>(function TextareaField(
  { label, error, hint, className, ...rest },
  ref,
) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {(id, describedBy) => (
        <textarea
          ref={ref}
          id={id}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy}
          className={cn(controlClass({ invalid: !!error, multiline: true }), className)}
          {...rest}
        />
      )}
    </FieldShell>
  )
})
