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
  match_confidence: string | null;
  matched_account_id: string | null;
  matched_account_name: string | null;
  num_candidates: number;
  ai_verdict: string | null; // "same" | "different" | "uncertain" | null (never verified)
  ai_reasoning: string | null;
  ai_verified_at: string | null;
  ai_check_cost: number | null;
  // Semicolon-delimited subset of account_eligibility.py's REASON_LABELS
  // (own_bad_status / cluster_bad_status / name_marker / recent_activity /
  // open_deal / lost_deal_last_9_months) -- only populated for
  // MATCHED_PROTECTED rows. See REASON_LABEL_INFO in ClayBatchReview.tsx.
  exclusion_reasons: string | null;
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

// ---- Clay/ZoomInfo import ----------------------------------------------
// Closes the gap Jeff flagged (2026-11-14): the ClayAmbiguousQueue above
// already read clay_matches, but nothing wrote to it. These two calls are
// the upload -> detect -> (human confirms mapping) -> run flow.

export interface ClayColumnMapping {
  company_name: string | null;
  website: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
}

export interface ClayDetectColumnsResult {
  columns: string[];
  detected_mapping: ClayColumnMapping;
  row_count: number;
  preview_rows: Record<string, string>[];
}

export async function detectClayColumns(file: File): Promise<ClayDetectColumnsResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await client.post<ClayDetectColumnsResult>(
    "/clay-dedupe/detect-columns",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export interface ClayImportResult {
  batch_id: string;
  rows_processed: number;
  classification_counts: Record<string, number>;
  ambiguous_count: number;
  brand_match_count: number;
  eligibility_data_available: boolean;
}

export async function runClayDedupe(
  file: File,
  columnMapping: Partial<ClayColumnMapping>,
): Promise<ClayImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("column_mapping", JSON.stringify(columnMapping));
  const { data } = await client.post<ClayImportResult>("/clay-dedupe/run", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ---- Clay dedupe batch review table -------------------------------------
// Jeff (2026-11-16): "show a table of the account and the possible
// matches. also call out which ones are net new. then select rows which
// can then be exported back out as a CSV file." Scoped to one run
// (batch_id) -- the classification_counts bullet list above tells you
// totals, this is every row from that run, side by side.

export interface ClayBatchRow {
  id: number;
  clay_company_name: string | null;
  clay_website: string | null;
  classification: string;
  match_method: string | null;
  match_confidence: string | null;
  matched_account_id: string | null;
  matched_account_name: string | null;
  num_candidates: number;
  ai_verdict: string | null; // "same" | "different" | "uncertain" | null (never verified)
  ai_reasoning: string | null;
  ai_verified_at: string | null;
  ai_check_cost: number | null;
  // Semicolon-delimited subset of account_eligibility.py's REASON_LABELS
  // (own_bad_status / cluster_bad_status / name_marker / recent_activity /
  // open_deal / lost_deal_last_9_months) -- only populated for
  // MATCHED_PROTECTED rows. See REASON_LABEL_INFO in ClayBatchReview.tsx.
  exclusion_reasons: string | null;
  // This row's latest clay_dispatch.py outcome, if it's ever been sent to
  // a vertical pipeline from this tab -- null if it never has.
  dispatch_status: string | null; // "dispatched" | "skipped_already_enriched" | null
  dispatch_vertical: string | null;
  dispatch_job_id: string | null;
}

export interface ClayBatchRowsResult {
  total_rows: number;
  classification_counts: Record<string, number>;
  page: number;
  page_size: number;
  rows: ClayBatchRow[];
}

export interface ClayBatchRowsQuery {
  search?: string;
  classification?: string;
  page?: number;
  pageSize?: number;
}

export async function fetchClayBatchRows(
  batchId: string,
  q: ClayBatchRowsQuery = {},
): Promise<ClayBatchRowsResult> {
  const { data } = await client.get<ClayBatchRowsResult>(`/clay-dedupe/batch/${batchId}/rows`, {
    params: {
      search: q.search || undefined,
      classification: q.classification || undefined,
      page: q.page ?? 1,
      page_size: q.pageSize ?? 50,
    },
  });
  return data;
}

export async function downloadClayBatchCsv(batchId: string): Promise<Blob> {
  const response = await client.get(`/clay-dedupe/batch/${batchId}/export.csv`, {
    responseType: "blob",
  });
  return response.data as Blob;
}

export async function downloadSelectedClayRowsCsv(batchId: string, ids: number[]): Promise<Blob> {
  const response = await client.post(
    `/clay-dedupe/batch/${batchId}/export-selected.csv`,
    { ids },
    { responseType: "blob" },
  );
  return response.data as Blob;
}

// ---- Clay dispatch: send selected rows straight into a vertical pipeline
// ----------------------------------------------------------------------
// Jeff (2026-11-18): "After I dedupe the list and find the net new, and
// select accounts, how do I route them to a vertical? or store in them
// in a future run?" -- any selected row (any classification -- the
// dedupe status is a decision aid, never a gate) can be sent here. No
// Salesforce account needed; see clay_dispatch.py for how.

export interface ProtectedClayRow {
  id: number;
  clay_company_name: string | null;
  matched_account_name: string | null;
  exclusion_reasons: string | null;
}

export type DispatchClayRowsResult =
  | { requires_confirmation: true; protected_rows: ProtectedClayRow[] }
  | {
      requires_confirmation: false;
      job_id: string;
      vertical: string;
      run_date: string;
      total_requested: number;
      total_dispatched: number;
      skipped_already_enriched: number;
      missing_ids: number[];
      unusable_ids: number[];
      pid: number;
    };

export async function dispatchClayRows(req: {
  clayMatchIds: number[];
  vertical: string;
  disabledChannels?: string[];
  confirmedProtected?: boolean;
}): Promise<DispatchClayRowsResult> {
  const { data } = await client.post<DispatchClayRowsResult>("/clay-dedupe/dispatch", {
    clay_match_ids: req.clayMatchIds,
    vertical: req.vertical,
    disabled_channels: req.disabledChannels,
    confirmed_protected: req.confirmedProtected ?? false,
  });
  return data;
}

// ---- AI brand-match verification ----------------------------------------
// Jeff (2026-11-16), on Cortland/Knightvest/Pantzer -- brand-fuzzy hits he
// could confirm by eye are real Salesforce matches under a different
// domain: "is there a way for the low confidence to have claude api open
// up both websites and do a comparison?" A human-requested second opinion
// per row -- never run automatically, never changes `classification`.

export interface VerifyClayBrandMatchResult {
  id: number;
  ai_verdict: string; // "same" | "different" | "uncertain"
  ai_reasoning: string;
  ai_verified_at: string;
  ai_check_cost: number;
  fetch_errors: Record<string, string>;
}

export async function verifyClayBrandMatch(
  batchId: string,
  rowId: number,
): Promise<VerifyClayBrandMatchResult> {
  const { data } = await client.post<VerifyClayBrandMatchResult>(
    `/clay-dedupe/batch/${batchId}/rows/${rowId}/verify`,
  );
  return data;
}

// ---- Internal Salesforce duplicate/sibling detection -------------------
// Jeff (2026-11-14): accounts already loaded into this app with the same
// name or website, compared against each other (not against an external
// export like Clay/ZoomInfo above).

export interface DuplicateGroupRow {
  group_id: number;
  match_type: string;
  account_id: string;
  account_name: string;
  website: string;
  phone: string;
  state: string;
  industry: string;
  parent_account_id: string;
  already_hierarchical: boolean;
  group_size: number;
}

export interface DuplicateSummary {
  total_groups: number;
  total_accounts_flagged: number;
  groups_already_hierarchical: number;
  counts_by_type: Record<string, number>;
  preview_rows: DuplicateGroupRow[];
  preview_truncated: boolean;
  has_any_parent_data: boolean;
}

export async function fetchDuplicateSummary(maxGroupSize = 50): Promise<DuplicateSummary> {
  const { data } = await client.get<DuplicateSummary>("/duplicates/summary", {
    params: { max_group_size: maxGroupSize },
  });
  return data;
}

export async function downloadDuplicatesCsv(maxGroupSize = 50): Promise<Blob> {
  const response = await client.get("/duplicates/export.csv", {
    params: { max_group_size: maxGroupSize },
    responseType: "blob",
  });
  return response.data as Blob;
}

export interface DuplicateRowsQuery {
  maxGroupSize?: number;
  search?: string;
  matchType?: string;
  page?: number;
  pageSize?: number;
}

export interface DuplicateRowsResult {
  rows: DuplicateGroupRow[];
  total_rows: number;
  total_groups: number;
  page: number;
  page_size: number;
}

/** Jeff (2026-11-14): "I can only see the first set of records. I want to
 * be able to paginate and search with filters." Backs the Duplicates
 * table directly, separate from fetchDuplicateSummary()'s capped preview. */
export async function fetchDuplicateRows(q: DuplicateRowsQuery = {}): Promise<DuplicateRowsResult> {
  const { data } = await client.get<DuplicateRowsResult>("/duplicates/rows", {
    params: {
      max_group_size: q.maxGroupSize ?? 50,
      search: q.search || undefined,
      match_type: q.matchType || undefined,
      page: q.page ?? 1,
      page_size: q.pageSize ?? 50,
    },
  });
  return data;
}

/** "Select records and export the selected records" -- distinct from
 * downloadDuplicatesCsv()'s full-dataset export above. */
export async function downloadSelectedDuplicatesCsv(
  accountIds: string[],
  maxGroupSize = 50,
): Promise<Blob> {
  const response = await client.post(
    "/duplicates/export-selected.csv",
    { account_ids: accountIds, max_group_size: maxGroupSize },
    { responseType: "blob" },
  );
  return response.data as Blob;
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
  // "salesforce" (the usual Step 2 dispatch) or "clay_import" (dispatched
  // straight from the Clay Import tab's review table, no Salesforce
  // account needed -- see dispatchClayRows).
  source: string;
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
  source: string;
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

export async function fetchCostTracker(vertical?: string, search?: string): Promise<CostTrackerResponse> {
  const { data } = await client.get<CostTrackerResponse>("/cost-tracker", {
    params: { vertical: vertical || undefined, search: search || undefined },
  });
  return data;
}

/** Jeff (2026-11-16): "let's add a filtering and export feature to the
 * cost tracker." Same vertical/search filters as fetchCostTracker --
 * the download always matches what the "By channel" table shows. */
export async function downloadCostTrackerCsv(vertical?: string, search?: string): Promise<Blob> {
  const response = await client.get("/cost-tracker/export.csv", {
    params: { vertical: vertical || undefined, search: search || undefined },
    responseType: "blob",
  });
  return response.data as Blob;
}

// ---- Cost Tracker: by tool (2026-11-16) ----------------------------------
// Jeff: "In the cost tracker do we have a breakdown of spend by tool
// used" -- the per-tool split (serper / rapidapi / anthropic_claude /
// usaspending_api / normalization_api, plus "unspecified_legacy" for
// rows written before this shipped) alongside the existing by-channel
// view.

export interface CostTrackerToolSummary {
  tool: string;
  rows_with_cost: number;
  total_cost: number;
}

export interface CostTrackerToolRow {
  vertical: string;
  tool: string;
  rows_with_cost: number;
  total_cost: number;
}

export interface CostTrackerByToolResponse {
  by_tool: CostTrackerToolSummary[];
  by_tool_and_vertical: CostTrackerToolRow[];
  data_integrity_warnings: string[];
}

export async function fetchCostTrackerByTool(
  vertical?: string,
  search?: string,
): Promise<CostTrackerByToolResponse> {
  const { data } = await client.get<CostTrackerByToolResponse>("/cost-tracker/by-tool", {
    params: { vertical: vertical || undefined, search: search || undefined },
  });
  return data;
}

export async function downloadCostTrackerByToolCsv(vertical?: string, search?: string): Promise<Blob> {
  const response = await client.get("/cost-tracker/by-tool/export.csv", {
    params: { vertical: vertical || undefined, search: search || undefined },
    responseType: "blob",
  });
  return response.data as Blob;
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

// ---------------------------------------------------------------------------
// Custom Vertical Builder -- Jeff (2026-11-18): config-driven way to define
// a new vertical (channel selection, search-term/description config,
// ordering, early-exit-on-PROSPECT) without writing new Python per
// vertical. See claude/Custom_Vertical_Builder_Design.md in the MPLC
// project. Surfaced in the Settings tab, not a new top-level tab.
// ---------------------------------------------------------------------------

export type CustomVerticalChannelType = "serper_image" | "youtube_video" | "website_scrape";

export interface CustomVerticalChannelRow {
  id: number;
  vertical_key: string;
  step_order: number;
  channel_type: CustomVerticalChannelType;
  enabled: boolean;
  description: string;
  config_json: string | null;
  config_generated_cost: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomVerticalRow {
  vertical_key: string;
  display_name: string;
  // Added 2026-11-18: answers "does a custom vertical map to the right
  // pipeline post-Step-1?" -- match_keywords_json is generated once (an
  // LLM call from the vertical's own channel descriptions) and used by a
  // separate, free keyword-match pass (not Stage B's classifier) to tag
  // "safe to distribute" accounts. See custom_verticals.py's
  // match_accounts_to_custom_verticals for the full mechanism.
  match_keywords_json: string | null;
  match_keywords_generated_cost: number;
  created_at: string | null;
  updated_at: string | null;
  channels: CustomVerticalChannelRow[];
}

export async function fetchCustomVerticals(): Promise<CustomVerticalRow[]> {
  const { data } = await client.get<CustomVerticalRow[]>("/custom-verticals");
  return data;
}

export async function createCustomVertical(
  verticalKey: string,
  displayName: string,
): Promise<CustomVerticalRow> {
  const { data } = await client.post<CustomVerticalRow>("/custom-verticals", {
    vertical_key: verticalKey,
    display_name: displayName,
  });
  return data;
}

export async function deleteCustomVertical(verticalKey: string): Promise<void> {
  await client.delete(`/custom-verticals/${encodeURIComponent(verticalKey)}`);
}

export async function addCustomVerticalChannel(
  verticalKey: string,
  channelType: CustomVerticalChannelType,
  description: string,
): Promise<CustomVerticalChannelRow> {
  const { data } = await client.post<CustomVerticalChannelRow>(
    `/custom-verticals/${encodeURIComponent(verticalKey)}/channels`,
    { channel_type: channelType, description },
  );
  return data;
}

export interface UpdateCustomVerticalChannelInput {
  step_order?: number;
  enabled?: boolean;
  config_json?: string;
  regenerate_from_description?: string;
}

export async function updateCustomVerticalChannel(
  verticalKey: string,
  channelId: number,
  input: UpdateCustomVerticalChannelInput,
): Promise<CustomVerticalChannelRow> {
  const { data } = await client.put<CustomVerticalChannelRow>(
    `/custom-verticals/${encodeURIComponent(verticalKey)}/channels/${channelId}`,
    input,
  );
  return data;
}

export async function deleteCustomVerticalChannel(verticalKey: string, channelId: number): Promise<void> {
  await client.delete(`/custom-verticals/${encodeURIComponent(verticalKey)}/channels/${channelId}`);
}

// Account-matching for custom verticals -- the piece that answers "when I
// create a vertical, does it map to the right pipeline post-Step-1?" A
// separate, additive pass from Stage B's classifier (see CLAUDE.md /
// custom_verticals.py for why); these three calls are its UI surface.

export async function generateCustomVerticalMatchKeywords(
  verticalKey: string,
): Promise<CustomVerticalRow> {
  const { data } = await client.post<CustomVerticalRow>(
    `/custom-verticals/${encodeURIComponent(verticalKey)}/match-keywords/generate`,
  );
  return data;
}

export async function updateCustomVerticalMatchKeywords(
  verticalKey: string,
  matchKeywordsJson: string,
): Promise<CustomVerticalRow> {
  const { data } = await client.put<CustomVerticalRow>(
    `/custom-verticals/${encodeURIComponent(verticalKey)}/match-keywords`,
    { match_keywords_json: matchKeywordsJson },
  );
  return data;
}

export interface RematchResult {
  run_date: string;
  matches: Record<string, number>;
}

export async function rematchCustomVerticals(): Promise<RematchResult> {
  const { data } = await client.post<RematchResult>("/custom-verticals/rematch");
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
