import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  downloadBlob,
  downloadClayBatchCsv,
  downloadSelectedClayRowsCsv,
  fetchClayBatchRows,
  verifyClayBrandMatch,
} from "../api/client";

const CLASSIFICATION_LABELS: Record<string, string> = {
  NET_NEW: "Net new (no Salesforce match)",
  MATCHED_PROTECTED: "Matched — protected",
  MATCHED_AVAILABLE: "Matched — available",
  MATCHED_UNKNOWN: "Matched — unknown status",
  POSSIBLE_MATCH_BRAND: "Possible match (brand-root fuzzy)",
};

// Jeff (2026-11-16), on brand-fuzzy hits he could confirm by eye are real
// matches under a different domain ("different domains but same company.
// companies can have multiple domains"): "is there a way for the low
// confidence to have claude api open up both websites and do a
// comparison?" -- these labels/colors are just the AI's verdict on that
// comparison (same/different/uncertain), never the row's classification.
const AI_VERDICT_LABELS: Record<string, string> = {
  same: "AI: same company",
  different: "AI: different companies",
  uncertain: "AI: uncertain",
};

const PAGE_SIZE = 50;

/** Per-row table for one Clay dedupe run (Jeff, 2026-11-16: "show a table
 * of the account and the possible matches. also call out which ones are
 * net new. then select rows which can then be exported back out as a CSV
 * file"). The classification bullet list above this (in ClayImport)
 * gives totals; this is every row side by side, searchable/filterable,
 * with NET_NEW visually called out so it's not just another classification
 * string in a column, and row selection -> export-selected, same pattern
 * the Duplicates tab already uses. */
