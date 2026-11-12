import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAccounts, type AccountFilters } from "./api/client";
import { FilterBar } from "./components/FilterBar";
import { MetricsPanel } from "./components/MetricsPanel";
import { AccountsTable } from "./components/AccountsTable";
import { Pagination } from "./components/Pagination";
import { ActionBar } from "./components/ActionBar";
import { useSelection } from "./hooks/useSelection";
import "./App.css";

// Known verticals from the latest validated pipeline run (2026-11-11) —
// hardcoded rather than derived, since the backend has no "distinct
// verticals" endpoint today. Covers the real buckets Stage B produces;
// an unlisted one still works via "All" + visual inspection, it's just
// not in this dropdown.
const KNOWN_VERTICALS = [
  "Restaurants, Clubs, Pubs",
  "Corporations",
  "Health Care Services",
  "Multi-Dwelling Units",
  "Car Dealerships",
  "Dentists",
  "Education",
  "Religious Institutions",
  "Short-term Lodging",
  "Communal Living Facilities",
  "Activity Centers",
  "Government and Similar Buildings & Services",
  "",
];

const PAGE_SIZE = 50;

function App() {
  const [filters, setFilters] = useState<AccountFilters>({});
  const [page, setPage] = useState(1);
  const selection = useSelection();
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["accounts", filters, page],
    queryFn: () => fetchAccounts(filters, page, PAGE_SIZE),
  });

  const handleFiltersChange = (next: AccountFilters) => {
    setFilters(next);
    setPage(1);
    selection.clearSelection();
  };

  const handlePipelineRunComplete = () => {
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>MPLC PoP Detection Engine</h1>
      </header>

      <MetricsPanel />

      <FilterBar filters={filters} onChange={handleFiltersChange} verticals={KNOWN_VERTICALS} />

      <ActionBar
        selection={selection}
        currentFilters={filters}
        total={data?.total ?? 0}
        onPipelineRunComplete={handlePipelineRunComplete}
      />

      {isLoading && <p>Loading…</p>}
      {isError && <p className="action-error">Failed to load accounts: {String(error)}</p>}

      {data && (
        <>
          <AccountsTable rows={data.rows} selection={selection} />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}

export default App;
