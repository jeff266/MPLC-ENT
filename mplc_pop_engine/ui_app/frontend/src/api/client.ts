/**
 * Thin typed client over the FastAPI backend. One function per endpoint —
 * no generic "call anything" wrapper, so a change to a backend response
 * shape is a type error here, not a silent runtime surprise in a component.
 */
import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

// Without this, every useMutation onError handler across the app only ever
// sees axios's generic "Request failed with status code 503" — the actual
// FastAPI `detail` message (e.g. enrichment.DispatchError's "Neither
// DATABASE_URL nor SUPABASE_PASSWORD is set...") is silently dropped.
// Caught live (2026-11-13) via a real 503 from /accounts/check-already-enriched
// in this sandbox (no Supabase creds configured) — the UI showed the generic
// axios message instead of the actionable one. Fixes it for every endpoint,
// not just the new enrichment ones.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === "string" && detail) {
      error.message = detail;
    }
    return Promise.reject(error);
  },
);

// ---- Shared row/filter shapes -------------------------------------------

export interface AccountRow {
  account_id: string;
  account_name: string | null;
  website: string | null;
  state: string | null;
  country: string | null;
  operating_market: string | null;
  capacity: number | null;
  capacity_type: string | null;
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
  country?: string;
  operating_market?: string;
  capacity_type?: string;
  capacity_min?: number;
  capacity_max?: number;
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

export interface ClayMatchRow {
  id: number;
  clay_company_name: string | null;
  clay_website: string | null;
  classification: string;
  match_method: string | null;
  num_candidates: number;
}

export interface ClayAmbiguousPage {
  total: number;
  page: number;
  page_size: number;
  rows: ClayMatchRow[];
}

export async function fetchClayAmbiguousQueue(
  batchId: string | undefined,
  page: number,
  pageSize: number,
): Promise<ClayAmbiguousPage> {
  const { data } = await client.get<ClayAmbiguousPage>("/review-queues/clay-ambiguous", {
    params: { batch_id: batchId, page, page_size: pageSize },
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

// ---- Weekly file upload --------------------------------------------------

export interface UploadResult {
  saved: string[];
  deleted: string[];
  incoming_dir: string;
}

export async function uploadWeeklyFiles(files: File[]): Promise<UploadResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const { data } = await client.post<UploadResult>("/pipeline/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export interface IncomingFile {
  filename: string;
  size_bytes: number;
  modified_at: number;
  matched_role: string | null;
}

export async function fetchIncomingFiles(): Promise<{ files: IncomingFile[] }> {
  const { data } = await client.get<{ files: IncomingFile[] }>("/pipeline/incoming");
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

// ---- Step 2: Run Vertical Pipelines (local dispatch) ----------------------
// Jeff (2026-11-13): "step 2 - take selected accounts and run it through
// vertical pipelines + check already enriched accounts to not burn
// credits." Vertical is a user choice for the dispatch job — see
// backend/enrichment.py for why this isn't auto-routed per account.

export interface ToggleableChannel {
  key: string; // e.g. "youtube" — passed back in disabled_channels to turn it off
  label: string; // display label, e.g. "YouTube video search"
}

export interface DispatchableVertical {
  key: string; // unified_worker.py's CLI arg, e.g. "corporate"
  label: string; // display label, e.g. "Corporations"
  toggleable_channels: ToggleableChannel[]; // paid channels this vertical can disable per-run
}

export async function fetchDispatchableVerticals(): Promise<DispatchableVertical[]> {
  const { data } = await client.get<DispatchableVertical[]>("/enrichment/verticals");
  return data;
}

export interface EnrichmentSelectionRequest {
  account_ids?: string[];
  filter?: AccountFilters;
  exclude_account_ids?: string[];
  vertical: string;
  created_by?: string;
  disabled_channels?: string[]; // paid channel keys to turn OFF for this dispatch
}

export interface AlreadyEnrichedPreview {
  vertical: string;
  total_selected: number;
  already_enriched_count: number;
  to_dispatch_count: number;
  already_enriched_account_ids: string[];
}

export async function checkAlreadyEnriched(
  req: EnrichmentSelectionRequest,
): Promise<AlreadyEnrichedPreview> {
  const { data } = await client.post<AlreadyEnrichedPreview>(
    "/accounts/check-already-enriched",
    req,
  );
  return data;
}

export interface DispatchResult {
  job_id: string;
  vertical: string;
  run_date: string;
  total_requested: number;
  total_dispatched: number;
  skipped_already_enriched: number;
  missing_account_ids: string[];
  pid: number;
  batch_file: string;
}

export async function dispatchEnrichment(
  req: EnrichmentSelectionRequest,
): Promise<DispatchResult> {
  const { data } = await client.post<DispatchResult>("/enrichment/dispatch", req);
  return data;
}

// ---- Step 3: Pipeline Monitor ---------------------------------------------

export interface EnrichmentJobSummary {
  job_id: string;
  vertical: string;
  display_vertical: string;
  run_date: string;
  status: string;
  total_requested: number;
  total_dispatched: number;
  skipped_already_enriched: number;
  pid: number | null;
  started_at: string;
  finished_at: string | null;
  created_by: string | null;
}

export async function fetchEnrichmentJobs(): Promise<EnrichmentJobSummary[]> {
  const { data } = await client.get<EnrichmentJobSummary[]>("/enrichment/jobs");
  return data;
}

export interface EnrichmentResultRow {
  account_id: string;
  account_name: string | null;
  status: string;
  is_prospect: boolean | null;
  enrichment_result: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface EnrichmentHeartbeat {
  id: number;
  droplet: string | null;
  worker_id: string;
  vertical: string;
  pid: number;
  batch_file: string;
  records_total: number;
  records_done: number;
  last_account_name: string | null;
  last_error: string | null;
  started_at: string;
  last_seen_at: string;
}

export interface JobProgress {
  job_id: string;
  vertical: string;
  display_vertical: string;
  run_date: string;
  status: string;
  process_alive: boolean;
  total_dispatched: number;
  skipped_already_enriched: number;
  status_counts: Record<string, number>;
  cost_so_far: number;
  heartbeat: EnrichmentHeartbeat | null;
  results: EnrichmentResultRow[];
  supabase_error: string | null;
}

export async function fetchJobProgress(jobId: string): Promise<JobProgress> {
  const { data } = await client.get<JobProgress>(`/enrichment/jobs/${jobId}/progress`);
  return data;
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
