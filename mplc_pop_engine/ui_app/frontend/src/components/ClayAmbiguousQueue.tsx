import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchClayAmbiguousQueue } from "../api/client";
import { Pagination } from "./Pagination";

const PAGE_SIZE = 50;

/** Clay-dedupe rows with more than one Salesforce candidate (clay_dedupe.py's
 * "ambiguous" classification) — needs a human pick, since the tool can't
 * safely guess between 2+ equally-plausible matches. Empty today because
 * no Clay batch has been run through the DB-backed path yet (clay_dedupe.py
 * was validated standalone against a 1,758-row export, but hasn't written
 * into clay_matches). That's expected, not a bug. */
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
        No ambiguous Clay matches yet — nothing has been run through the Clay dedupe tool
        against this database.
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
            <th># candidates</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.id}>
              <td>{row.clay_company_name}</td>
              <td>{row.clay_website}</td>
              <td>{row.classification}</td>
              <td>{row.match_method ?? "—"}</td>
              <td>{row.num_candidates}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
    </div>
  );
}
