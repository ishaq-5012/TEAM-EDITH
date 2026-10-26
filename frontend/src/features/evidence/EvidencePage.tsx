import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  FolderSearch,
  LayoutGrid,
  List,
  Network,
  Play,
  RefreshCw,
  Rows3,
  Sparkles,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useBreadcrumbTrail } from "../../components/layout/crumbStore";
import { NetworkArt } from "../../components/art/NetworkArt";
import { Tilt } from "../../components/fx/Tilt";
import { Button } from "../../components/ui/Button";
import { cn } from "../../components/ui/cn";
import { Drawer } from "../../components/ui/Drawer";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "../../components/ui/States";
import { ApiError, api, errorMessage } from "../../lib/api";
import { panelSwap } from "../../lib/motion";
import type { Outcome } from "../../lib/types";
import { CheckCards } from "./CheckCards";
import { DocumentRail } from "./DocumentRail";
import { evidenceDetail } from "./EvidenceDetailPanel";
import { EvidenceGraph, documentsOf, type Selection } from "./EvidenceGraph";
import { CountUp, EvidenceHero } from "./EvidenceHero";
import { EvidenceList } from "./EvidenceList";
import { NetworkView } from "./NetworkView";
import {
  OUTCOME,
  OUTCOME_LOOK,
  OUTCOME_ORDER,
  groupIcon,
} from "./evidenceMeta";

type View = "overview" | "network" | "matrix" | "list";
const VIEW_KEY = "vf.evidence.view";
const VIEWS: {
  key: View;
  label: string;
  icon: typeof Network;
  hint: string;
}[] = [
  {
    key: "overview",
    label: "Overview",
    icon: LayoutGrid,
    hint: "Each check, with documents grouped by the value they hold",
  },
  {
    key: "network",
    label: "Network",
    icon: Network,
    hint: "One check at a time: documents on a ring, comparisons as links",
  },
  {
    key: "matrix",
    label: "Matrix",
    icon: Rows3,
    hint: "Every check against every document, coloured by agreement",
  },
  {
    key: "list",
    label: "List",
    icon: List,
    hint: "Findings ordered by priority, as a plain list",
  },
];

function readView(): View {
  try {
    const v = sessionStorage.getItem(VIEW_KEY);
    return v === "graph"
      ? "matrix"
      : VIEWS.some((x) => x.key === v)
        ? (v as View)
        : "overview";
  } catch {
    return "overview";
  }
}

