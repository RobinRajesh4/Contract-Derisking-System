import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, BookOpen } from "lucide-react";
import { getAnalysis } from "@/services/analysis";

export interface DocumentViewerProps {
  analysisId: string | null;
  highlightedClauseId: string | number | null;
  /** Optional label shown when no contract is selected */
  emptyLabel?: string;
}

export default function DocumentViewer({
  analysisId,
  highlightedClauseId,
  emptyLabel = "Select a specific contract to view the document and jump to referenced clauses.",
}: DocumentViewerProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analysis-clauses", analysisId],
    queryFn: () => getAnalysis(analysisId as string),
    enabled: !!analysisId,
  });

  const clauseRefs = useRef<Record<string | number, HTMLDivElement | null>>({});

  /* Scroll to + flash the highlighted clause whenever it changes */
  useEffect(() => {
    if (highlightedClauseId == null) return;

    const el = clauseRefs.current[highlightedClauseId];
    if (!el) return;

    el.classList.remove("clause-highlighted");
    void el.offsetWidth; // force reflow so animation re-fires
    el.classList.add("clause-highlighted");

    el.scrollIntoView({ behavior: "smooth", block: "center" });

    const timer = setTimeout(() => {
      el.classList.remove("clause-highlighted");
    }, 3200);

    return () => clearTimeout(timer);
  }, [highlightedClauseId]);

  /* ── Empty state ── */
  if (!analysisId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-muted-foreground">
        <BookOpen className="h-12 w-12 opacity-30" />
        <div className="text-center">
          <p className="text-sm font-medium">No contract selected</p>
          <p className="mt-1 text-xs opacity-70 max-w-[200px] mx-auto">{emptyLabel}</p>
        </div>
      </div>
    );
  }

  /* ── Loading ── */
  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-xs">Loading document…</p>
        </div>
      </div>
    );
  }

  /* ── Error ── */
  if (isError || !data) {
    return (
      <div className="flex h-full items-center justify-center text-destructive">
        <p className="text-sm">Failed to load document.</p>
      </div>
    );
  }

  const clauses: Array<{ id: string | number; text: string }> =
    data.clauses ?? data.results ?? [];

  const filename: string = data.filename ?? "Contract";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Document header */}
      <div className="shrink-0 border-b bg-muted/50 px-5 py-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          <span className="truncate text-sm font-semibold">{filename}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {clauses.length} clause{clauses.length !== 1 ? "s" : ""}
        </p>
      </div>

      {/* Clause list */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {clauses.map((clause) => (
          <div
            key={clause.id}
            ref={(el) => {
              clauseRefs.current[clause.id] = el;
            }}
            data-clause-id={clause.id}
            className="group relative rounded-md border border-border/40 bg-background p-4 text-sm leading-relaxed transition-colors hover:border-border"
          >
            <span className="mb-2 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold text-muted-foreground">
              §{clause.id}
            </span>
            <p className="whitespace-pre-wrap text-foreground/90">{clause.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
