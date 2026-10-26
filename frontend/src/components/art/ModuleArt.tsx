import { useId, type ReactNode } from 'react'
import { cn } from '../ui/cn'
import { NetworkArt } from './NetworkArt'

export type ArtVariant = 'command' | 'applications' | 'evidence' | 'compliance' | 'review' | 'trust' | 'governance' | 'account'

/** Shared defs and a soft backdrop of rings and stars that every module illustration sits on. */
function Scene({ children, className }: { children: (id: string) => ReactNode; className?: string }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 420 250" className={cn('pointer-events-none size-full select-none', className)} aria-hidden focusable="false">
      <defs>
        <linearGradient id={`${id}-a`} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="var(--color-violet-400)" />
          <stop offset="1" stopColor="var(--color-cyan-400)" />
        </linearGradient>
        <linearGradient id={`${id}-card`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0.96" />
          <stop offset="1" stopColor="white" stopOpacity="0.72" />
        </linearGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0" stopColor="var(--color-violet-400)" stopOpacity="0.6" />
          <stop offset="1" stopColor="var(--color-violet-400)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="250" cy="125" r="120" fill={`url(#${id}-glow)`} opacity="0.55" className="art-pulse" />
      <g className="art-orbit" opacity="0.4">
        <circle cx="250" cy="125" r="104" fill="none" stroke="white" strokeOpacity="0.3" strokeDasharray="2 8" />
      </g>
      {[[40, 40], [380, 30], [395, 200], [70, 215], [180, 22], [330, 232]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 2 ? 1.6 : 2.4} fill="white" className="art-pulse" style={{ animationDelay: `${i * -0.6}s` }} />
      ))}
      {children(id)}
    </svg>
  )
}

/** Floating "paper" card with text lines, used by several scenes. */
function Paper({ id, x, y, w = 70, h = 88, rot = 0, delay = 0, accent }: { id: string; x: number; y: number; w?: number; h?: number; rot?: number; delay?: number; accent?: string }) {
  return (
    <g className="art-float" style={{ animationDelay: `${delay}s` }}>
      <g transform={`translate(${x} ${y}) rotate(${rot})`}>
        <rect width={w} height={h} rx="9" fill={`url(#${id}-card)`} />
        <rect x="10" y="14" width={w * 0.5} height="5" rx="2.5" fill="var(--color-navy-600)" opacity="0.55" />
        <rect x="10" y="26" width={w * 0.72} height="4" rx="2" fill="var(--color-navy-600)" opacity="0.28" />
        <rect x="10" y="36" width={w * 0.6} height="4" rx="2" fill="var(--color-navy-600)" opacity="0.28" />
        <rect x="10" y="46" width={w * 0.66} height="4" rx="2" fill="var(--color-navy-600)" opacity="0.28" />
        {accent && <rect x="10" y={h - 22} width={w * 0.38} height="10" rx="5" fill={accent} opacity="0.85" />}
      </g>
    </g>
  )
}

function CommandScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(250 125)">
            {[86, 62, 38].map((r, i) => (
              <circle key={r} r={r} fill="none" stroke="white" strokeOpacity={0.18 + i * 0.08} strokeWidth="1.5" />
            ))}
            <g className="art-orbit" style={{ animationDuration: '8s' }}>
              <path d="M0 0 L0 -86 A86 86 0 0 1 61 -61 Z" fill={`url(#${id}-a)`} opacity="0.35" />
            </g>
            <circle r="6" fill="var(--color-cyan-400)" />
            {[[-40, -50], [55, 20], [-20, 60], [30, -30]].map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r="4" fill="white" className="art-pulse" style={{ animationDelay: `${i * -0.7}s` }} />
            ))}
          </g>
          <g transform="translate(40 150)" className="art-float">
            <rect width="110" height="70" rx="12" fill={`url(#${id}-card)`} />
            {[18, 34, 26, 44, 30].map((h, i) => (
              <rect key={i} x={14 + i * 18} y={56 - h} width="10" height={h} rx="3" fill={i === 3 ? 'var(--color-violet-600)' : 'var(--color-navy-600)'} opacity={i === 3 ? 0.9 : 0.35} />
            ))}
          </g>
        </>
      )}
    </Scene>
  )
}

function ApplicationsScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(150 70)" className="art-float" style={{ animationDelay: '-1s' }}>
            <path d="M0 18 Q0 8 10 8 L52 8 L62 20 L150 20 Q160 20 160 30 L160 120 Q160 130 150 130 L10 130 Q0 130 0 120 Z" fill="var(--color-violet-500)" opacity="0.55" />
          </g>
          <Paper id={id} x={182} y={48} rot={-8} delay={-0.4} accent="var(--color-pass)" />
          <Paper id={id} x={238} y={40} rot={6} delay={-2} accent="var(--color-violet-600)" />
          <g transform="translate(150 98)">
            <rect width="160" height="102" rx="14" fill="var(--color-navy-700)" opacity="0.9" />
            <rect x="16" y="20" width="70" height="6" rx="3" fill="white" opacity="0.6" />
            <rect x="16" y="34" width="110" height="5" rx="2.5" fill="white" opacity="0.25" />
          </g>
          <g transform="translate(330 60)" className="art-float" style={{ animationDelay: '-2.6s' }}>
            <circle r="22" fill={`url(#${id}-a)`} />
            <path d="M0 9 L0 -9 M-7 -2 L0 -9 L7 -2" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          </g>
        </>
      )}
    </Scene>
  )
}

function ComplianceScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(250 60)">
            <rect x="-3" y="0" width="6" height="130" rx="3" fill="white" opacity="0.75" />
            <rect x="-40" y="128" width="80" height="10" rx="5" fill="white" opacity="0.75" />
            <g className="art-float" style={{ animationDuration: '5s' }}>
              <rect x="-90" y="14" width="180" height="5" rx="2.5" fill="white" opacity="0.85" />
              <path d="M-80 19 L-104 70 L-56 70 Z" fill="none" stroke="white" strokeOpacity="0.6" />
              <path d="M80 19 L56 70 L104 70 Z" fill="none" stroke="white" strokeOpacity="0.6" />
              <ellipse cx="-80" cy="70" rx="26" ry="7" fill={`url(#${id}-a)`} />
              <ellipse cx="80" cy="70" rx="26" ry="7" fill={`url(#${id}-a)`} />
            </g>
          </g>
          <Paper id={id} x={60} y={110} w={84} h={96} rot={-6} delay={-1.2} accent="var(--color-pass)" />
          <Paper id={id} x={350} y={120} w={52} h={70} rot={8} delay={-2.4} accent="var(--color-review)" />
        </>
      )}
    </Scene>
  )
}

function ReviewScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(170 46)" className="art-float">
            <rect width="140" height="160" rx="16" fill={`url(#${id}-card)`} />
            {[0, 1, 2, 3].map((i) => (
              <g key={i} transform={`translate(18 ${26 + i * 32})`}>
                <rect width="18" height="18" rx="5" fill={i < 2 ? 'var(--color-pass)' : i === 2 ? 'var(--color-review)' : 'var(--color-navy-100)'} />
                {i < 2 && <path d="M4 9 L8 13 L14 5" stroke="white" strokeWidth="2.4" fill="none" strokeLinecap="round" />}
                <rect x="28" y="3" width={70 - i * 8} height="5" rx="2.5" fill="var(--color-navy-600)" opacity="0.5" />
                <rect x="28" y="12" width={50} height="4" rx="2" fill="var(--color-navy-600)" opacity="0.25" />
              </g>
            ))}
          </g>
          <g transform="translate(320 150)" className="art-float" style={{ animationDelay: '-2s' }}>
            <circle r="30" fill="none" stroke={`url(#${id}-a)`} strokeWidth="8" />
            <rect x="18" y="18" width="12" height="40" rx="6" transform="rotate(-45 24 24)" fill="white" opacity="0.85" />
          </g>
        </>
      )}
    </Scene>
  )
}

function TrustScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(250 125)" className="art-float">
            <path d="M0 -84 L66 -58 L66 6 Q66 58 0 86 Q-66 58 -66 6 L-66 -58 Z" fill={`url(#${id}-a)`} opacity="0.9" />
            <path d="M0 -66 L50 -46 L50 4 Q50 44 0 66 Q-50 44 -50 4 L-50 -46 Z" fill="var(--color-navy-900)" opacity="0.55" />
            <path d="M-22 2 L-6 18 L26 -16" stroke="white" strokeWidth="9" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </g>
          <Paper id={id} x={60} y={70} rot={-10} delay={-1.5} accent="var(--color-pass)" />
          <g transform="translate(360 70)" className="art-float" style={{ animationDelay: '-2.8s' }}>
            <rect x="-16" y="-4" width="32" height="26" rx="6" fill="white" opacity="0.9" />
            <path d="M-9 -4 V-12 Q-9 -22 0 -22 Q9 -22 9 -12 V-4" stroke="white" strokeWidth="4" fill="none" opacity="0.9" />
            <circle cy="9" r="4" fill="var(--color-violet-600)" />
          </g>
        </>
      )}
    </Scene>
  )
}

function GovernanceScene() {
  return (
    <Scene>
      {(id) => (
        <>
          <g transform="translate(150 50)" className="art-float">
            <rect width="190" height="150" rx="16" fill={`url(#${id}-card)`} />
            {[40, 70, 52, 96, 78].map((h, i) => (
              <rect key={i} x={22 + i * 32} y={128 - h} width="20" height={h} rx="5" fill={i === 3 ? `url(#${id}-a)` : 'var(--color-navy-600)'} opacity={i === 3 ? 1 : 0.3} />
            ))}
            <path d="M24 70 L60 52 L92 62 L126 26 L160 40" stroke="var(--color-violet-600)" strokeWidth="3" fill="none" strokeLinecap="round" className="art-flow" />
          </g>
          <g transform="translate(360 170)" className="art-float" style={{ animationDelay: '-2s' }}>
            <circle r="30" fill="white" opacity="0.9" />
            <path d="M0 0 L0 -30 A30 30 0 0 1 26 15 Z" fill="var(--color-violet-600)" />
            <path d="M0 0 L26 15 A30 30 0 0 1 -20 22 Z" fill="var(--color-cyan-500)" />
          </g>
        </>
      )}
    </Scene>
  )
}

const SCENES: Record<ArtVariant, () => ReactNode> = {
  command: CommandScene,
  applications: ApplicationsScene,
  evidence: () => <NetworkArt className="size-full" />,
  compliance: ComplianceScene,
  review: ReviewScene,
  trust: TrustScene,
  governance: GovernanceScene,
  account: GovernanceScene,
}

/** Animated illustration for a module's hero banner. Decorative only. */
export function ModuleArt({ variant, className }: { variant: ArtVariant; className?: string }) {
  const Scene = SCENES[variant]
  return (
    <div className={className} aria-hidden>
      <Scene />
    </div>
  )
}
