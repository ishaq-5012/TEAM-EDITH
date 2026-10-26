import { usePointerVars } from './usePointerVars'

/** A 24-spoke wheel, drawn in currentColor. */
function Chakra({ size, className, style }: { size: number; className?: string; style?: React.CSSProperties }) {
  const spokes = Array.from({ length: 24 }, (_, i) => (i * 360) / 24)
  return (
    <svg viewBox="-50 -50 100 100" width={size} height={size} className={className} style={style} fill="none" stroke="currentColor">
      <circle r="46" strokeWidth="3" />
      <circle r="40" strokeWidth="0.8" opacity="0.6" />
      <circle r="6" fill="currentColor" stroke="none" />
      {spokes.map((a) => (
        <g key={a} transform={`rotate(${a})`}>
          <path d="M0 -6 L1.6 -26 L0 -44 L-1.6 -26 Z" fill="currentColor" stroke="none" />
          <circle cy="-43" r="1.6" fill="currentColor" stroke="none" transform="rotate(7.5)" />
        </g>
      ))}
    </svg>
  )
}

/**
 * The app's living backdrop: a tricolor aurora (saffron, green, pink, chakra blue), a neon perspective floor,
 * slowly turning chakra wheels, glowing orbs and rings, a 3D cube, and a light that follows the cursor.
 * Every layer moves at its own depth with the pointer. Decorative only; it ignores the pointer and stops
 * moving under reduced motion.
 */
export function Scene() {
  usePointerVars()
  return (
    <div className="scene" aria-hidden>
      <div className="tricolor-bar" />
      <div className="scene-blob scene-blob-a" />
      <div className="scene-blob scene-blob-b" />
      <div className="scene-blob scene-blob-c" />
      <div className="scene-blob-d" />
      <div className="scene-floor" />
      <div className="scene-grid depth-1" />
      <div className="depth-2">
        <Chakra size={420} className="chakra" style={{ top: '6%', left: '64%', opacity: 0.35 }} />
        <span className="glass-orb" style={{ top: '18%', left: '30%', width: 90, height: 90 }} />
        <span className="glass-orb glass-orb-cyan" style={{ top: '70%', left: '86%', width: 64, height: 64, animationDelay: '-4s' }} />
        <span className="glass-ring" style={{ top: '76%', left: '28%', width: 160, height: 160 }} />
      </div>
      <div className="depth-3">
        <Chakra size={120} className="chakra chakra-sm" style={{ top: '62%', left: '8%' }} />
        <span className="glass-orb glass-orb-pink" style={{ top: '40%', left: '93%', width: 44, height: 44, animationDelay: '-7s' }} />
        <span className="glass-ring glass-ring-sm" style={{ top: '12%', left: '20%', width: 80, height: 80, animationDelay: '-3s' }} />
        <div className="cube-wrap" style={{ top: '50%', left: '74%' }}>
          <div className="cube">
            {['front', 'back', 'right', 'left', 'top', 'bottom'].map((f) => (
              <span key={f} className={`cube-face cube-${f}`} />
            ))}
          </div>
        </div>
      </div>
      <div className="cursor-light" />
    </div>
  )
}
