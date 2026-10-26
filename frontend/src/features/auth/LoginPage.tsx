import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { BadgeCheck, FileCheck2, Fingerprint, GitCompareArrows, Lock, ScrollText, ShieldCheck } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation } from 'react-router-dom'
import { z } from 'zod'
import { Scene } from '../../components/fx/Scene'
import { useTilt } from '../../components/fx/useTilt'
import { Logo } from '../../components/layout/Logo'
import { Button } from '../../components/ui/Button'
import { TextField } from '../../components/ui/Field'
import { api, errorMessage } from '../../lib/api'
import { useAuth } from './AuthProvider'

const SESSION_END_MESSAGES = {
  expired: 'Your session ended (inactivity, sign-out elsewhere, or an account change). Please sign in again.',
  signed_out: 'You have been signed out.',
  signed_out_offline:
    'You have been signed out on this device, but the server could not be reached to end the session. It will expire on its own.',
} as const

const schema = z.object({
  email: z.string().trim().min(1, 'Email is required').email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})
type Values = z.infer<typeof schema>

const pillars = [
  { icon: GitCompareArrows, title: 'Cross-document reasoning', text: 'Every finding links to its evidence.' },
  { icon: FileCheck2, title: 'Deterministic rules', text: 'Versioned and reproducible.' },
  { icon: ShieldCheck, title: 'Honest trust signals', text: 'Never claims what it cannot prove.' },
]

const spring = { type: 'spring', stiffness: 140, damping: 18, mass: 0.9 } as const

/** A floating paper card in the 3D stage. */
function Paper({ z, x, y, rot, title, status, tone, delay }: { z: number; x: number; y: number; rot: number; title: string; status: string; tone: 'pass' | 'fail'; delay: number }) {
  const reduce = useReducedMotion()
  const color = tone === 'pass' ? '#0f7a55' : '#c62839'
  const bg = tone === 'pass' ? '#dcf5ea' : '#fde8eb'
  return (
    <motion.div
      className="absolute w-48 rounded-2xl bg-white p-4 shadow-[0_0_40px_-10px_rgb(255_79_216/0.55),0_24px_50px_-18px_rgb(0_0_0/0.8)] ring-1 ring-white"
      style={{ left: x, top: y, transform: `translateZ(${z}px) rotate(${rot}deg)` }}
      initial={reduce ? false : { opacity: 0, y: 40, scale: 0.85 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ ...spring, delay }}
    >
      <div className="mb-3 flex items-center gap-2">
        <span className="grid size-7 place-items-center rounded-lg bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] text-white">
          <ScrollText className="size-4" aria-hidden />
        </span>
        <span className="text-[12px] font-bold text-[#151935]">{title}</span>
      </div>
      {[78, 62, 70, 48].map((w, i) => (
        <span key={i} className="mb-1.5 block h-1.5 rounded-full bg-[#e6e8f5]" style={{ width: `${w}%` }} />
      ))}
      <span className="mt-3 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ color, background: bg }}>
        {status}
      </span>
    </motion.div>
  )
}

function Stage() {
  const ref = useTilt<HTMLDivElement>({ max: 16, lift: 0 })
  const reduce = useReducedMotion()
  return (
    <div ref={ref} className="tilt-lite relative mx-auto h-[300px] w-[480px] [transform-style:preserve-3d]" aria-hidden>
      {/* orbit ring and glow */}
      <div className="absolute top-1/2 left-1/2 size-[360px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,rgb(255_79_216/0.35),rgb(255_153_51/0.15)_50%,transparent)]" />
      <div className="glass-ring" style={{ top: 40, left: 70, width: 320, height: 320 }} />
      <Paper z={40} x={10} y={40} rot={-8} title="Passport" status="✓ Consistent" tone="pass" delay={0.25} />
      <Paper z={90} x={150} y={120} rot={4} title="Application" status="≠ Date differs" tone="fail" delay={0.4} />
      <Paper z={20} x={280} y={20} rot={9} title="Utility bill" status="✓ Consistent" tone="pass" delay={0.55} />
      {/* shield badge */}
      <motion.div
        className="absolute grid size-24 place-items-center rounded-[28px] bg-[linear-gradient(145deg,#ff9933,#ff4fd8_50%,#3b5bff)] text-white shadow-[0_1px_0_rgb(255_255_255/0.4)_inset,0_0_60px_-6px_rgb(255_79_216/0.8)]"
        style={{ left: 300, top: 200, transform: 'translateZ(140px)' }}
        initial={reduce ? false : { opacity: 0, scale: 0.4, rotate: -30 }}
        animate={{ opacity: 1, scale: 1, rotate: 0 }}
        transition={{ ...spring, delay: 0.75 }}
      >
        <ShieldCheck className="size-12" />
        <span className="absolute -top-2 -right-2 grid size-8 place-items-center rounded-full bg-emerald-400 text-white ring-4 ring-[#0a0d24] shadow-[0_0_18px_rgb(34_197_94/0.9)]">
          <BadgeCheck className="size-5" />
        </span>
      </motion.div>
      <motion.div
        className="absolute rounded-2xl bg-[rgb(10_13_38/0.75)] px-3 py-2 text-[12px] font-bold text-[#86efac] ring-1 ring-[#22c55e]/50 backdrop-blur-md shadow-[0_0_24px_-6px_rgb(34_197_94/0.7)]"
        style={{ left: 40, top: 250, transform: 'translateZ(110px)' }}
        initial={reduce ? false : { opacity: 0, x: -30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ ...spring, delay: 0.9 }}
      >
        <Fingerprint className="mr-1 inline size-4" /> SHA-256 verified
      </motion.div>
    </div>
  )
}

