import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchClayAmbiguousQueue } from "../api/client";
import { Pagination } from "./Pagination";

const PAGE_SIZE = 50;

const CLASSIFICATION_LABELS: Record<string, string> = {
  POSSIBLE_MATCH_BRAND: "Possible match (brand-root fuzzy)",
};

/** Human-review queue for Clay dedupe rows: either more than one
 * Salesforce candidate (clay_dedupe.py can't safely guess between 2+
 * equally-plausible matches), or a brand-root fuzzy hit -- added
 * 2026-11-16, Jeff: "Exact match is useless for me". Real MDU/real-estate
 * operators often sit in Salesforce under a different legal-entity name
 * and domain than a prospect list (e.g. "Cortland Partners, LLC" /
 * cortland.com in Salesforce vs. "Cortland Development, LLC" /
 * cortlandpartners.com on a prospect list) -- a brand-root match always
 * lands here for a human to confirm or reject, even with a single
 * candidate, since fuzzy matching is never auto-trusted the way an exact
 * domain/name match is. */
export function ClayAmbiguousQueue() {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["clay-ambiguous", page],
    queryFn: () => fetchClayAmbiguousQueue(undefined, page, PAGE_SIZE),
  });

  if (isLoading) return <p>Loading…</p>;
  if (!data) return null;

  if (data.rows.length === 0) {
    return (
      <p className="empty-state">
        Nothing needs review right now — no Clay dedupe rows with multiple candidates or a
        brand-root fuzzy match.
      </p>
    );
  }

  return (
    <div>
      <table className="accounts-table">
        <thead>
          <tr>
            <th>Clay company name</th>
            <th>Clay website</th>
            <th>Classification</th>
            <th>Match method</th>
            <th>Confidence</th>
            <th>Salesforce candidate</th>
            <th># candidates</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.id}>
              <td>{row.clay_company_name}</td>
              <td>{row.clay_website}</td>
              <td>{CLASSIFICATION_LABELS[row.classification] ?? row.classification}</td>
              <td>{row.match_method ?? "—"}</td>
              <td>{row.match_confidence ?? "—"}</td>
              <td title={row.matched_account_id ?? undefined}>
                {row.matched_account_name ?? "—"}
                {row.num_candidates > 1 ? ` (+${row.num_candidates - 1} more)` : ""}
              </td>
              <td>{row.num_candidates}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
    </div>
  );
}
