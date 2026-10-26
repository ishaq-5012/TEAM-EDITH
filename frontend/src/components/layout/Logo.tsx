import { cn } from '../ui/cn'

export function Logo({ inverted, compact }: { inverted?: boolean; compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        className="relative grid size-8 place-items-center rounded-[9px] bg-[linear-gradient(135deg,#ff9933,#ff4fd8_50%,#3b5bff)] shadow-[0_0_18px_-3px_rgb(255_79_216/0.8)]"
        aria-hidden
      >
        <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12.5l4.2 4.2L19 7" />
        </svg>
      </span>
      {!compact && (
        <span className={cn('text-[15px] font-semibold tracking-[-0.01em]', inverted ? 'text-white' : 'text-ink')}>
          VerifyFlow<span className="text-vibrant font-bold"> AI</span>
        </span>
      )}
    </span>
  )
}
