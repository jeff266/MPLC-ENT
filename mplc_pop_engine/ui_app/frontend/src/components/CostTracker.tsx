import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  downloadBlob,
  downloadCostTrackerByToolCsv,
  downloadCostTrackerCsv,
  fetchCostTracker,
  fetchCostTrackerByTool,
} from "../api/client";

/** Cost Tracker tab. Per claude/Cost_Tracker_Design.md and Jeff's
 * 2026-11-14 decisions: on-demand (no scheduler, no separate rollup
 * table -- every load re-aggregates account_enrichment_results fresh),
 * cumulative all-time totals (not scoped to one run), both $/PROSPECT
 * and $/Lead (PROSPECT+SUSPECT) shown side by side as the North Star
 * metrics. The data_integrity_warnings banner only renders when the
 * backend's inline is_prospect-vs-lead_status/tier check actually finds
 * a mismatch -- see the real 139-row bug this caught and fixed earlier
 * the same day this tab was built. Silent the rest of the time, so it
 * reads as a real alert, not routine noise.
 *
 * Jeff (2026-11-16): "let's add a filtering and export feature to the
 * cost tracker." Vertical is a chip row (server-side -- scopes both the
 * summary tiles and the by_channel table, same convention as /cost-
 * tracker?vertical=); search is a text box (server-side too, but only
 * narrows by_channel, same "chips/counts don't move with the filter"
 * convention the Clay batch review table already uses). Download CSV
 * hits /cost-tracker/export.csv with the exact same two params, so the
 * file always matches what's on screen.
 *
 * Jeff (2026-11-16, same day): "In the cost tracker do we have a
 * breakdown of spend by tool used" -- added a second "By tool" section
 * below, sharing the SAME vertical/search filters (one filter row drives
 * both tables) rather than a separate control set, with its own CSV
 * download. "unspecified_legacy" is real spend from rows written before
 * the enrichers started persisting cost_breakdown -- shown plainly
 * rather than hidden, so this total always reconciles with the
 * by-channel total above for the same vertical. */
const TOOL_LABELS: Record<string, string> = {
  serper: "Serper (search)",
  rapidapi: "RapidAPI (video download)",
  anthropic_claude: "Anthropic Claude (VLM / verification)",
  usaspending_api: "USAspending.gov (federal contracts)",
  normalization_api: "Normalization API",
  unspecified_legacy: "Unspecified (pre-dates tool tracking)",
};

