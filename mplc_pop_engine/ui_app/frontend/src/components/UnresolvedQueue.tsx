import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchUnresolvedQueue } from "../api/client";
import { Pagination } from "./Pagination";

const PAGE_SIZE = 50;

/** Stage C's UNRESOLVED pile — currently 100% of Corporate/Healthcare/MDU
 * by design (missing breakroom_documented/facility_type/location_count
 * source data, per roe_rules/*.py's own docstrings — not a pipeline bug).
 * This is the queue for a human to eventually resolve those accounts by
 * hand, or for Jeff to decide those verticals need a different data
 * source before they can ever segment automatically. */
export function UnresolvedQueue() {
  const [vertical, setVertical] = useState<string>("");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["unresolved", vertical, page],
    queryFn: () => fetchUnresolvedQueue(vertical || undefined, page, PAGE_SIZE),
  });

  return (
    <div>
      <div className="filter-bar">
        <label>
          Vertical
          <select
            value={vertical}
            onChange={(e) => {
              setVertical(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="Corporations">Corporations</option>
            <option value="Health Care Services">Health Care Services</option>
            <option value="Multi-Dwelling Units">Multi-Dwelling Units</option>
          </select>
        </label>
      </div>

      {isLoading && <p>Loading…</p>}

      {data && (
        <>
          {data.rows.length === 0 ? (
            <p className="empty-state">No unresolved accounts match this filter.</p>
          ) : (
            <table className="accounts-table">
              <thead>
                <tr>
                  <th>Account ID</th>
                  <th>Name</th>
                  <th>Vertical</th>
                  <th>Reason</th>
                  <th>Edge case</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.account_id}>
                    <td>{row.account_id}</td>
                    <td>{row.account_name}</td>
                    <td>{row.vertical}</td>
                    <td>{row.reason}</td>
                    <td>{row.edge_case ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