export function EvidencePage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const reduce = useReducedMotion();
  const app = useQuery({
    queryKey: ["application", id],
    queryFn: () => api.application(id),
  });
  const evidence = useQuery({
    queryKey: ["evidence", id],
    queryFn: () => api.evidence(id),
    retry: false,
  });
  const [selection, setSelection] = useState<Selection>(null);
  const [view, setView] = useState<View>(readView);
  const [filter, setFilter] = useState<Outcome | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useBreadcrumbTrail(
    app.data
      ? [
          { label: app.data.reference, to: `/applications/${id}` },
          { label: "Evidence graph" },
        ]
      : undefined,
  );
  useEffect(() => {
    document.title = `Evidence ${app.data?.reference ?? ""} · VerifyFlow AI`;
  }, [app.data?.reference]);

  const run = useMutation({
    mutationFn: (force: boolean) => api.runEvidenceAnalysis(id, force),
    onSuccess: (data) => {
      qc.setQueryData(["evidence", id], data);
      setActionError(null);
      setSelection(null);
      setNotice(
        data.reused
          ? "Inputs have not changed since the current analysis, so it was reused."
          : "Analysis completed.",
      );
    },
    onError: (e) => setActionError(errorMessage(e)),
  });

  const v = evidence.data;
  const ordered = useMemo(
    () =>
      v
        ? [...v.findings].sort((a, b) => b.priority_score - a.priority_score)
        : [],
    [v],
  );
  const shown = useMemo(
    () => (filter ? ordered.filter((f) => f.outcome === filter) : ordered),
    [ordered, filter],
  );
  const docs = useMemo(() => (v ? documentsOf(v.findings) : []), [v]);
  const detail = v ? evidenceDetail(id, v.findings, selection) : null;
  const selectedFinding =
    selection && v?.findings.find((f) => f.id === selection.findingId);

  const switchView = (next: View) => {
    setView(next);
    try {
      sessionStorage.setItem(VIEW_KEY, next);
    } catch {
      // Remembering the view is a convenience only.
    }
  };

  if (app.isError) {
    if (app.error instanceof ApiError && app.error.status === 404) {
      return (
        <EmptyState
          icon={<FolderSearch className="size-6" />}
          title="Application not found"
          action={
            <Link
              to="/evidence"
              className="text-sm font-medium text-violet-700 hover:underline"
            >
              Back to evidence
            </Link>
          }
        >
          It doesn’t exist, or you don’t have access to it.
        </EmptyState>
      );
    }
    return <ErrorState error={app.error} onRetry={() => app.refetch()} />;
  }

  const notAnalyzed =
    evidence.isError &&
    evidence.error instanceof ApiError &&
    evidence.error.code === "not_analyzed";
  const canRun = v
    ? v.can_analyze
    : !!app.data &&
      app.data.permissions.can_edit &&
      app.data.status !== "archived";

  const actions = canRun && (
    <>
      <button
        type="button"
        onClick={() => run.mutate(false)}
        disabled={run.isPending}
        className="inline-flex h-10 items-center gap-2 rounded-full bg-[linear-gradient(120deg,#ff9933,#ff4fd8_52%,#7c5cff)] px-5 text-[13.5px] font-semibold text-white shadow-[0_1px_0_rgb(255_255_255/0.35)_inset,0_0_22px_-4px_rgb(255_79_216/0.65),0_10px_24px_-10px_rgb(255_153_51/0.7)] transition-transform hover:-translate-y-0.5 disabled:opacity-70"
      >
        {run.isPending && run.variables === false ? (
          <RefreshCw className="size-4 animate-spin" aria-hidden />
        ) : (
          <Play className="size-4" aria-hidden />
        )}
        {v ? "Re-run analysis" : "Run analysis"}
      </button>
      {v && (
        <button
          type="button"
          onClick={() => run.mutate(true)}
          disabled={run.isPending}
          className="glass inline-flex h-10 items-center gap-2 rounded-full px-4 text-[13px] font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-70"
        >
          {run.isPending && run.variables === true && (
            <RefreshCw className="size-4 animate-spin" aria-hidden />
          )}
          Force re-run
        </button>
      )}
    </>
  );

  return (
    <div className="pb-12">
      <EvidenceHero
        reference={app.data?.reference}
        title={app.data?.title}
        view={v}
        actions={actions}
      />

      <div className="space-y-7">
        <AnimatePresence>
          {actionError && (
            <motion.p
              key="err"
              role="alert"
              variants={panelSwap}
              initial="initial"
              animate="animate"
              exit="exit"
              className="rounded-2xl bg-fail-bg px-4 py-3 text-[13px] text-fail"
            >
              {actionError}
            </motion.p>
          )}
          {notice && !actionError && (
            <motion.p
              key="ok"
              role="status"
              variants={panelSwap}
              initial="initial"
              animate="animate"
              exit="exit"
              className="flex items-center gap-2 rounded-2xl bg-info-bg px-4 py-3 text-[13px] text-info"
            >
              <Sparkles className="size-4" aria-hidden /> {notice}
            </motion.p>
          )}
        </AnimatePresence>

        {evidence.isPending ? (
          <LoadingRows rows={6} label="Loading evidence" />
        ) : notAnalyzed ? (
          <section className="relative overflow-hidden rounded-3xl border border-line bg-surface px-6 py-14 text-center shadow-[var(--shadow-card)]">
            <div className="hero-surface mx-auto mb-6 h-44 max-w-md rounded-3xl">
              <NetworkArt className="absolute inset-0 size-full" />
            </div>
            <EmptyState
              icon={<Network className="size-6" />}
              title="No analysis yet"
              action={
                canRun && (
                  <Button
                    onClick={() => run.mutate(false)}
                    loading={run.isPending}
                  >
                    Run analysis
                  </Button>
                )
              }
            >
              The analysis compares each configured field across this
              application’s documents using deterministic rules. Upload and
              extract documents first.
            </EmptyState>
          </section>
        ) : evidence.isError ? (
          <ErrorState
            error={evidence.error}
            onRetry={() => evidence.refetch()}
          />
        ) : (
          v && (
            <>
              {v.stale && (
                <p
                  role="status"
                  className="flex gap-3 rounded-2xl border border-review/30 bg-review-bg px-5 py-4 text-[13px] text-review"
                >
                  <AlertTriangle
                    className="mt-0.5 size-4 shrink-0"
                    aria-hidden
                  />
                  Documents, extractions, corrections or comparison settings
                  have changed since this analysis. It is shown as stored;
                  re-run it to include the changes.
                </p>
              )}

              {/* Outcome tiles double as filters */}
              <section
                aria-label="Filter checks by outcome"
                className="grid grid-cols-2 gap-4 lg:grid-cols-4"
              >
                {OUTCOME_ORDER.map((o, i) => {
                  const look = OUTCOME_LOOK[o];
                  const Icon = look.icon;
                  const n = v.analysis.summary[o] ?? 0;
                  const on = filter === o;
                  return (
                    <motion.button
                      key={o}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setFilter(on ? null : o)}
                      initial={reduce ? false : { opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.05 + i * 0.06, duration: 0.4 }}
                      className="group flex rounded-3xl text-left"
                    >
                      <Tilt
                        className={cn(
                          "metal w-full rounded-3xl border bg-surface p-5 shadow-[var(--shadow-card)]",
                          on ? "ring-4 ring-violet-500/40" : "border-line",
                        )}
                      >
                        <div className="flex items-start justify-between">
                          <span
                            className={cn(
                              "grid size-11 place-items-center rounded-2xl bg-gradient-to-br text-white shadow-md transition-transform group-hover:scale-110 group-hover:-rotate-6 motion-reduce:group-hover:scale-100 motion-reduce:group-hover:rotate-0",
                              look.tile,
                            )}
                          >
                            <Icon className="size-5" aria-hidden />
                          </span>
                          <span
                            className={cn(
                              "rounded-full px-2 py-0.5 text-[11px] font-medium",
                              on
                                ? "bg-violet-600 text-white"
                                : "bg-navy-50 text-ink-subtle",
                            )}
                          >
                            {on ? "Filtered" : "Filter"}
                          </span>
                        </div>
                        <p className="mt-4 text-[34px] leading-none font-semibold tracking-[-0.03em] text-ink">
                          <CountUp value={n} />
                          <span className="sr-only">{n}</span>
                        </p>
                        <p
                          className={cn(
                            "mt-1.5 text-[13px] font-medium",
                            look.text,
                          )}
                        >
                          {OUTCOME[o].label}
                        </p>
                      </Tilt>
                    </motion.button>
                  );
                })}
              </section>

              <DocumentRail
                applicationId={id}
                documents={docs}
                findings={v.findings}
                focus={focus}
                onFocus={setFocus}
              />

              <section aria-labelledby="checks-title" className="space-y-5">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <h2
                      id="checks-title"
                      className="text-[20px] font-semibold tracking-[-0.02em] text-ink"
                    >
                      Checks{" "}
                      {filter && (
                        <span className="text-ink-subtle">
                          · {OUTCOME[filter].label}
                        </span>
                      )}
                    </h2>
                    <p className="mt-0.5 text-[13px] text-ink-muted">
                      {VIEWS.find((x) => x.key === view)?.hint}
                    </p>
                  </div>
                  <div
                    role="radiogroup"
                    aria-label="Evidence view"
                    className="relative inline-flex max-w-full overflow-x-auto rounded-full border border-line bg-surface p-1 shadow-[var(--shadow-card)]"
                  >
                    {VIEWS.map(({ key, label, icon: Icon }) => (
                      <button
                        key={key}
                        role="radio"
                        aria-checked={view === key}
                        onClick={() => switchView(key)}
                        className={cn(
                          "relative inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-[13px] font-medium transition-colors",
                          view === key
                            ? "text-white"
                            : "text-ink-muted hover:text-ink",
                        )}
                      >
                        {view === key && (
                          <motion.span
                            layoutId="evidence-view-pill"
                            className="absolute inset-0 rounded-full bg-gradient-to-r from-navy-900 to-violet-700"
                            transition={
                              reduce
                                ? { duration: 0 }
                                : {
                                    type: "spring",
                                    stiffness: 480,
                                    damping: 38,
                                  }
                            }
                            aria-hidden
                          />
                        )}
                        <Icon className="relative size-4" aria-hidden />
                        <span className="relative">{label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Enter-only: the chosen view appears at once and fades in; nothing waits on an exit animation. */}
                <motion.div
                  key={view}
                  variants={panelSwap}
                  initial="initial"
                  animate="animate"
                >
                  {shown.length === 0 ? (
                    <p className="rounded-3xl border border-dashed border-line bg-surface px-6 py-12 text-center text-[13.5px] text-ink-muted">
                      No checks with this outcome.{" "}
                      <button
                        type="button"
                        className="font-medium text-violet-700 hover:underline"
                        onClick={() => setFilter(null)}
                      >
                        Show all checks
                      </button>
                    </p>
                  ) : view === "overview" ? (
                    <CheckCards
                      findings={shown}
                      focus={focus}
                      onSelect={setSelection}
                    />
                  ) : view === "network" ? (
                    <NetworkView
                      findings={shown}
                      selection={selection}
                      focus={focus}
                      onSelect={setSelection}
                      onFocus={setFocus}
                    />
                  ) : view === "matrix" ? (
                    <div className="space-y-3">
                      <EvidenceGraph
                        findings={shown}
                        selection={selection}
                        onSelect={setSelection}
                      />
                      <p className="text-[12px] text-ink-subtle">
                        Rows are checks and columns are documents (D1, D2, …;
                        red labels have a difference). Select a document to
                        narrow its column, a value to see its source, or a
                        comparison chip to see the two values side by side.
                      </p>
                    </div>
                  ) : (
                    <EvidenceList
                      findings={shown}
                      selection={selection}
                      onSelect={setSelection}
                    />
                  )}
                </motion.div>
              </section>
            </>
          )
        )}
      </div>

      <Drawer
        open={!!detail}
        onClose={() => setSelection(null)}
        title={detail?.title}
        eyebrow={detail?.eyebrow}
        icon={
          selectedFinding
            ? (() => {
                const I = groupIcon(selectedFinding.group_key);
                return <I className="size-5" aria-hidden />;
              })()
            : undefined
        }
      >
        <div aria-live="polite">
          <motion.div
            key={
              selection
                ? `${selection.kind}:${"id" in selection ? selection.id : selection.findingId}`
                : "none"
            }
            variants={panelSwap}
            initial="initial"
            animate="animate"
          >
            {detail?.body}
          </motion.div>
        </div>
      </Drawer>

      {run.isPending && (
        <p role="status" className="sr-only">
          Running analysis
        </p>
      )}
    </div>
  );
}