export function ClayBatchReview({ batchId }: { batchId: string }) {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [classification, setClassification] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [downloadAllError, setDownloadAllError] = useState<string | null>(null);
  const [exportingSelected, setExportingSelected] = useState(false);
  const [exportSelectedError, setExportSelectedError] = useState<string | null>(null);

  // Reset to page 1 and clear selection whenever we're reviewing a
  // different run -- a selection made against a previous batch's row ids
  // would silently (and wrongly) carry over otherwise.
  useEffect(() => {
    setPage(1);
    setSearchInput("");
    setSearch("");
    setClassification("");
    setSelectedIds(new Set());
  }, [batchId]);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const rowsQuery = useQuery({
    queryKey: ["clay-batch-rows", batchId, page, search, classification],
    queryFn: () => fetchClayBatchRows(batchId, { search, classification, page, pageSize: PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  // One row verified at a time, per Jeff's "is there a way for the low
  // confidence to have claude api open up both websites and do a
  // comparison?" -- a human asks for this per row, it's never automatic.
  // Re-fetches this page afterward rather than hand-patching the cache,
  // since that's the simplest way to pick up the real persisted
  // ai_verdict/ai_reasoning/ai_verified_at from the backend.
  const [verifyingRowId, setVerifyingRowId] = useState<number | null>(null);
  const [verifyError, setVerifyError] = useState<{ id: number; message: string } | null>(null);
  const verifyMutation = useMutation({
    mutationFn: (rowId: number) => verifyClayBrandMatch(batchId, rowId),
    onMutate: (rowId) => {
      setVerifyingRowId(rowId);
      setVerifyError(null);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clay-batch-rows", batchId] });
    },
    onError: (e, rowId) => {
      setVerifyError({ id: rowId, message: String(e) });
    },
    onSettled: () => setVerifyingRowId(null),
  });

  async function handleDownloadAll() {
    setDownloadingAll(true);
    setDownloadAllError(null);
    try {
      const blob = await downloadClayBatchCsv(batchId);
      downloadBlob(blob, `clay_dedupe_${batchId}.csv`);
    } catch (e) {
      setDownloadAllError(String(e));
    } finally {
      setDownloadingAll(false);
    }
  }

  async function handleDownloadSelected() {
    setExportingSelected(true);
    setExportSelectedError(null);
    try {
      const blob = await downloadSelectedClayRowsCsv(batchId, Array.from(selectedIds));
      downloadBlob(blob, `clay_dedupe_${batchId}_selected.csv`);
    } catch (e) {
      setExportSelectedError(String(e));
    } finally {
      setExportingSelected(false);
    }
  }

  function toggleRow(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const rows = rowsQuery.data?.rows ?? [];
  const pageIds = rows.map((r) => r.id);
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
  const someOnPageSelected = pageIds.some((id) => selectedIds.has(id));

  function toggleSelectAllOnPage() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  }

  const classificationCounts = rowsQuery.data?.classification_counts ?? {};
  const totalRows = rowsQuery.data?.total_rows ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  return (
    <div className="clay-batch-review">
      <h4>Review this run's rows</h4>

      <div className="clay-review-chips">
        <button
          type="button"
          className={classification === "" ? "chip chip-active" : "chip"}
          onClick={() => {
            setClassification("");
            setPage(1);
          }}
        >
          All ({Object.values(classificationCounts).reduce((a, b) => a + b, 0).toLocaleString()})
        </button>
        {Object.entries(classificationCounts).map(([cls, count]) => (
          <button
            key={cls}
            type="button"
            className={
              classification === cls
                ? `chip chip-active${cls === "NET_NEW" ? " chip-net-new" : ""}`
                : `chip${cls === "NET_NEW" ? " chip-net-new" : ""}`
            }
            onClick={() => {
              setClassification(cls);
              setPage(1);
            }}
          >
            {CLASSIFICATION_LABELS[cls] ?? cls} ({count.toLocaleString()})
          </button>
        ))}
      </div>

      <div className="clay-review-toolbar">
        <input
          type="text"
          placeholder="Search company name, website, or matched account…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <button type="button" onClick={handleDownloadAll} disabled={downloadingAll}>
          {downloadingAll ? "Preparing CSV…" : "Download all as CSV"}
        </button>
        <button
          type="button"
          onClick={handleDownloadSelected}
          disabled={selectedIds.size === 0 || exportingSelected}
        >
          {exportingSelected ? "Preparing CSV…" : `Export ${selectedIds.size.toLocaleString()} selected`}
        </button>
        {selectedIds.size > 0 && (
          <button type="button" onClick={() => setSelectedIds(new Set())}>
            Clear selection
          </button>
        )}
      </div>
      {downloadAllError && <p className="action-error">Download failed: {downloadAllError}</p>}
      {exportSelectedError && <p className="action-error">Export failed: {exportSelectedError}</p>}

      {rowsQuery.isError && (
        <p className="action-error">Could not load rows: {String(rowsQuery.error)}</p>
      )}

      <p className="field-hint">
        {totalRows.toLocaleString()} row(s){classification || search ? " match this filter" : ""} —
        page {page} of {totalPages.toLocaleString()}
      </p>

      <table className="accounts-table clay-review-table">
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
            <th>Account</th>
            <th>Website</th>
            <th>Status</th>
            <th>Matched Salesforce account</th>
            <th>Confidence</th>
            <th># candidates</th>
            <th>AI verification</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={row.classification === "NET_NEW" ? "row-net-new" : ""}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedIds.has(row.id)}
                  onChange={() => toggleRow(row.id)}
                  aria-label={`Select ${row.clay_company_name}`}
                />
              </td>
              <td title={row.clay_company_name ?? undefined}>{row.clay_company_name}</td>
              <td title={row.clay_website ?? undefined}>{row.clay_website}</td>
              <td>
                <span
                  className={
                    row.classification === "NET_NEW"
                      ? "status-pill status-pill-net-new"
                      : row.classification === "POSSIBLE_MATCH_BRAND"
                        ? "status-pill status-pill-brand"
                        : "status-pill status-pill-matched"
                  }
                >
                  {CLASSIFICATION_LABELS[row.classification] ?? row.classification}
                </span>
              </td>
              <td title={row.matched_account_id ?? undefined}>
                {row.matched_account_name ?? "—"}
                {row.num_candidates > 1 ? ` (+${row.num_candidates - 1} more)` : ""}
              </td>
              <td>{row.match_confidence ?? "—"}</td>
              <td>{row.num_candidates}</td>
              <td>
                {!row.matched_account_id ? (
                  "—"
                ) : (
                  <>
                    {row.ai_verdict && (
                      <div>
                        <span
                          className={`status-pill status-pill-ai-${row.ai_verdict}`}
                          title={row.ai_reasoning ?? undefined}
                        >
                          {AI_VERDICT_LABELS[row.ai_verdict] ?? row.ai_verdict}
                        </span>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => verifyMutation.mutate(row.id)}
                      disabled={verifyingRowId === row.id}
                    >
                      {verifyingRowId === row.id
                        ? "Checking…"
                        : row.ai_verdict
                          ? "Re-check with AI"
                          : "Check with AI"}
                    </button>
                    {verifyError?.id === row.id && (
                      <p className="action-error">{verifyError.message}</p>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && !rowsQuery.isFetching && (
            <tr>
              <td colSpan={8}>No rows match this filter.</td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="clay-review-pagination">
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
    </div>
  );
}
