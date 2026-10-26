import { useId } from 'react'
import { cn } from '../ui/cn'

/**
 * Decorative evidence-network artwork for hero banners: document glyphs joined by flowing links, pulsing nodes
 * and slow orbit rings. Purely visual (aria-hidden). All movement is CSS and stops under prefers-reduced-motion.
 */
export function NetworkArt({ className }: { className?: string }) {
  const id = useId().replace(/:/g, '')
  const nodes: [number, number, number][] = [
    [62, 70, 5], [150, 34, 4], [214, 112, 6], [118, 156, 4], [292, 56, 5], [338, 150, 4], [256, 196, 5], [40, 190, 3.5],
    [386, 88, 3.5], [182, 228, 3],
  ]
  const links: [number, number][] = [[0, 1], [1, 2], [0, 3], [2, 3], [1, 4], [2, 4], [4, 5], [2, 6], [5, 6], [3, 7], [4, 8], [6, 9], [3, 9]]
  return (
    <svg viewBox="0 0 420 250" className={cn('pointer-events-none select-none', className)} aria-hidden focusable="false">
      <defs>
        <linearGradient id={`${id}-link`} x1="0" x2="1">
          <stop offset="0" stopColor="var(--color-cyan-400)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--color-violet-400)" stopOpacity="0.9" />
        </linearGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0" stopColor="var(--color-violet-400)" stopOpacity="0.55" />
          <stop offset="1" stopColor="var(--color-violet-400)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-doc`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0.95" />
          <stop offset="1" stopColor="white" stopOpacity="0.7" />
        </linearGradient>
      </defs>

      <g className="art-orbit" opacity="0.35">
        <circle cx="214" cy="125" r="112" fill="none" stroke="white" strokeOpacity="0.25" strokeDasharray="2 7" />
      </g>
      <g className="art-orbit-reverse" opacity="0.3">
        <circle cx="214" cy="125" r="70" fill="none" stroke="var(--color-cyan-400)" strokeOpacity="0.5" strokeDasharray="1 9" />
      </g>

      {links.map(([a, b], i) => (
        <line
          key={i}
          x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]}
          stroke={`url(#${id}-link)`} strokeWidth="1.4" strokeLinecap="round"
          className="art-flow" style={{ animationDelay: `${(i % 5) * -0.5}s` }}
        />
      ))}

      {nodes.map(([x, y, r], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r={r * 4} fill={`url(#${id}-glow)`} className="art-pulse" style={{ animationDelay: `${(i % 4) * -0.8}s` }} />
          <circle cx={x} cy={y} r={r} fill={i % 3 === 0 ? 'var(--color-cyan-400)' : 'white'} />
        </g>
      ))}

      {/* Three document cards floating over the network */}
      {[
        [92, 92, -8, 0],
        [244, 70, 6, -1.6],
        [300, 150, -4, -3.1],
      ].map(([x, y, rot, delay], i) => (
        <g key={i} className="art-float" style={{ animationDelay: `${delay}s` }}>
          <g transform={`translate(${x} ${y}) rotate(${rot})`}>
            <rect width="46" height="58" rx="6" fill={`url(#${id}-doc)`} />
            <path d="M34 0 L46 12 L34 12 Z" fill="var(--color-violet-400)" opacity="0.5" />
            <rect x="8" y="16" width="24" height="3" rx="1.5" fill="var(--color-navy-600)" opacity="0.5" />
            <rect x="8" y="24" width="30" height="3" rx="1.5" fill="var(--color-navy-600)" opacity="0.3" />
            <rect x="8" y="32" width="20" height="3" rx="1.5" fill="var(--color-navy-600)" opacity="0.3" />
            <rect x="8" y="42" width="16" height="6" rx="3" fill={i === 1 ? 'var(--color-fail)' : 'var(--color-pass)'} opacity="0.75" />
          </g>
        </g>
      ))}
    </svg>
  )
}
