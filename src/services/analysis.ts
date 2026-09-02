import { apiFetch } from "./api";

export interface AnalyzeRequest {
  analysis_id?: string;
  text?: string;
  policy_id?: string;
  policy?: Record<string, any>;
}

export interface AnalyzeResponse {
  analysis_id: string;
  total_clauses: number;
  results: Array<Record<string, any>>;
  policy_summary?: Record<string, any> | null;
}

export interface OCRInfo {
  used: boolean;
  method?: string;
  pages?: number;
  characters?: number;
}

export async function uploadContract(
  file: File
): Promise<{
  analysis_id: string;
  total_clauses: number;
  ocr_info?: OCRInfo;
}> {
  const fd = new FormData();
  fd.append("file", file);

  const res = await fetch(
    `${location.origin}/__bypass_cors__`,
    { method: "HEAD" }
  ).catch(() => undefined);

  // Directly call API; CORS handled server-side.
  const base =
    (import.meta as any).env?.VITE_API_URL ||
    "http://localhost:8000";

  const resp = await fetch(`${base}/upload`, {
    method: "POST",
    body: fd,
  });

  if (!resp.ok) {
    throw new Error(
      (await resp.text()) || "Upload failed"
    );
  }

  return (await resp.json()) as {
    analysis_id: string;
    total_clauses: number;
    ocr_info?: OCRInfo;
  };
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

export interface CompareResult {
  contract_1: Record<string, any>;
  contract_2: Record<string, any>;
  comparison: Record<string, any>;
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