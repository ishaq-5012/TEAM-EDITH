import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Tilt } from "../../components/fx/Tilt";
import { cn } from "../../components/ui/cn";
import { fetchPageImage } from "../../lib/api";
import type { EvidenceFinding } from "../../lib/types";
import type { GraphDocument } from "./EvidenceGraph";

const THUMB_SCALE = 0.35;

function Thumbnail({
  applicationId,
  documentId,
  name,
}: {
  applicationId: string;
  documentId: string;
  name: string;
}) {
  const q = useQuery({
    queryKey: ["page-image", documentId, 1, THUMB_SCALE],
    queryFn: () => fetchPageImage(applicationId, documentId, 1, THUMB_SCALE),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!q.data) return;
    const u = URL.createObjectURL(q.data);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [q.data]);
  if (q.isPending)
    return <div className="skeleton absolute inset-3 rounded-md" aria-hidden />;
  if (!url)
    return (
      <div className="absolute inset-0 grid place-items-center text-violet-500">
        <FileText className="size-9" aria-hidden />
      </div>
    );
  // The whole first page as a small sheet of paper, whatever its orientation.
  return (
    <img
      src={url}
      alt={`First page of ${name}`}
      className="absolute inset-x-0 top-3 bottom-0 mx-auto h-[calc(100%-0.75rem)] w-auto max-w-[calc(100%-1.5rem)] rounded-t-md bg-white object-contain object-top shadow-[0_6px_18px_rgb(17_22_58/0.18)] transition-transform duration-300 group-hover:-translate-y-1 group-hover:scale-[1.03]"
      draggable={false}
    />
  );
}

/** Per-document summary: values found, and how many stored comparisons involving it disagree. */
function stats(findings: EvidenceFinding[], documentId: string) {
  let found = 0;
  let differs = 0;
  for (const f of findings) {
    const mine = f.references.filter((r) => r.document_id === documentId);
    found += mine.filter((r) => r.usable).length;
    const ids = new Set(mine.map((r) => r.id));
    differs += f.relationships.filter(
      (rel) =>
        rel.result === "fail" &&
        (ids.has(rel.source_reference_id) || ids.has(rel.target_reference_id)),
    ).length;
  }
  return { found, differs };
}

export function DocumentRail({
  applicationId,
  documents,
  findings,
  focus,
  onFocus,
}: {
  applicationId: string;
  documents: GraphDocument[];
  findings: EvidenceFinding[];
  focus: string | null;
  onFocus: (id: string | null) => void;
}) {
  const reduce = useReducedMotion();
  return (
    <section aria-labelledby="doc-rail-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="doc-rail-title" className="text-[15px] font-semibold text-ink">
          Documents in this analysis{" "}
          <span className="ml-1 text-ink-subtle">{documents.length}</span>
        </h2>
        <p className="text-[12.5px] text-ink-muted">
          {focus ? (
            <button
              type="button"
              onClick={() => onFocus(null)}
              className="font-medium text-violet-700 hover:underline"
            >
              Clear document focus
            </button>
          ) : (
            "Select a document to highlight its values in every check."
          )}
        </p>
      </div>
      <ul
        className="-mx-1 flex snap-x gap-4 overflow-x-auto px-1 pt-1 pb-3"
        aria-label="Documents"
      >
        {documents.map((d, i) => {
          const s = stats(findings, d.id);
          const active = focus === d.id;
          return (
            <motion.li
              key={d.id}
              className="w-44 shrink-0 snap-start"
              initial={reduce ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.04, 0.3), duration: 0.35 }}
            >
              <Tilt className="rounded-2xl">
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onFocus(active ? null : d.id)}
                  className={cn(
                    "group block w-full rounded-2xl border bg-surface text-left shadow-[var(--shadow-card)] transition-[border-color,box-shadow]",
                    active
                      ? "border-violet-500 ring-4 ring-violet-500/20"
                      : "border-line hover:border-violet-300",
                  )}
                >
                  <div className="relative h-32 overflow-hidden rounded-t-2xl border-b border-line bg-[linear-gradient(160deg,var(--color-violet-100),var(--color-navy-50)_55%,var(--color-cyan-50))]">
                    <Thumbnail
                      applicationId={applicationId}
                      documentId={d.id}
                      name={d.name}
                    />
                    <span
                      className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-navy-950/25 to-transparent"
                      aria-hidden
                    />
                    {s.differs > 0 && (
                      <span className="absolute top-2 right-2 rounded-full bg-fail px-2 py-0.5 text-[10.5px] font-semibold text-white shadow">
                        {s.differs} differ
                      </span>
                    )}
                  </div>
                  <div className="px-3 py-2.5">
                    <p
                      className="truncate text-[12.5px] font-semibold text-ink"
                      title={d.name}
                    >
                      {d.name}
                    </p>
                    <p className="text-[11.5px] text-ink-subtle">
                      {s.found} values found
                    </p>
                  </div>
                </button>
              </Tilt>
            </motion.li>
          );
        })}
      </ul>
    </section>
  );
}
