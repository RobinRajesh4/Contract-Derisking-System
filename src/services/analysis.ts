import { apiFetch, errorMessage, getBaseUrl } from "./api";
import { buildCompiledPolicy } from "@/policy/buildPolicy";

export interface AnalyzeRequest {
  analysis_id?: string;
  text?: string;
  policy_id?: string;
  policy?: Record<string, any>;
}

export interface AnalysisQuality {
  complete: boolean;
  fallback_clauses?: Array<string | number>;
  fallback_policy_checks?: number;
  message?: string | null;
}

export interface AnalyzeResponse {
  analysis_id: string;
  total_clauses: number;
  results: Array<Record<string, any>>;
  policy_summary?: Record<string, any> | null;
  analysis_quality?: AnalysisQuality | null;
}

export interface OCRInfo {
  used: boolean;
  method?: string;
  pages?: number;
  characters?: number;
  error?: string;
}

export interface UploadResult {
  analysis_id: string;
  total_clauses: number;
  ocr_info?: OCRInfo;
  reprocessed?: boolean;
  clauses_changed?: boolean;
  parse_quality?: { ok: boolean; ratio: number; missing_sample?: string[] };
  search_index?: { ok: boolean; passages: number; error?: string | null };
  /** Set when the same file was already stored under another name. */
  duplicate_of?: string | null;
}

export async function uploadContract(file: File): Promise<UploadResult> {
  const fd = new FormData();
  // Just the file name: in a folder upload the browser would otherwise
  // send "Folder/sub/file.pdf".
  fd.append("file", file, file.name);

  const resp = await fetch(`${getBaseUrl()}/upload`, {
    method: "POST",
    body: fd,
  });

  if (!resp.ok) {
    throw new Error(await errorMessage(resp));
  }

  return (await resp.json()) as UploadResult;
}

export async function analyze(
  req: AnalyzeRequest
): Promise<AnalyzeResponse> {
  return apiFetch<AnalyzeResponse>(
    `/analyze`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(req),
    }
  );
}

export async function analyzeById(
  analysis_id: string
): Promise<AnalyzeResponse> {
  return analyze({ analysis_id });
}

export async function listAnalyses(): Promise<any[]> {
  return apiFetch<any[]>(`/clauses`);
}

export async function getAnalysis(
  analysis_id: string
): Promise<any> {
  return apiFetch<any>(
    `/clauses/${analysis_id}`
  );
}

export async function savePolicy(
  policy: Record<string, any>
): Promise<{
  policy_id: string;
  status: string;
}> {
  return apiFetch(`/policy`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(policy),
  });
}

export async function getPolicy(
  policy_id: string
): Promise<any> {
  return apiFetch<any>(
    `/policy/${policy_id}`
  );
}

export async function listPolicies(): Promise<any[]> {
  return apiFetch<any[]>(`/policies`);
}

export interface ContractSummary {
  executive_summary?: string;
  key_obligations?: string[];
  major_risks?: string[];
  recommendations?: string[];
  overall_sentiment?:
    | "Favorable"
    | "Balanced"
    | "Unfavorable"
    | string;
  [key: string]: any;
}

export async function getSummary(
  analysis_id: string
): Promise<ContractSummary> {
  return apiFetch<ContractSummary>(
    `/summary/${analysis_id}`,
    {
      method: "POST",
    }
  );
}

export interface DomainRiskStats {
  total: number;
  high: number;
  medium: number;
  low: number;
  unclassified: number;
  normalized_risk_score: number;
  high_risk_percentage: number;
}

export interface ContractRiskStats {
  analysis_id?: string;
  filename?: string;
  created_at?: string;
  updated_at?: string;
  total_clauses: number;
  classified_clauses: number;
  unclassified_clauses: number;
  high_risk: number;
  medium_risk: number;
  low_risk: number;
  high_risk_percentage: number;
  medium_risk_percentage: number;
  low_risk_percentage: number;
  normalized_risk_score: number;
  weighted_risk_points: number;
  domains: Record<string, DomainRiskStats>;
}

export interface DomainComparison {
  domain: string;
  contract_1: DomainRiskStats;
  contract_2: DomainRiskStats;
  score_difference: number;
}

export interface ExtractedTermMatch {
  value: string;
  clause_id?: string | number;
  clause_text: string;
}

export interface ExtractedTerm {
  label: string;
  value: string;
  clause_id?: string | number;
  clause_text: string;
  all_matches: ExtractedTermMatch[];
  has_conflict: boolean;
}

export interface TermComparison {
  key: string;
  label: string;
  contract_1: ExtractedTerm | null;
  contract_2: ExtractedTerm | null;
  status:
    | "same"
    | "different"
    | "only_contract_1"
    | "only_contract_2"
    | "missing_both";
}


export interface CompareResult {
  contract_1: ContractRiskStats;
  contract_2: ContractRiskStats;
  comparison: {
    clause_difference: number;
    high_risk_difference: number;
    normalized_score_difference: number;
    high_risk_rate_difference: number;
    safer_contract: string | null;
    is_tie: boolean;
    /** Contracts that can't be compared because they aren't risk-analyzed. */
    not_analyzed?: string[];
    verdict: string;
    verdict_reasons: string[];
    domain_comparison: DomainComparison[];
    term_comparison: TermComparison[];
  };
}

export async function compareAnalyses(
  analysis_id_1: string,
  analysis_id_2: string
): Promise<CompareResult> {
  return apiFetch<CompareResult>(
    `/compare`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        analysis_id_1,
        analysis_id_2,
      }),
    }
  );
}

/** Risk-analyze a stored contract with the current policy library. */
export function runAnalysis(analysis_id: string): Promise<AnalyzeResponse> {
  const policy = buildCompiledPolicy({ policyId: "ui_policy_v1", riskThreshold: 15 });
  return analyze({ analysis_id, policy });
}

/** Warnings worth telling the user about after an upload. */
export function uploadWarnings(u: UploadResult): string[] {
  const notes: string[] = [];
  if (u.duplicate_of) {
    notes.push(`Same file as "${u.duplicate_of}", which is already stored; no duplicate was created.`);
  } else if (u.reprocessed) {
    notes.push(
      u.clauses_changed
        ? "This file was already uploaded; its record was re-processed and updated."
        : "This file was already uploaded; the existing record was updated (no duplicate created)."
    );
  }
  if (u.parse_quality && u.parse_quality.ok === false) {
    notes.push(
      `Only about ${Math.round((u.parse_quality.ratio || 0) * 100)}% of the document's text ended up in clauses. Check the clauses before relying on this analysis.`
    );
  }
  if (u.ocr_info?.error) notes.push(u.ocr_info.error);
  if (u.search_index && u.search_index.ok === false && u.search_index.error) notes.push(u.search_index.error);
  return notes;
}
