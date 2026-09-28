// The backend listens on 8001 (backend/run_server.py). Override with
// VITE_API_URL in a .env file if it runs elsewhere.
const BASE_URL = (import.meta as any).env?.VITE_API_URL || "http://localhost:8001";

/**
 * A readable message from a failed response: FastAPI's {"detail": "..."}
 * or its validation list, plain text, or the status line - never a raw
 * JSON dump or "[object Object]".
 */
export async function errorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  let detail: any = text;
  try {
    const body = JSON.parse(text);
    detail = body?.detail ?? body?.message ?? body;
  } catch {
    /* plain text */
  }
  if (Array.isArray(detail)) {
    detail = detail.map((d) => (typeof d === "string" ? d : d?.msg || JSON.stringify(d))).join("; ");
  } else if (detail && typeof detail === "object") {
    detail = JSON.stringify(detail);
  }
  const msg = String(detail || "").trim();
  return msg || `${res.status} ${res.statusText}`.trim() || "Request failed";
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

export function getBaseUrl() {
  return BASE_URL;
}
