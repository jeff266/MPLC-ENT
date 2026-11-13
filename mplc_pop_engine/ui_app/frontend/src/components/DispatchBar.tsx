import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  checkAlreadyEnriched,
  dispatchEnrichment,
  fetchDispatchableVerticals,
  type AccountFilters,
} from "../api/client";
import type { SelectionState } from "../hooks/useSelection";

interface Props {
  selection: SelectionState;
  currentFilters: AccountFilters;
  total: number;
  onDispatched: () => void;
}

/** Step 2 (Jeff, 2026-11-13): "take selected accounts and run it through
 * vertical pipelines + check already enriched accounts to not burn
 * credits." The vertical here is a deliberate user choice — a dropdown —
 * not auto-routed from each account's classified vertical; Step 1's own
 * vertical filter is how the selection gets narrowed down before it
 * reaches this bar. See backend/enrichment.py for the full rationale. */
export function DispatchBar({ selection, currentFilters, total, onDispatched }: Props) {
  const [vertical, setVertical] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: verticals } = useQuery({
    queryKey: ["dispatchable-verticals"],
    queryFn: fetchDispatchableVerticals,
  });

  const buildSelectionReq = (v: string) =>
    selection.mode === "all-filtered"
      ? { filter: currentFilters, exclude_account_ids: Array.from(selection.excludedIds), vertical: v }
      : { account_ids: Array.from(selection.selectedIds), vertical: v };

  const preview = useMutation({
    mutationFn: checkAlreadyEnriched,
    onError: (err: Error) => setError(err.message),
  });

  const dispatch = useMutation({
    mutationFn: dispatchEnrichment,
    onSuccess: () => {
      setError(null);
      preview.reset();
      selection.clearSelection();
      onDispatched();
    },
    onError: (err: Error) => setError(err.message),
  });

  const hasSelection =
    selection.mode === "all-filtered"
      ? total - selection.excludedIds.size > 0
      : selection.selectedIds.size > 0;

  const selectedCountLabel =
    selection.mode === "all-filtered"
      ? `all ${(total - selection.excludedIds.size).toLocaleString()} filtered`
      : `${selection.selectedIds.size.toLocaleString()} selected`;

  const handleCheck = () => {
    if (!vertical) return;
    setError(null);
    preview.mutate(buildSelectionReq(vertical));
  };

  const handleDispatch = () => {
    if (!vertical) return;
    setError(null);
    dispatch.mutate(buildSelectionReq(vertical));
  };

  return (
    <div className="action-bar">
      <div className="action-bar-left">
        <label>
          Vertical pipeline
          <select value={vertical} onChange={(e) => { setVertical(e.target.value); preview.reset(); }}>
            <option value="">Choose a vertical…</option>
            {verticals?.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
          </select>
        </label>
        {hasSelection && <span className="selection-summary">{selectedCountLabel}</span>}
      </div>

      <div className="action-bar-right">
        <button
          type="button"
          onClick={handleCheck}
          disabled={!hasSelection || !vertical || preview.isPending}
        >
          {preview.isPending ? "Checking…" : "Check Already Enriched"}
        </button>

        <button
          type="button"
          className="primary"
          onClick={handleDispatch}
          disabled={!hasSelection || !vertical || dispatch.isPending}
        >
          {dispatch.isPending ? "Dispatching…" : "Run Selected Through Pipeline"}
        </button>
      </div>

      {preview.data && (
        <p className="action-success">
          {preview.data.total_selected.toLocaleString()} selected —{" "}
          {preview.data.already_enriched_count.toLocaleString()} already enriched for{" "}
          {preview.data.vertical} (any run date, will be skipped),{" "}
          {preview.data.to_dispatch_count.toLocaleString()} will actually run.
        </p>
      )}

      {dispatch.isSuccess && (
        <p className="action-success">
          Dispatched job {dispatch.data.job_id.slice(0, 8)}… —{" "}
          {dispatch.data.total_dispatched.toLocaleString()} account(s) running through{" "}
          {dispatch.data.vertical} ({dispatch.data.skipped_already_enriched.toLocaleString()} skipped,
          already enriched). Check the Pipeline Monitor tab for live progress.
        </p>
      )}

      {error && <p className="action-error">{error}</p>}
    </div>
  );
}
