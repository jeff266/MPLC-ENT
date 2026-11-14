import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAccounts, type AccountFilters } from "./api/client";
import { FilterBar } from "./components/FilterBar";
import { UploadPanel } from "./components/UploadPanel";
import { MetricsPanel } from "./components/MetricsPanel";
import { AccountsTable } from "./components/AccountsTable";
import { Pagination } from "./components/Pagination";
import { ActionBar } from "./components/ActionBar";
import { DispatchBar } from "./components/DispatchBar";
import { PipelineMonitor } from "./components/PipelineMonitor";
import { UnresolvedQueue } from "./components/UnresolvedQueue";
import { ClayAmbiguousQueue } from "./components/ClayAmbiguousQueue";
import { CostTracker } from "./components/CostTracker";
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

type Tab = "step1" | "step2" | "step3" | "unresolved" | "clay" | "cost-tracker";

function App() {
  const [tab, setTab] = useState<Tab>("step1");

  // Step 1 (Find Safe Accounts) state — its own filters/selection, used by
  // the "Find Enrichable Accounts" export and the manual pipeline-run
  // trigger.
  const [filters1, setFilters1] = useState<AccountFilters>({});
  const [page1, setPage1] = useState(1);
  const selection1 = useSelection();

  // Step 2 (Run Vertical Pipelines) state — a SEPARATE filter/selection,
  // per Jeff's "take each step as its own distinct module" (2026-11-13):
  // this is choosing which accounts to actually dispatch to a worker, a
  // different decision from Step 1's "find enrichable" export, even
  // though it reads from the same underlying accounts table.
  const [filters2, setFilters2] = useState<AccountFilters>({});
  const [page2, setPage2] = useState(1);
  const selection2 = useSelection();

  const queryClient = useQueryClient();

  const { data: data1, isLoading: loading1, isError: error1, error: errorObj1 } = useQuery({
    queryKey: ["accounts", filters1, page1],
    queryFn: () => fetchAccounts(filters1, page1, PAGE_SIZE),
    enabled: tab === "step1",
  });

  const { data: data2, isLoading: loading2, isError: error2, error: errorObj2 } = useQuery({
    queryKey: ["accounts", filters2, page2],
    queryFn: () => fetchAccounts(filters2, page2, PAGE_SIZE),
    enabled: tab === "step2",
  });

  const handleFilters1Change = (next: AccountFilters) => {
    setFilters1(next);
    setPage1(1);
    selection1.clearSelection();
  };

  const handleFilters2Change = (next: AccountFilters) => {
    setFilters2(next);
    setPage2(1);
    selection2.clearSelection();
  };

  const handlePipelineRunComplete = () => {
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
  };

  const handleDispatched = () => {
    queryClient.invalidateQueries({ queryKey: ["enrichment-jobs"] });
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>MPLC PoP Detection Engine</h1>
      </header>

      <MetricsPanel />

      <nav className="tab-bar">
        <button type="button" className={tab === "step1" ? "tab-active" : ""} onClick={() => setTab("step1")}>
          1. Find Safe Accounts
        </button>
        <button type="button" className={tab === "step2" ? "tab-active" : ""} onClick={() => setTab("step2")}>
          2. Run Vertical Pipelines
        </button>
        <button type="button" className={tab === "step3" ? "tab-active" : ""} onClick={() => setTab("step3")}>
          3. Pipeline Monitor
        </button>
        <button
          type="button"
          className={tab === "unresolved" ? "tab-active" : ""}
          onClick={() => setTab("unresolved")}
        >
          Unresolved Queue
        </button>
        <button type="button" className={tab === "clay" ? "tab-active" : ""} onClick={() => setTab("clay")}>
          Clay Ambiguous
        </button>
        <button
          type="button"
          className={tab === "cost-tracker" ? "tab-active" : ""}
          onClick={() => setTab("cost-tracker")}
        >
          Cost Tracker
        </button>
      </nav>

      {tab === "step1" && (
        <>
          <UploadPanel />

          <FilterBar filters={filters1} onChange={handleFilters1Change} verticals={KNOWN_VERTICALS} />

          <ActionBar
            selection={selection1}
            currentFilters={filters1}
            total={data1?.total ?? 0}
            onPipelineRunComplete={handlePipelineRunComplete}
          />

          {loading1 && <p>Loading…</p>}
          {error1 && <p className="action-error">Failed to load accounts: {String(errorObj1)}</p>}

          {data1 && (
            <>
              <AccountsTable rows={data1.rows} selection={selection1} />
              <Pagination page={page1} pageSize={PAGE_SIZE} total={data1.total} onPageChange={setPage1} />
            </>
          )}
        </>
      )}

      {tab === "step2" && (
        <>
          <p className="step-description">
            Select the accounts you want to run through a vertical pipeline, choose the pipeline,
            and dispatch. Accounts already enriched for that vertical (any run date) are skipped
            automatically so credits aren't burned re-processing them.
          </p>

          <FilterBar filters={filters2} onChange={handleFilters2Change} verticals={KNOWN_VERTICALS} />

          <DispatchBar
            selection={selection2}
            currentFilters={filters2}
            total={data2?.total ?? 0}
            onDispatched={handleDispatched}
          />

          {loading2 && <p>Loading…</p>}
          {error2 && <p className="action-error">Failed to load accounts: {String(errorObj2)}</p>}

          {data2 && (
            <>
              <AccountsTable rows={data2.rows} selection={selection2} />
              <Pagination page={page2} pageSize={PAGE_SIZE} total={data2.total} onPageChange={setPage2} />
            </>
          )}
        </>
      )}

      {tab === "step3" && <PipelineMonitor />}
      {tab === "unresolved" && <UnresolvedQueue />}
      {tab === "clay" && <ClayAmbiguousQueue />}
      {tab === "cost-tracker" && <CostTracker />}
    </div>
  );
}

export default App;
