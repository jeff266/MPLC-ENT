/**
 * Thin typed client over the FastAPI backend. One function per endpoint —
 * no generic "call anything" wrapper, so a change to a backend response
 * shape is a type error here, not a silent runtime surprise in a component.
 */
import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

// ---- Shared row/filter shapes -------------------------------------------

export interface AccountRow {
  account_id: string;
  account_name: string | null;
  website: string | null;
  state: string | null;
  industry: string | null;
  excluded: boolean;
  exclusion_reasons: string | null;
  vertical: string | null;
  segment: string | null;
  confidence: string | null;
  reason: string | null;
  edge_case: string | null;
}

export interface AccountsPage {
  run_date: string | null;
  total: number;
  page: number;
  page_size: number;
  rows: AccountRow[];
}

export interface AccountFilters {
  run_date?: string;
  vertical?: string;
  segment?: string;
  excluded?: boolean;
}

export async function fetchAccounts(
  filters: AccountFilters,
  page: number,
  pageSize: number,
): Promise<AccountsPage> {
  const { data } = await client.get<AccountsPage>("/accounts", {
    params: { ...filters, page, page_size: pageSize },
  });
  return data;
}

// ---- Review queues --------------------------------------------------------

export interface UnresolvedRow {
  account_id: string;
  account_name: string | null;
  vertical: string | null;
  reason: string | null;
  missing_data: string | null;
  edge_case: string | null;
}

export interface UnresolvedPage {
  run_date: string | null;
  total: number;
  page: number;
  page_size: number;
  rows: UnresolvedRow[];
}

export async function fetchUnresolvedQueue(
  vertical: string | undefined,
  page: number,
  pageSize: number,
): Promise<UnresolvedPage> {
  const { data } = await client.get<UnresolvedPage>("/review-queues/unresolved", {
    params: { vertical, page, page_size: pageSize },
  });
  return data;
}

// ---- Pipeline runs ----------------------------------------------------

export interface PipelineRunSummary {
  run_id: string;
  run_date: string;
  stage: string;
  status: "running" | "completed" | "failed";
  counts_json: string | null;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
}

export async function fetchRuns(): Promise<PipelineRunSummary[]> {
  const { data } = await client.get<PipelineRunSummary[]>("/runs");
  return data;
}

export interface AutoRunResult {
  run_date: string;
  summary: {
    stage_a: { safe_count: number; excluded_count: number };
    stage_b: { verticals: Record<string, number> };
    stage_c: { segments: Record<string, Record<string, number>> };
  };
  archived_files: Record<string, string>;
}

export async function triggerPipelineRunAuto(): Promise<AutoRunResult> {
  // No timeout override here deliberately: a real run takes ~5 minutes
  // against the full account universe (measured this session), and the
  // default axios timeout (0 = none) is correct for that, not a bug to fix.
  const { data } = await client.post<AutoRunResult>("/pipeline/run/auto");
  return data;
}

// ---- Find Enrichable Accounts -----------------------------------------

export interface FindEnrichableRequest {
  account_ids?: string[];
  filter?: AccountFilters;
  exclude_account_ids?: string[];
  created_by?: string;
}

export interface FindEnrichableResult {
  csvBlob: Blob;
  markedCount: number;
  missingCount: number;
}

export async function findEnrichableAccounts(
  req: FindEnrichableRequest,
): Promise<FindEnrichableResult> {
  const response = await client.post("/accounts/find-enrichable", req, {
    responseType: "blob",
  });
  return {
    csvBlob: response.data as Blob,
    markedCount: Number(response.headers["x-marked-count"] ?? 0),
    missingCount: Number(response.headers["x-missing-count"] ?? 0),
  };
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
