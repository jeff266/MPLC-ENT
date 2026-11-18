import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  downloadBlob,
  downloadDuplicatesCsv,
  downloadSelectedDuplicatesCsv,
  fetchDuplicateRows,
  fetchDuplicateSummary,
} from "../api/client";
import { UploadPanel } from "./UploadPanel";

const MATCH_TYPE_LABELS: Record<string, string> = {
  DUPLICATE_NAME_AND_WEBSITE: "Duplicate (same name + website)",
  DUPLICATE_WEBSITE_ONLY: "Duplicate (same website, different name)",
  SIBLING_NAME_ONLY: "Sibling (same name, different site)",
};

const PAGE_SIZE = 50;
const MAX_GROUP_SIZE = 50;

/** Finds Account records within this app's own Salesforce universe that
 * share a name or website with another Account — a likely duplicate or a
 * sibling (e.g. multi-location) account. Jeff (2026-11-14): "there's
 * quite a few accounts with exact same names or website... export a
 * file with the findings in a CSV which I can send to support at MPLC."
 *
 * Later the same day: "In duplicates, I can only see the first set of
 * records. I want to be able to paginate and search with filters. Select
 * records and export the selected records" -- the table below is backed
 * by /duplicates/rows (paginated + searchable + filterable server-side,
 * since the full result set can run into six figures of rows) rather
 * than the summary endpoint's 200-row preview, and selection persists
 * across pages so a review pass isn't lost by paging forward.
 *
 * This is deliberately a flag-for-review tool, not an auto-merge: every
 * group is for a human (Jeff, then MPLC support) to look at and decide,
 * same caution clay_dedupe.py's ambiguous-match handling already uses
 * elsewhere in this app.
 *
 * Jeff (2026-11-18): "when i drop a file into duplicates, I also want to
 * then pass it into the Find Safe Accounts feature as well. So I'd catch
 * net new AND we can run the rest thru safe to distribute." The dropzone
 * below is the SAME UploadPanel Step 1 uses, with autoRunAfterUpload on:
 * drop the weekly export here and it (1) lands in incoming/, (2)
 * automatically fires the real Find Safe Accounts pipeline run
 * (account_eligibility.py), which already excludes a sibling/parent
 * cluster from safe-to-distribute if ANY member has an open deal, 90-day
 * activity, or a Licensed/Customer status — Jeff's exact stated rule, not
 * new logic — and (3) once that run lands, re-triggers this panel's own
 * scan so the duplicate/sibling review list reflects the file you just
 * dropped. "Net new" = whatever comes out of the pipeline run with
 * excluded=false AND isn't part of a flagged group below. */
interface Props {
  /** Invoked once the auto-triggered pipeline run completes, so the
   * caller (App.tsx) can invalidate the Step 1/2 accounts tables the
   * same way ActionBar's manual "Run Pipeline" already does. */
  onPipelineRunComplete?: () => void;
}

