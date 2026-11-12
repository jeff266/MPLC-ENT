import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRuns } from "../api/client";

interface StageCSummary {
  stage_a: { safe_count: number; excluded_count: number };
  stage_b: { verticals: Record<string, number> };
  stage_c: { segments: Record<string, Record<string, number>> };
}

/** Collapsible dashboard metrics above the triage table — Jeff:
 * "Dashboard type metrics can be helpful but collapsible" (2026-11-12).
 * Pulls from the latest PipelineRun's counts_json rather than
 * re-aggregating the accounts table client-side, since the backend
 * already computed and stored these numbers once per run. */
export function MetricsPanel() {
  const [expanded, setExpanded] = useState(false);
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: fetchRuns });

  const latestCompleted = runs?.find((r) => r.status === "completed" && r.counts_json);
  if (!latestCompleted || !latestCompleted.counts_json) {
    return null;
  }

  const summary: StageCSummary = JSON.parse(latestCompleted.counts_json);
  const { safe_count, excluded_count } = summary.stage_a;
  const total = safe_count + excluded_count;

  const segmentTotals: Record<string, number> = {};
  for (const perVertical of Object.values(summary.stage_c.segments)) {
    for (const [segment, count] of Object.entries(perVertical)) {
      segmentTotals[segment] = (segmentTotals[segment] ?? 0) + count;
    }
  }

  return (
    <div className="metrics-panel">
      <button type="button" className="metrics-toggle" onClick={() => setExpanded((e) => !e)}>
        {expanded ? "▾" : "▸"} Run {latestCompleted.run_date} — {total.toLocaleString()} accounts
        ({safe_count.toLocaleString()} safe, {excluded_count.toLocaleString()} excluded)
      </button>

      {expanded && (
        <div className="metrics-body">
          <div className="metrics-row">
            <strong>By segment</strong>
            <ul className="metrics-list">
              {Object.entries(segmentTotals)
                .sort((a, b) => b[1] - a[1])
                .map(([segment, count]) => (
                  <li key={segment}>
                    {segment}: {count.toLocaleString()}
                  </li>
                ))}
            </ul>
          </div>
          <div className="metrics-row">
            <strong>Top verticals</strong>
            <ul className="metrics-list">
              {Object.entries(summary.stage_b.verticals)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 8)
                .map(([vertical, count]) => (
                  <li key={vertical || "(blank)"}>
                    {vertical || "(blank)"}: {count.toLocaleString()}
                  </li>
                ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
