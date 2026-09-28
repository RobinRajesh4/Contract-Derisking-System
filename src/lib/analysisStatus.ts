/**
 * Whether a contract's risk numbers can be trusted.
 *
 * A contract with no risk analysis has no risky clauses on record, which
 * every page used to show as "Low risk" / 0 high-risk clauses. That
 * happens when /analyze failed, and after a re-upload or re-index
 * changed the clauses (the old results no longer match, so they are
 * cleared). An analysis where the AI server failed for some clauses is
 * "partial": those clauses were scored by keyword matching instead.
 */
export type AnalysisState = "analyzed" | "partial" | "not_analyzed";

/** The fields of a stored contract record this module looks at. */
export interface AnalysisRecordLike {
  status?: string;
  results?: unknown[] | null;
  analysis_quality?: { complete?: boolean; message?: string | null } | null;
}

export function analysisState(a: AnalysisRecordLike | null | undefined): AnalysisState {
  const results = a?.results;
  if (a?.status !== "analyzed" || !Array.isArray(results) || results.length === 0) {
    return "not_analyzed";
  }
  if (a?.analysis_quality && a.analysis_quality.complete === false) {
    return "partial";
  }
  return "analyzed";
}

export function isAnalyzed(a: AnalysisRecordLike | null | undefined): boolean {
  return analysisState(a) !== "not_analyzed";
}

export const NOT_ANALYZED_TEXT =
  "Not risk-analyzed yet. Its risk figures are unknown, not low. Run the analysis from the contract's page.";

export function partialText(a: AnalysisRecordLike | null | undefined): string {
  return (
    a?.analysis_quality?.message ||
    "Some clauses were scored by keyword matching because the AI server didn't respond. Re-run the analysis."
  );
}
