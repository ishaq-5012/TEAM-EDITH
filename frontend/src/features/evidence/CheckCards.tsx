import { ArrowUpRight } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Tilt } from "../../components/fx/Tilt";
import { cn } from "../../components/ui/cn";
import { StatusPill } from "../../components/ui/StatusPill";
import type { EvidenceFinding, EvidenceReference } from "../../lib/types";
import type { Selection } from "./EvidenceGraph";
import { OUTCOME, OUTCOME_LOOK, SEVERITY, groupIcon } from "./evidenceMeta";

interface Cluster {
  key: string;
  value: string;
  usable: boolean;
  refs: EvidenceReference[];
}

const STATUS_TEXT: Record<string, string> = {
  missing: "Not found",
  not_extracted: "Not extracted",
  invalid: "Invalid value",
};

/** Documents grouped by the value they hold: agreeing documents share a row, so a contradiction is a second row. */
function clusters(f: EvidenceFinding): Cluster[] {
  const map = new Map<string, Cluster>();
  for (const r of f.references) {
    const key =
      r.usable && r.effective_value
        ? `v:${r.effective_value}`
        : `s:${r.status}`;
    const value =
      r.usable && r.effective_value
        ? r.effective_value.replace(/\n/g, ", ")
        : (STATUS_TEXT[r.status] ?? r.status.replace("_", " "));
    const c = map.get(key) ?? {
      key,
      value,
      usable: !!(r.usable && r.effective_value),
      refs: [],
    };
    c.refs.push(r);
    map.set(key, c);
  }
  return [...map.values()].sort(
    (a, b) =>
      Number(b.usable) - Number(a.usable) || b.refs.length - a.refs.length,
  );
}

function CheckCard({
  finding: f,
  index,
  focus,
  onSelect,
}: {
  finding: EvidenceFinding;
  index: number;
  focus: string | null;
  onSelect: (s: Selection) => void;
}) {
  const reduce = useReducedMotion();
  const look = OUTCOME_LOOK[f.outcome];
  const Icon = groupIcon(f.group_key);
  const OutcomeIcon = look.icon;
  const groups = clusters(f);
  const byResult = f.relationships.reduce<Record<string, number>>(
    (acc, r) => ({ ...acc, [r.result]: (acc[r.result] ?? 0) + 1 }),
    {},
  );
  const distinct = groups.filter((g) => g.usable).length;

  return (
    <motion.article
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduce ? undefined : { opacity: 0, scale: 0.97 }}
      transition={{
        duration: 0.35,
        delay: reduce ? 0 : Math.min(index * 0.05, 0.3),
        ease: [0.22, 1, 0.36, 1],
      }}
      className="flex min-w-0"
      aria-labelledby={`check-${f.id}`}
    >
      <Tilt className="metal flex min-w-0 flex-1 flex-col rounded-3xl border border-line bg-surface shadow-[var(--shadow-card)]">
        <div
          className={cn("h-1.5 rounded-t-3xl bg-gradient-to-r", look.tile)}
          aria-hidden
        />
        <div className="flex items-start gap-3.5 px-5 pt-5">
          <span
            className={cn(
              "grid size-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br text-white shadow-md",
              look.tile,
            )}
          >
            <Icon className="size-5.5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h3
              id={`check-${f.id}`}
              className="text-[16px] font-semibold tracking-[-0.01em] text-ink"
            >
              {f.group_label}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <StatusPill status={OUTCOME[f.outcome].pill}>
                {OUTCOME[f.outcome].label}
              </StatusPill>
              <span className="rounded-full bg-navy-50 px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                {SEVERITY[f.severity]} severity
              </span>
            </div>
          </div>
          {f.outcome !== "pass" && (
            <div
              className="text-right"
              title="Priority: a deterministic ordering aid, not a compliance decision"
            >
              <p className="text-[22px] leading-none font-semibold tabular-nums text-ink">
                {f.priority_score}
              </p>
              <p className="text-[10.5px] tracking-wide text-ink-subtle uppercase">
                priority
              </p>
            </div>
          )}
        </div>

        <p className="px-5 pt-3 text-[12.5px] text-ink-muted">
          {distinct === 0
            ? "No document holds a usable value."
            : distinct === 1
              ? "All documents with a value agree."
              : `${distinct} different values across documents.`}
        </p>

        <ul
          className="mt-3 flex-1 space-y-2 px-5"
          aria-label={`Values for ${f.group_label}`}
        >
          {groups.map((g) => {
            const contested = distinct > 1 && g.usable;
            return (
              <li
                key={g.key}
                className={cn(
                  "rounded-2xl border px-3.5 py-2.5",
                  !g.usable
                    ? "border-dashed border-line bg-navy-50/50"
                    : contested
                      ? `border-transparent ${look.soft}`
                      : "border-line bg-surface",
                )}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <p
                    className={cn(
                      "min-w-0 truncate text-[13.5px]",
                      g.usable
                        ? "font-mono font-medium text-ink"
                        : "text-ink-subtle italic",
                    )}
                    title={g.value}
                  >
                    {g.value}
                  </p>
                  <span className="shrink-0 text-[11.5px] text-ink-subtle tabular-nums">
                    {g.refs.length} doc{g.refs.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {g.refs.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() =>
                        onSelect({
                          kind: "reference",
                          findingId: f.id,
                          id: r.id,
                        })
                      }
                      aria-label={`${f.group_label} in ${r.document_name}: ${g.value}`}
                      className={cn(
                        "max-w-[12rem] truncate rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors",
                        focus === r.document_id
                          ? "border-violet-600 bg-violet-600 text-white shadow-sm"
                          : "border-line bg-surface text-ink-muted hover:border-violet-400 hover:text-violet-700",
                        focus && focus !== r.document_id && "opacity-50",
                      )}
                      title={r.document_name}
                    >
                      {r.document_name}
                    </button>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3.5">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink-muted">
            <span className="font-medium text-ink">
              {f.relationships.length} comparisons
            </span>
            {(["pass", "fail", "review", "insufficient"] as const).map(
              (o) =>
                byResult[o] > 0 && (
                  <span key={o} className="inline-flex items-center gap-1">
                    <span
                      className="size-2 rounded-full"
                      style={{ background: OUTCOME_LOOK[o].ring }}
                      aria-hidden
                    />
                    {byResult[o]} {OUTCOME[o].short}
                  </span>
                ),
            )}
          </p>
          <button
            type="button"
            onClick={() => onSelect({ kind: "finding", findingId: f.id })}
            aria-label={`${f.group_label}: ${OUTCOME[f.outcome].label}, priority ${f.priority_score}. Open evidence`}
            className="group inline-flex items-center gap-1.5 rounded-full bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] px-3.5 py-1.5 text-[12.5px] font-semibold text-white shadow-[0_1px_0_rgb(255_255_255/0.3)_inset,0_8px_18px_-8px_rgb(109_68_236/0.9)] transition-[transform,box-shadow] hover:-translate-y-0.5 motion-reduce:hover:translate-y-0"
          >
            <OutcomeIcon className="size-3.5" aria-hidden /> Open evidence
            <ArrowUpRight
              className="size-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
              aria-hidden
            />
          </button>
        </div>
      </Tilt>
    </motion.article>
  );
}

export function CheckCards({
  findings,
  focus,
  onSelect,
}: {
  findings: EvidenceFinding[];
  focus: string | null;
  onSelect: (s: Selection) => void;
}) {
  return (
    <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
      <AnimatePresence mode="popLayout">
        {findings.map((f, i) => (
          <CheckCard
            key={f.id}
            finding={f}
            index={i}
            focus={focus}
            onSelect={onSelect}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
