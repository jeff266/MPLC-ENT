/**
 * Thin typed client over the FastAPI backend. One function per endpoint —
 * no generic "call anything" wrapper, so a change to a backend response
 * shape is a type error here, not a silent runtime surprise in a component.
 */
import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

const TOKEN_KEY = "pop_engine_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Attach the token to every request. Added 2026-11-14 alongside the
// backend's whole-app auth middleware (main.py's require_auth) -- every
// endpoint except /auth/login, /auth/signup, /health now 401s without
// this header.
client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On a 401 from anything other than the login/signup calls themselves
// (those legitimately 401 on wrong credentials, not an expired session),
// clear the stale token and reload so App.tsx's auth check sends the
// person back to the login screen, instead of the UI quietly continuing
// to issue requests that will all keep failing.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error?.config?.url ?? "";
    const isAuthEndpoint = url.includes("/auth/login") || url.includes("/auth/signup");
    if (error?.response?.status === 401 && !isAuthEndpoint) {
      clearToken();
      window.location.reload();
    }
    return Promise.reject(error);
  },
);

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

// Pre-dispatch cost preview (2026-11-14, Jeff: "are we showing an estimate
// of how much each run and total will cost?" -- this is that estimate,
// built from this vertical's own historical $/account in Cost Tracker,
// never a guessed rate).
export interface CostEstimateRequest {
  vertical: string;
  account_count: number;
  disabled_channels?: string[];
}

export interface ExcludedChannelCost {
  channel: string;
  historical_cost_per_account: number;
}

export type CostEstimate =
  | { estimable: false; vertical: string; account_count: number; reason: string }
  | {
      estimable: true;
      vertical: string;
      account_count: number;
      cost_per_account: number;
      estimated_total_cost: number;
      based_on_historical_accounts: number;
      directional: boolean;
      excluded_channels: ExcludedChannelCost[];
      note: string;
    };

export async function fetchCostEstimate(req: CostEstimateRequest): Promise<CostEstimate> {
  const params = new URLSearchParams({
    vertical: req.vertical,
    account_count: String(req.account_count),
  });
  if (req.disabled_channels && req.disabled_channels.length > 0) {
    params.set("disabled_channels", req.disabled_channels.join(","));
  }
  const { data } = await client.get<CostEstimate>(`/enrichment/cost-estimate?${params.toString()}`);
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

// ---- Cost Tracker -----------------------------------------------------
// Per claude/Cost_Tracker_Design.md and Jeff's 2026-11-14 decisions:
// on-demand, cumulative (all-time, no date filter), no separate rollup
// table on the backend -- this just reflects GET /cost-tracker's shape.

export interface CostTrackerVerticalSummary {
  vertical: string;
  accounts_processed: number;
  prospect_count: number;
  suspect_count: number;
  rows_with_cost: number;
  total_cost: number;
  is_prospect_mismatches: number;
  cost_per_account: number | null;
  cost_per_prospect: number | null;
  cost_per_lead: number | null;
}

export interface CostTrackerChannelRow {
  vertical: string;
  channel: string | null;
  accounts_processed: number;
  prospect_count: number;
  suspect_count: number;
  rows_with_cost: number;
  total_cost: number;
  is_prospect_mismatches: number;
}

export interface CostTrackerResponse {
  summary: CostTrackerVerticalSummary[];
  by_channel: CostTrackerChannelRow[];
  data_integrity_warnings: string[];
}

export async function fetchCostTracker(vertical?: string): Promise<CostTrackerResponse> {
  const { data } = await client.get<CostTrackerResponse>("/cost-tracker", {
    params: vertical ? { vertical } : undefined,
  });
  return data;
}

// ---- Auth ---------------------------------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: string;
  email: string;
}

export async function signup(email: string, password: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/signup", { email, password });
  return data;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/login", { email, password });
  return data;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await client.get<CurrentUser>("/auth/me");
  return data;
}

// ---- Settings (added 2026-11-14) ---------------------------------------
// Store the production path's API keys/connection strings in .env and
// verify each against a real provider call. See backend/settings.py's
// module docstring for exactly which vars are managed (and which are
// deliberately excluded) and what each verify() call actually costs.

export type SettingCategory = "secret" | "connection" | "flag";

export interface SettingField {
  key: string;
  label: string;
  category: SettingCategory;
  help: string;
  is_set: boolean;
  value: string | null; // only populated for flag-category fields
  masked_value: string | null; // only populated for secret/connection fields
  source_file: string | null;
  verifiable: boolean;
}

export async function fetchSettings(): Promise<SettingField[]> {
  const { data } = await client.get<{ settings: SettingField[] }>("/settings");
  return data.settings;
}

export async function updateSetting(key: string, value: string): Promise<{ key: string; source_file: string }> {
  const { data } = await client.put(`/settings/${encodeURIComponent(key)}`, { value });
  return data;
}

export interface VerifyResult {
  ok: boolean;
  detail: string;
  cost_note: string;
}

export async function verifySetting(key: string): Promise<VerifyResult> {
  const { data } = await client.post<VerifyResult>(`/settings/${encodeURIComponent(key)}/verify`);
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