function AnimatedHeadline() {
  const reduce = useReducedMotion()
  const words = ['Evidence', 'first.']
  const accent = ['Every', 'decision', 'traceable.']
  const word = (w: string, i: number, cls: string) => (
    <motion.span
      key={`${w}-${i}`}
      className={`inline-block ${cls}`}
      initial={reduce ? false : { opacity: 0, y: 40, rotateX: -70, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, rotateX: 0, filter: 'blur(0px)', transitionEnd: { filter: 'none' } }}
      transition={{ ...spring, delay: 0.1 + i * 0.09 }}
      style={{ transformPerspective: 600, transformOrigin: '50% 100%' }}
    >
      {w}&nbsp;
    </motion.span>
  )
  return (
    <h2 className="text-[42px] leading-[1.06] font-extrabold tracking-[-0.035em] text-ink xl:text-[52px]">
      {words.map((w, i) => word(w, i, ''))}
      <br />
      {accent.map((w, i) => word(w, i + words.length, 'text-vibrant neon-text'))}
    </h2>
  )
}

export function LoginPage() {
  const { status, login, sessionEnd } = useAuth()
  const location = useLocation()
  const reduce = useReducedMotion()
  const cardRef = useTilt<HTMLDivElement>({ max: 6, lift: 4 })
  const [formError, setFormError] = useState<string | null>(null)
  const evaluator = useQuery({ queryKey: ['evaluator-credentials'], queryFn: api.evaluatorCredentials, retry: false, gcTime: 0 })
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={from} replace />
  }

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null)
    try {
      await login(v.email, v.password)
    } catch (e) {
      setFormError(errorMessage(e))
    }
  })

  return (
    <div className="relative grid min-h-dvh overflow-hidden lg:grid-cols-[1.15fr_1fr]">
      <Scene />
      <aside className="relative hidden flex-col justify-center gap-7 px-14 py-10 lg:flex">
        <motion.div initial={reduce ? false : { opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} transition={spring}>
          <Logo />
        </motion.div>
        <div className="max-w-xl">
          <AnimatedHeadline />
          <motion.p
            className="mt-5 max-w-lg text-[16px] leading-7 text-ink-muted"
            initial={reduce ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: 0.55 }}
          >
            VerifyFlow validates applications, cross-checks documents and evaluates compliance rules, while people stay in
            control of every judgement.
          </motion.p>
        </div>
        <Stage />
        <ul className="grid max-w-2xl grid-cols-3 gap-3">
          {pillars.map((p, i) => (
            <motion.li
              key={p.title}
              initial={reduce ? false : { opacity: 0, y: 24, scale: 0.92 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ ...spring, delay: 0.9 + i * 0.1 }}
              className="glass-panel rounded-2xl p-4"
            >
              <span className="mb-2 grid size-10 place-items-center rounded-xl bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] text-white shadow-[0_0_18px_-4px_rgb(255_79_216/0.7)]">
                <p.icon className="size-5" aria-hidden />
              </span>
              <span className="block text-[13.5px] font-bold text-ink">{p.title}</span>
              <span className="block text-[12.5px] text-ink-muted">{p.text}</span>
            </motion.li>
          ))}
        </ul>
      </aside>

      <main className="relative flex items-center justify-center px-4 py-12 sm:px-8">
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 40, rotateY: -18, scale: 0.94 }}
          animate={{ opacity: 1, y: 0, rotateY: 0, scale: 1 }}
          transition={{ ...spring, delay: 0.2 }}
          style={{ transformPerspective: 1200 }}
          className="w-full max-w-[420px]"
        >
          <div className="spin-border rounded-[30px] p-[2px]">
            <div ref={cardRef} className="glass-panel tilt-surface rounded-[28px] !bg-[rgb(9_12_34/0.88)] px-8 py-9">
              <div className="mb-7 lg:hidden">
                <Logo />
              </div>
              <span className="mb-4 inline-flex items-center gap-1.5 rounded-full bg-saffron-soft px-3 py-1 text-[11.5px] font-bold tracking-wide text-[#ffb366] uppercase ring-1 ring-saffron/40">
                <Lock className="size-3.5" aria-hidden /> Secure workspace
              </span>
              <h1 className="text-[30px] leading-tight font-extrabold tracking-[-0.03em] text-ink">Sign in</h1>
              <p className="mt-1.5 text-sm text-ink-muted">Use the account issued by your VerifyFlow administrator.</p>

              {sessionEnd && (
                <p
                  role="status"
                  className={
                    sessionEnd === 'signed_out'
                      ? 'mt-5 rounded-xl bg-pass-bg px-3 py-2 text-[13px] text-pass'
                      : 'mt-5 rounded-xl bg-review-bg px-3 py-2 text-[13px] text-review'
                  }
                >
                  {SESSION_END_MESSAGES[sessionEnd]}
                </p>
              )}

              <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
                <TextField label="Work email" type="email" autoComplete="username" error={errors.email?.message} {...register('email')} />
                <TextField
                  label="Password"
                  type="password"
                  autoComplete="current-password"
                  error={errors.password?.message}
                  {...register('password')}
                />
                {formError && (
                  <motion.p
                    role="alert"
                    initial={reduce ? false : { opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: [0, -6, 6, -4, 4, 0] }}
                    transition={{ duration: 0.45 }}
                    className="rounded-xl bg-fail-bg px-3 py-2 text-[13px] font-medium text-fail"
                  >
                    {formError}
                  </motion.p>
                )}
                <Button type="submit" className="h-12 w-full rounded-xl text-[15px]" loading={isSubmitting}>
                  Sign in
                </Button>
              </form>
              {evaluator.data?.accounts.length ? (
                <div className="mt-6 rounded-2xl bg-[linear-gradient(135deg,rgba(124,92,255,.27),rgba(255,79,216,.19))] p-4 ring-1 ring-[#c5aaff]/55 shadow-[0_0_26px_-10px_rgba(255,79,216,.75)]">
                  <p className="mb-1 text-[13px] font-extrabold uppercase tracking-[0.11em] text-white">Auto-fill credentials</p>
                  <p className="mb-3 text-[12px] text-[#e9ddff]">Choose a role, then press Sign in.</p>
                  <div className="flex flex-wrap gap-2">
                    {evaluator.data.accounts.map((account) => (
                      <button key={account.role} type="button" onClick={() => {
                        setValue('email', account.email, { shouldValidate: true })
                        setValue('password', account.password, { shouldValidate: true })
                        setFormError(null)
                      }} className="inline-flex items-center gap-1.5 rounded-full bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] px-3.5 py-2 text-[12px] font-bold text-white shadow-[0_4px_14px_-4px_rgba(255,79,216,.8)] ring-1 ring-white/35 transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-[0_6px_20px_-3px_rgba(255,79,216,.95)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white" aria-label={`Auto-fill ${account.label} credentials`}>
                        <ShieldCheck className="size-3.5" aria-hidden /> {account.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="mt-6 flex flex-wrap gap-2 text-[11.5px] font-semibold text-ink-muted">
                  {['HttpOnly session', 'CSRF protected', 'Every action audited'].map((t) => (
                    <span key={t} className="inline-flex items-center gap-1 rounded-full bg-white/[0.06] px-2.5 py-1 ring-1 ring-white/10">
                      <ShieldCheck className="size-3.5 text-[#4ade80]" aria-hidden /> {t}
                    </span>
                  ))}
                </div>
              )}
              <p className="mt-6 text-xs leading-5 text-ink-subtle">Accounts are provisioned by administrators. There is no self-registration.</p>
            </div>
          </div>
        </motion.div>
      </main>
    </div>
  )
}
