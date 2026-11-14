import { useQuery } from "@tanstack/react-query";
import { fetchCostTracker } from "../api/client";

/** Cost Tracker tab. Per claude/Cost_Tracker_Design.md and Jeff's
 * 2026-11-14 decisions: on-demand (no scheduler, no separate rollup
 * table -- every load re-aggregates account_enrichment_results fresh),
 * cumulative all-time totals (not scoped to one run), both $/PROSPECT
 * and $/Lead (PROSPECT+SUSPECT) shown side by side as the North Star
 * metrics. The data_integrity_warnings banner only renders when the
 * backend's inline is_prospect-vs-lead_status/tier check actually finds
 * a mismatch -- see the real 139-row bug this caught and fixed earlier
 * the same day this tab was built. Silent the rest of the time, so it
 * reads as a real alert, not routine noise. */
export function CostTracker() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["cost-tracker"],
    queryFn: () => fetchCostTracker(),
  });

  const fmtMoney = (v: number | null, digits = 4) => (v === null ? "—" : `$${v.toFixed(digits)}`);

  return (
    <div className="cost-tracker">
      <p className="step-description">
        Cumulative, all-time cost rollup computed on demand from the real per-account
        enrichment results — no cached snapshot, no hand-maintained log.
      </p>

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
        <p className="empty-state">No completed enrichment results yet.</p>
      )}

      {data && data.summary.length > 0 && (
        <>
          {data.summary.map((s) => (
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
          ))}

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
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
