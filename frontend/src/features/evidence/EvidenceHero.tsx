import { animate, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'
import { NetworkArt } from '../../components/art/NetworkArt'
import { formatDateTime, shortHash } from '../../lib/format'
import type { EvidenceView, Outcome } from '../../lib/types'
import { OUTCOME, OUTCOME_LOOK, OUTCOME_ORDER } from './evidenceMeta'

/** A number that counts up to its value (instant under reduced motion). */
export function CountUp({ value, className }: { value: number; className?: string }) {
  const reduce = useReducedMotion()
  const [shown, setShown] = useState(reduce ? value : 0)
  useEffect(() => {
    if (reduce) {
      setShown(value)
      return
    }
    const controls = animate(0, value, { duration: 0.9, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => setShown(Math.round(v)) })
    return () => controls.stop()
  }, [value, reduce])
  return (
    <span className={className} aria-hidden>
      {shown}
    </span>
  )
}

/** Donut of findings by outcome; the centre shows the share of checks that are consistent. */
function OutcomeRing({ counts }: { counts: Record<Outcome, number> }) {
  const reduce = useReducedMotion()
  const total = OUTCOME_ORDER.reduce((a, o) => a + counts[o], 0)
  const r = 54
  const c = 2 * Math.PI * r
  let offset = 0
  const consistent = total ? Math.round((counts.pass / total) * 100) : 0
  return (
    <figure className="relative m-0 size-40 shrink-0" aria-label={`${consistent}% of ${total} checks consistent`}>
      <svg viewBox="0 0 140 140" className="size-full -rotate-90" aria-hidden>
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgb(255 255 255 / 0.12)" strokeWidth="14" />
        {OUTCOME_ORDER.map((o, i) => {
          const len = total ? (counts[o] / total) * c : 0
          const seg = (
            <motion.circle
              key={o}
              cx="70" cy="70" r={r} fill="none" strokeWidth="14" strokeLinecap="butt"
              style={{ stroke: OUTCOME_LOOK[o].bright }}
              strokeDasharray={`${len} ${c - len}`}
              initial={reduce ? false : { strokeDashoffset: -offset + len, opacity: 0 }}
              animate={{ strokeDashoffset: -offset, opacity: 1 }}
              transition={{ duration: 0.8, delay: 0.15 + i * 0.12, ease: [0.22, 1, 0.36, 1] }}
            />
          )
          offset += len
          return seg
        })}
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="text-3xl font-semibold tracking-[-0.03em]">
            <CountUp value={consistent} />%
          </p>
          <p className="text-[11px] tracking-wide text-white/70 uppercase">consistent</p>
        </div>
      </div>
    </figure>
  )
}

export function EvidenceHero({
  reference,
  title,
  view,
  actions,
}: {
  reference?: string
  title?: string
  view?: EvidenceView
  actions?: ReactNode
}) {
  const counts = Object.fromEntries(OUTCOME_ORDER.map((o) => [o, view?.analysis.summary[o] ?? 0])) as Record<Outcome, number>
  const checks = OUTCOME_ORDER.reduce((a, o) => a + counts[o], 0)
  return (
    <section className="hero-surface rise-in mb-6 rounded-[28px] px-6 py-7 sm:px-9 sm:py-9" aria-labelledby="evidence-hero-title">
      <NetworkArt className="absolute top-4 right-2 hidden w-[42%] max-w-[480px] opacity-70 md:block xl:top-1/2 xl:right-[24rem] xl:w-[30%] xl:-translate-y-1/2" />
      <div className="relative grid gap-8 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
        <div className="max-w-xl min-w-0">
          <p className="text-[11px] font-semibold tracking-[0.16em] text-cyan-400 uppercase">{reference ?? 'Evidence'} · Evidence Intelligence</p>
          <h1 id="evidence-hero-title" className="mt-2 text-3xl font-semibold tracking-[-0.03em] sm:text-[40px] sm:leading-[1.1]">
            Evidence Intelligence Graph
          </h1>
          {title && <p className="mt-2 text-[15px] text-white/80">{title}</p>}
          <p className="mt-3 max-w-lg text-[13.5px] leading-6 text-white/65">
            Every value is compared across documents with deterministic rules. Each finding links back to the document, field and page location it came from.
          </p>
          {view && (
            <div className="mt-5 flex flex-wrap gap-2 text-[12px] text-white/80">
              <span className="glass rounded-full px-3 py-1">{view.analysis.document_count} documents</span>
              <span className="glass rounded-full px-3 py-1">{checks} checks</span>
              <span className="glass rounded-full px-3 py-1">Analysed {formatDateTime(view.analysis.created_at)}</span>
              <span className="glass rounded-full px-3 py-1 font-mono" title={view.analysis.input_fingerprint}>
                inputs {shortHash(view.analysis.input_fingerprint, 8)}
              </span>
            </div>
          )}
          {actions && <div className="mt-6 flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
        {view && (
          <div className="glass flex w-fit flex-wrap items-center gap-6 justify-self-start rounded-3xl px-6 py-5 xl:justify-self-end">
            <OutcomeRing counts={counts} />
            <ul className="space-y-2 text-[13px]" aria-label="Findings by outcome">
              {OUTCOME_ORDER.map((o) => {
                const Icon = OUTCOME_LOOK[o].icon
                return (
                  <li key={o} className="flex items-center gap-2.5">
                    <span className="grid size-6 place-items-center rounded-md" style={{ background: OUTCOME_LOOK[o].bright }}>
                      <Icon className="size-3.5 text-navy-950" aria-hidden />
                    </span>
                    <span className="w-6 text-right font-semibold tabular-nums">{counts[o]}</span>
                    <span className="text-white/75">{OUTCOME[o].label}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