export function CostTracker() {
  const [vertical, setVertical] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["cost-tracker", vertical, search],
    queryFn: () => fetchCostTracker(vertical || undefined, search || undefined),
    placeholderData: (prev) => prev,
  });

  // Vertical chips come from the backend's own full (unfiltered-by-search)
  // vertical list -- fetched once, unscoped, so the chip row itself never
  // disappears/reorders as the active vertical filter changes.
  const allVerticalsQuery = useQuery({
    queryKey: ["cost-tracker-all-verticals"],
    queryFn: () => fetchCostTracker(),
  });
  const availableVerticals = (allVerticalsQuery.data?.summary ?? []).map((s) => s.vertical);

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await downloadCostTrackerCsv(vertical || undefined, search || undefined);
      downloadBlob(blob, "cost_tracker.csv");
    } catch (e) {
      setDownloadError(String(e));
    } finally {
      setDownloading(false);
    }
  }

  const byToolQuery = useQuery({
    queryKey: ["cost-tracker-by-tool", vertical, search],
    queryFn: () => fetchCostTrackerByTool(vertical || undefined, search || undefined),
    placeholderData: (prev) => prev,
  });

  const [downloadingByTool, setDownloadingByTool] = useState(false);
  const [downloadByToolError, setDownloadByToolError] = useState<string | null>(null);

  async function handleDownloadByTool() {
    setDownloadingByTool(true);
    setDownloadByToolError(null);
    try {
      const blob = await downloadCostTrackerByToolCsv(vertical || undefined, search || undefined);
      downloadBlob(blob, "cost_tracker_by_tool.csv");
    } catch (e) {
      setDownloadByToolError(String(e));
    } finally {
      setDownloadingByTool(false);
    }
  }

  const fmtMoney = (v: number | null, digits = 4) => (v === null ? "—" : `$${v.toFixed(digits)}`);

  return (
    <div className="cost-tracker">
      <p className="step-description">
        Cumulative, all-time cost rollup computed on demand from the real per-account
        enrichment results — no cached snapshot, no hand-maintained log.
      </p>

      <div className="clay-review-chips">
        <button
          type="button"
          className={vertical === "" ? "chip chip-active" : "chip"}
          onClick={() => setVertical("")}
        >
          All verticals
        </button>
        {availableVerticals.map((v) => (
          <button
            key={v}
            type="button"
            className={vertical === v ? "chip chip-active" : "chip"}
            onClick={() => setVertical(v)}
          >
            {v}
          </button>
        ))}
      </div>

      <div className="clay-review-toolbar">
        <input
          type="text"
          placeholder="Search channel or vertical…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <button type="button" onClick={handleDownload} disabled={downloading}>
          {downloading ? "Preparing CSV…" : "Download CSV"}
        </button>
      </div>
      {downloadError && <p className="action-error">Download failed: {downloadError}</p>}

      {isLoading && <p>Loading…</p>}
      {isError && <p className="action-error">Failed to load cost tracker: {String(error)}</p>}

      {data && data.data_integrity_warnings.length > 0 && (
        <div className="cost-tracker-warning">
          <strong>Data integrity warning</strong>
          <ul>
            {data.data_integrity_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {data && data.summary.length === 0 && (
        <p className="empty-state">
          {vertical
            ? `No completed enrichment results yet for ${vertical}.`
            : "No completed enrichment results yet."}
        </p>
      )}

      {data && data.summary.length > 0 && (
        <>
          {data.summary.map((s) =>
            // clay_brand_verification (Jeff, 2026-11-16: "when i click on
            // AI Check are we cost tracking that?") isn't a PROSPECT/
            // SUSPECT pipeline -- it's a same/different/uncertain second
            // opinion -- so the North Star $/prospect and $/lead tiles
            // below (and "0 prospects") would be misleading here. Shown
            // as its own simpler block instead of forcing it into tiles
            // that don't apply.
            s.vertical === "clay_brand_verification" ? (
              <div key={s.vertical} className="cost-tracker-vertical">
                <h3>Clay dedupe — AI brand verification ("Check with AI")</h3>
                <div className="metrics-panel">
                  <div className="metric-tile">
                    <div className="metric-value">${s.total_cost.toFixed(4)}</div>
                    <div className="metric-label">total spend (cumulative)</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">{s.accounts_processed.toLocaleString()}</div>
                    <div className="metric-label">checks run</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">{fmtMoney(s.cost_per_account)}</div>
                    <div className="metric-label">$ / check</div>
                  </div>
                </div>
              </div>
            ) : (
              <div key={s.vertical} className="cost-tracker-vertical">
                <h3>{s.vertical}</h3>
                <div className="metrics-panel">
                  <div className="metric-tile">
                    <div className="metric-value">{fmtMoney(s.cost_per_prospect)}</div>
                    <div className="metric-label">$ / prospect (North Star)</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">{fmtMoney(s.cost_per_lead)}</div>
                    <div className="metric-label">$ / lead (prospect + suspect)</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">{fmtMoney(s.cost_per_account)}</div>
                    <div className="metric-label">$ / account</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">${s.total_cost.toFixed(2)}</div>
                    <div className="metric-label">total spend (cumulative)</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">{s.accounts_processed.toLocaleString()}</div>
                    <div className="metric-label">accounts processed</div>
                  </div>
                  <div className="metric-tile">
                    <div className="metric-value">
                      {s.prospect_count.toLocaleString()}
                      {s.suspect_count > 0 ? ` + ${s.suspect_count.toLocaleString()}` : ""}
                    </div>
                    <div className="metric-label">prospects{s.suspect_count > 0 ? " + suspects" : ""}</div>
                  </div>
                </div>
              </div>
            ),
          )}

          <h3>By channel</h3>
          <table className="accounts-table">
            <thead>
              <tr>
                <th>Vertical</th>
                <th>Channel</th>
                <th>Accounts</th>
                <th>Prospects</th>
                <th>Total cost</th>
                <th>$ / account</th>
              </tr>
            </thead>
            <tbody>
              {data.by_channel.map((row) => (
                <tr key={`${row.vertical}-${row.channel ?? "none"}`}>
                  <td>{row.vertical}</td>
                  <td>{row.channel ?? "(no channel)"}</td>
                  <td>{row.accounts_processed.toLocaleString()}</td>
                  <td>{row.prospect_count.toLocaleString()}</td>
                  <td>${row.total_cost.toFixed(4)}</td>
                  <td>{row.rows_with_cost ? `$${(row.total_cost / row.rows_with_cost).toFixed(4)}` : "—"}</td>
                </tr>
              ))}
              {data.by_channel.length === 0 && (
                <tr>
                  <td colSpan={6}>No rows match this filter.</td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="clay-review-toolbar">
            <h3 style={{ margin: 0 }}>By tool</h3>
            <button type="button" onClick={handleDownloadByTool} disabled={downloadingByTool}>
              {downloadingByTool ? "Preparing CSV…" : "Download CSV"}
            </button>
          </div>
          {downloadByToolError && <p className="action-error">Download failed: {downloadByToolError}</p>}

          {byToolQuery.isLoading && <p>Loading…</p>}
          {byToolQuery.isError && (
            <p className="action-error">Failed to load tool breakdown: {String(byToolQuery.error)}</p>
          )}
          {byToolQuery.data && (
            <>
              <table className="accounts-table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Total cost</th>
                    <th>% of spend</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const grandTotal = byToolQuery.data.by_tool.reduce((sum, t) => sum + t.total_cost, 0);
                    return byToolQuery.data.by_tool.map((t) => (
                      <tr key={t.tool}>
                        <td>{TOOL_LABELS[t.tool] ?? t.tool}</td>
                        <td>${t.total_cost.toFixed(4)}</td>
                        <td>{grandTotal ? `${((t.total_cost / grandTotal) * 100).toFixed(1)}%` : "—"}</td>
                      </tr>
                    ));
                  })()}
                  {byToolQuery.data.by_tool.length === 0 && (
                    <tr>
                      <td colSpan={3}>No spend recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>

              <table className="accounts-table">
                <thead>
                  <tr>
                    <th>Vertical</th>
                    <th>Tool</th>
                    <th>Total cost</th>
                    <th>$ / row</th>
                  </tr>
                </thead>
                <tbody>
                  {byToolQuery.data.by_tool_and_vertical.map((row) => (
                    <tr key={`${row.vertical}-${row.tool}`}>
                      <td>{row.vertical}</td>
                      <td>{TOOL_LABELS[row.tool] ?? row.tool}</td>
                      <td>${row.total_cost.toFixed(4)}</td>
                      <td>{row.rows_with_cost ? `$${(row.total_cost / row.rows_with_cost).toFixed(4)}` : "—"}</td>
                    </tr>
                  ))}
                  {byToolQuery.data.by_tool_and_vertical.length === 0 && (
                    <tr>
                      <td colSpan={4}>No rows match this filter.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
