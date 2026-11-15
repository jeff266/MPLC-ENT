import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { downloadBlob, downloadDuplicatesCsv, fetchDuplicateSummary } from "../api/client";

const MATCH_TYPE_LABELS: Record<string, string> = {
  DUPLICATE_NAME_AND_WEBSITE: "Duplicate (same name + website)",
  DUPLICATE_WEBSITE_ONLY: "Duplicate (same website, different name)",
  SIBLING_NAME_ONLY: "Sibling (same name, different site)",
};

/** Finds Account records within this app's own Salesforce universe that
 * share a name or website with another Account — a likely duplicate or a
 * sibling (e.g. multi-location) account. Jeff (2026-11-14): "there's
 * quite a few accounts with exact same names or website... export a
 * file with the findings in a CSV which I can send to support at MPLC."
 *
 * This is deliberately a flag-for-review tool, not an auto-merge: every
 * group is for a human (Jeff, then MPLC support) to look at and decide,
 * same caution clay_dedupe.py's ambiguous-match handling already uses
 * elsewhere in this app. */
export function DuplicatesPanel() {
  const [ran, setRan] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["duplicate-summary"],
    queryFn: () => fetchDuplicateSummary(50),
    enabled: ran,
  });

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await downloadDuplicatesCsv(50);
      downloadBlob(blob, `internal_duplicates_${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (e) {
      setDownloadError(String(e));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="duplicates-panel">
      <p className="step-description">
        Finds Salesforce accounts already loaded into this app that share a name or a
        website with another account — a likely duplicate record, or a sibling account
        (e.g. the same chain/franchise name at a different location). Accounts that
        already have a parent account set in Salesforce are excluded — only orphaned,
        standalone accounts are flagged. Nothing here is merged automatically; every
        group is for a human to review. Hover a truncated cell to see the full value.
      </p>

      <button type="button" onClick={() => setRan(true)} disabled={summaryQuery.isFetching}>
        {summaryQuery.isFetching ? "Scanning…" : "Scan for duplicates/siblings"}
      </button>

      {summaryQuery.isError && (
        <p className="action-error">Scan failed: {String(summaryQuery.error)}</p>
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

          <button type="button" onClick={handleDownload} disabled={downloading}>
            {downloading ? "Preparing CSV…" : "Download CSV for MPLC support"}
          </button>
          {downloadError && <p className="action-error">Download failed: {downloadError}</p>}

          {summaryQuery.data.total_groups > 0 && (
            <>
              <h4>
                Preview{summaryQuery.data.preview_truncated ? " (first 200 rows — download the CSV for the rest)" : ""}
              </h4>
              <table className="accounts-table duplicates-table">
                <thead>
                  <tr>
                    <th>Group</th>
                    <th>Type</th>
                    <th>Account ID</th>
                    <th>Name</th>
                    <th>Website</th>
                    <th>State</th>
                    {summaryQuery.data.groups_already_hierarchical > 0 && <th>Already linked?</th>}
                  </tr>
                </thead>
                <tbody>
                  {summaryQuery.data.preview_rows.map((row) => (
                    <tr key={row.account_id}>
                      <td>{row.group_id}</td>
                      <td title={MATCH_TYPE_LABELS[row.match_type] ?? row.match_type}>
                        {MATCH_TYPE_LABELS[row.match_type] ?? row.match_type}
                      </td>
                      <td title={row.account_id}>{row.account_id}</td>
                      <td title={row.account_name}>{row.account_name}</td>
                      <td title={row.website}>{row.website}</td>
                      <td>{row.state}</td>
                      {summaryQuery.data.groups_already_hierarchical > 0 && (
                        <td>{row.already_hierarchical ? "Yes" : ""}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </div>
  );
}