export function DuplicatesPanel({ onPipelineRunComplete }: Props = {}) {
  const [ran, setRan] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [matchType, setMatchType] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exportingSelected, setExportingSelected] = useState(false);
  const [exportSelectedError, setExportSelectedError] = useState<string | null>(null);

  // Debounce the search box so every keystroke doesn't fire a request.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const summaryQuery = useQuery({
    queryKey: ["duplicate-summary"],
    queryFn: () => fetchDuplicateSummary(MAX_GROUP_SIZE),
    enabled: ran,
  });

  const rowsQuery = useQuery({
    queryKey: ["duplicate-rows", page, search, matchType],
    queryFn: () =>
      fetchDuplicateRows({
        maxGroupSize: MAX_GROUP_SIZE,
        search,
        matchType,
        page,
        pageSize: PAGE_SIZE,
      }),
    enabled: ran,
    placeholderData: (prev) => prev, // keep showing the current page while the next loads
  });

  async function handleScan() {
    if (ran) {
      summaryQuery.refetch();
      rowsQuery.refetch();
    } else {
      setRan(true);
    }
  }

  function handleAutoRunComplete() {
    // The dropped file just got ingested + protection-filtered into
    // `accounts`, so this panel's own scan (which reads straight from
    // that table) needs to run against the NEW data, not whatever was
    // there before the drop.
    onPipelineRunComplete?.();
    handleScan();
  }

  async function handleDownloadAll() {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await downloadDuplicatesCsv(MAX_GROUP_SIZE);
      downloadBlob(blob, `internal_duplicates_${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (e) {
      setDownloadError(String(e));
    } finally {
      setDownloading(false);
    }
  }

  async function handleDownloadSelected() {
    setExportingSelected(true);
    setExportSelectedError(null);
    try {
      const blob = await downloadSelectedDuplicatesCsv(Array.from(selectedIds), MAX_GROUP_SIZE);
      downloadBlob(
        blob,
        `internal_duplicates_selected_${new Date().toISOString().slice(0, 10)}.csv`,
      );
    } catch (e) {
      setExportSelectedError(String(e));
    } finally {
      setExportingSelected(false);
    }
  }

  function toggleRow(accountId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }

  const pageRows = rowsQuery.data?.rows ?? [];
  const pageRowIds = pageRows.map((r) => r.account_id);
  const allOnPageSelected = pageRowIds.length > 0 && pageRowIds.every((id) => selectedIds.has(id));
  const someOnPageSelected = pageRowIds.some((id) => selectedIds.has(id));

  function toggleSelectAllOnPage() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        pageRowIds.forEach((id) => next.delete(id));
      } else {
        pageRowIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  const totalRows = rowsQuery.data?.total_rows ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  const showAlreadyLinkedCol =
    (summaryQuery.data?.groups_already_hierarchical ?? 0) > 0;

  return (
    <div className="duplicates-panel">
      <section className="duplicates-section">
        <h3 className="duplicates-section-title">
          Drop this week's export <span className="duplicates-section-badge">new</span>
        </h3>
        <p className="step-description">
          Catches duplicates/siblings AND runs the file through Find Safe Accounts in one
          go — it lands in the same place Step 1 uses, the pipeline run fires automatically
          once both required files are matched, and the scan below re-runs against the
          result.
        </p>
        <UploadPanel autoRunAfterUpload onPipelineComplete={handleAutoRunComplete} />
      </section>

      <div className="duplicates-divider">
        <span>or check what's already loaded</span>
      </div>

      <section className="duplicates-section">
        <h3 className="duplicates-section-title">Scan the loaded accounts</h3>
        <p className="step-description">
          Finds Salesforce accounts already loaded into this app that share a name or a
          website with another account — a likely duplicate record, or a sibling account
          (e.g. the same chain/franchise name at a different location). Accounts that
          already have a parent account set in Salesforce, or are already flagged
          Delete/Duplicate in Account Status, are excluded — only orphaned, standalone
          accounts needing review are shown. Nothing here is merged automatically; every
          group is for a human to review. Hover a truncated cell to see the full value.
        </p>

        <button type="button" onClick={handleScan} disabled={summaryQuery.isFetching}>
          {summaryQuery.isFetching ? "Scanning…" : ran ? "Re-scan" : "Scan for duplicates/siblings"}
        </button>

        {summaryQuery.isError && (
          <p className="action-error">Scan failed: {String(summaryQuery.error)}</p>
        )}

        {summaryQuery.data && !summaryQuery.data.has_any_parent_data && (
          <p className="action-error">
            None of the loaded accounts have a Parent Account ID — the duplicate/sibling
            exclusion for already-parented accounts has nothing to exclude by, so counts
            below include accounts that may already be correctly organized under a parent
            in Salesforce (it just didn't come through in this weekly export). Check that
            the Salesforce report/export used for Step 1 actually includes the real
            Parent Account ID (ParentId) field before trusting these numbers.
          </p>
        )}

        {summaryQuery.data && (
          <div className="clay-import-result">
          <h3>
            {summaryQuery.data.total_groups.toLocaleString()} group(s),{" "}
            {summaryQuery.data.total_accounts_flagged.toLocaleString()} account(s) flagged
          </h3>
          <ul>
            {Object.entries(summaryQuery.data.counts_by_type).map(([type, count]) => (
              <li key={type}>
                {MATCH_TYPE_LABELS[type] ?? type}: {count.toLocaleString()}
              </li>
            ))}
          </ul>
          {summaryQuery.data.groups_already_hierarchical > 0 && (
            <p className="field-hint">
              {summaryQuery.data.groups_already_hierarchical.toLocaleString()} of these
              groups are already linked as parent/child in Salesforce.
            </p>
          )}

          <button type="button" onClick={handleDownloadAll} disabled={downloading}>
            {downloading ? "Preparing CSV…" : "Download all as CSV"}
          </button>
          {downloadError && <p className="action-error">Download failed: {downloadError}</p>}

          {summaryQuery.data.total_groups > 0 && (
            <>
              <div className="duplicates-toolbar">
                <input
                  type="text"
                  placeholder="Search name, website, or account ID…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                />
                <select
                  value={matchType}
                  onChange={(e) => {
                    setMatchType(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">All types</option>
                  {Object.entries(MATCH_TYPE_LABELS).map(([type, label]) => (
                    <option key={type} value={type}>
                      {label}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={handleDownloadSelected}
                  disabled={selectedIds.size === 0 || exportingSelected}
                >
                  {exportingSelected
                    ? "Preparing CSV…"
                    : `Export ${selectedIds.size.toLocaleString()} selected`}
                </button>
                {selectedIds.size > 0 && (
                  <button type="button" onClick={() => setSelectedIds(new Set())}>
                    Clear selection
                  </button>
                )}
              </div>
              {exportSelectedError && (
                <p className="action-error">Export failed: {exportSelectedError}</p>
              )}

              <h4>
                {totalRows.toLocaleString()} row(s) match
                {search || matchType ? " this filter" : ""} — page {page} of{" "}
                {totalPages.toLocaleString()}
              </h4>

              {rowsQuery.isError && (
                <p className="action-error">Could not load rows: {String(rowsQuery.error)}</p>
              )}

              <table className="accounts-table duplicates-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={allOnPageSelected}
                        ref={(el) => {
                          if (el) el.indeterminate = !allOnPageSelected && someOnPageSelected;
                        }}
                        onChange={toggleSelectAllOnPage}
                        aria-label="Select all rows on this page"
                      />
                    </th>
                    <th>Group</th>
                    <th>Type</th>
                    <th>Account ID</th>
                    <th>Name</th>
                    <th>Website</th>
                    <th>State</th>
                    {showAlreadyLinkedCol && <th>Already linked?</th>}
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={row.account_id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(row.account_id)}
                          onChange={() => toggleRow(row.account_id)}
                          aria-label={`Select ${row.account_name}`}
                        />
                      </td>
                      <td>{row.group_id}</td>
                      <td title={MATCH_TYPE_LABELS[row.match_type] ?? row.match_type}>
                        {MATCH_TYPE_LABELS[row.match_type] ?? row.match_type}
                      </td>
                      <td title={row.account_id}>{row.account_id}</td>
                      <td title={row.account_name}>{row.account_name}</td>
                      <td title={row.website}>{row.website}</td>
                      <td>{row.state}</td>
                      {showAlreadyLinkedCol && (
                        <td>{row.already_hierarchical ? "Yes" : ""}</td>
                      )}
                    </tr>
                  ))}
                  {pageRows.length === 0 && !rowsQuery.isFetching && (
                    <tr>
                      <td colSpan={showAlreadyLinkedCol ? 8 : 7}>No rows match this filter.</td>
                    </tr>
                  )}
                </tbody>
              </table>

              {totalPages > 1 && (
                <div className="duplicates-pagination">
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1 || rowsQuery.isFetching}
                  >
                    ← Previous
                  </button>
                  <span>
                    Page {page} of {totalPages.toLocaleString()}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages || rowsQuery.isFetching}
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
      </section>
    </div>
  );
}
