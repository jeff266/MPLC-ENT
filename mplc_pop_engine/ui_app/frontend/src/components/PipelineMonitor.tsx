import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchEnrichmentJobs, fetchJobProgress } from "../api/client";

/** Step 3 (Jeff, 2026-11-13): "another tab that shows how the vertical
 * pipelines work in detail and if accounts are running thru them it
 * visualizes progress and current outputs" — answered as ALL THREE: live
 * counts, per-account outputs, cost tracking. The live feed here is
 * Supabase's own account_enrichment_results + worker_heartbeat, written
 * incrementally by unified_worker.py as it runs (not a separate tracking
 * system) — this tab just polls and displays it. */
export function PipelineMonitor() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const { data: jobs, isLoading: jobsLoading } = useQuery({
    queryKey: ["enrichment-jobs"],
    queryFn: fetchEnrichmentJobs,
    refetchInterval: 5000, // new jobs/status changes show up without a manual refresh
  });

  const { data: progress, isError: progressError, error: progressErrorObj } = useQuery({
    queryKey: ["job-progress", selectedJobId],
    queryFn: () => fetchJobProgress(selectedJobId as string),
    enabled: !!selectedJobId,
    refetchInterval: (query) => (query.state.data?.process_alive ? 3000 : false),
  });

  return (
    <div className="pipeline-monitor">
      <div className="pipeline-monitor-jobs">
        <h3>Dispatched jobs</h3>
        {jobsLoading && <p>Loading…</p>}
        {jobs && jobs.length === 0 && (
          <p className="empty-state">
            No jobs yet. Dispatch a batch from the "2. Run Vertical Pipelines" tab.
          </p>
        )}
        {jobs && jobs.length > 0 && (
          <table className="accounts-table">
            <thead>
              <tr>
                <th></th>
                <th>Vertical</th>
                <th>Run date</th>
                <th>Dispatched</th>
                <th>Skipped (already enriched)</th>
                <th>Status</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.job_id}
                  className={j.job_id === selectedJobId ? "row-selected" : ""}
                  onClick={() => setSelectedJobId(j.job_id)}
                  style={{ cursor: "pointer" }}
                >
                  <td>
                    <input type="radio" checked={j.job_id === selectedJobId} readOnly />
                  </td>
                  <td>{j.display_vertical}</td>
                  <td>{j.run_date}</td>
                  <td>{j.total_dispatched.toLocaleString()}</td>
                  <td>{j.skipped_already_enriched.toLocaleString()}</td>
                  <td>{j.status}</td>
                  <td>{new Date(j.started_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedJobId && progress && (
        <div className="pipeline-monitor-progress">
          <h3>
            {progress.display_vertical} — job {selectedJobId.slice(0, 8)}…{" "}
            <span className={progress.process_alive ? "status-live" : "status-stopped"}>
              {progress.process_alive ? "● running" : "○ process exited"}
            </span>
          </h3>

          {progress.supabase_error && (
            <p className="action-error">
              Live progress unavailable: {progress.supabase_error}
            </p>
          )}

          <div className="metrics-panel">
            {Object.entries(progress.status_counts).map(([status, count]) => (
              <div key={status} className="metric-tile">
                <div className="metric-value">{count.toLocaleString()}</div>
                <div className="metric-label">{status}</div>
              </div>
            ))}
            <div className="metric-tile">
              <div className="metric-value">${progress.cost_so_far.toFixed(4)}</div>
              <div className="metric-label">cost so far</div>
            </div>
            {progress.heartbeat && (
              <div className="metric-tile">
                <div className="metric-value">
                  {progress.heartbeat.records_done}/{progress.heartbeat.records_total}
                </div>
                <div className="metric-label">
                  heartbeat (last seen {new Date(progress.heartbeat.last_seen_at).toLocaleTimeString()})
                </div>
              </div>
            )}
          </div>

          {progress.heartbeat?.last_error && (
            <p className="action-error">Last worker error: {progress.heartbeat.last_error}</p>
          )}

          <h4>Per-account outputs</h4>
          {progress.results.length === 0 ? (
            <p className="empty-state">No results written yet.</p>
          ) : (
            <table className="accounts-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Status</th>
                  <th>Prospect?</th>
                  <th>Channel / tier</th>
                  <th>Evidence</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {progress.results.map((r) => (
                  <tr key={r.account_id}>
                    <td>{r.account_name ?? r.account_id}</td>
                    <td>{r.status}</td>
                    <td>{r.is_prospect === null ? "—" : r.is_prospect ? "Yes" : "No"}</td>
                    <td>
                      {String(r.enrichment_result?.channel ?? "—")} /{" "}
                      {String(r.enrichment_result?.tier ?? "—")}
                    </td>
                    <td>
                      {r.enrichment_result?.source_url ? (
                        <a href={String(r.enrichment_result.source_url)} target="_blank" rel="noreferrer">
                          evidence
                        </a>
                      ) : (
                        r.error_message ?? "—"
                      )}
                    </td>
                    <td>{r.updated_at ? new Date(r.updated_at).toLocaleTimeString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {selectedJobId && progressError && (
        <p className="action-error">Failed to load job progress: {String(progressErrorObj)}</p>
      )}
    </div>
  );
}
