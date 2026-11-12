import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  downloadBlob,
  findEnrichableAccounts,
  triggerPipelineRunAuto,
  type AccountFilters,
} from "../api/client";
import type { SelectionState } from "../hooks/useSelection";

interface Props {
  selection: SelectionState;
  currentFilters: AccountFilters;
  total: number;
  onPipelineRunComplete: () => void;
}

/** The two real actions in this tool today (Jeff, 2026-11-12): the manual
 * "run the pipeline" trigger, and "Find Enrichable Accounts" on whatever's
 * selected in the triage table. Deliberately not a generic action-type
 * dropdown — there's exactly one real verb for row selection right now. */
export function ActionBar({ selection, currentFilters, total, onPipelineRunComplete }: Props) {
  const [runError, setRunError] = useState<string | null>(null);
  const [findError, setFindError] = useState<string | null>(null);

  const runPipeline = useMutation({
    mutationFn: triggerPipelineRunAuto,
    onSuccess: () => {
      setRunError(null);
      onPipelineRunComplete();
    },
    onError: (err: Error) => setRunError(err.message),
  });

  const findEnrichable = useMutation({
    mutationFn: findEnrichableAccounts,
    onSuccess: (result) => {
      setFindError(null);
      downloadBlob(result.csvBlob, `enrichable_accounts_${new Date().toISOString().slice(0, 10)}.csv`);
      if (result.missingCount > 0) {
        setFindError(`${result.missingCount} selected account(s) were not found and were skipped.`);
      }
      selection.clearSelection();
    },
    onError: (err: Error) => setFindError(err.message),
  });

  const handleFindEnrichable = () => {
    if (selection.mode === "all-filtered") {
      findEnrichable.mutate({
        filter: currentFilters,
        exclude_account_ids: Array.from(selection.excludedIds),
      });
    } else {
      findEnrichable.mutate({ account_ids: Array.from(selection.selectedIds) });
    }
  };

  const hasSelection =
    selection.mode === "all-filtered"
      ? total - selection.excludedIds.size > 0
      : selection.selectedIds.size > 0;

  const selectedCountLabel =
    selection.mode === "all-filtered"
      ? `all ${(total - selection.excludedIds.size).toLocaleString()} filtered`
      : `${selection.selectedIds.size.toLocaleString()} selected`;

  return (
    <div className="action-bar">
      <div className="action-bar-left">
        <button type="button" onClick={() => selection.selectAllFiltered()} disabled={total === 0}>
          Select all {total.toLocaleString()} filtered
        </button>
        {(selection.selectedIds.size > 0 || selection.mode === "all-filtered") && (
          <button type="button" className="link-button" onClick={() => selection.clearSelection()}>
            Clear selection
          </button>
        )}
        {hasSelection && <span className="selection-summary">{selectedCountLabel}</span>}
      </div>

      <div className="action-bar-right">
        <button
          type="button"
          onClick={handleFindEnrichable}
          disabled={!hasSelection || findEnrichable.isPending}
        >
          {findEnrichable.isPending ? "Working…" : "Find Enrichable Accounts"}
        </button>

        <button
          type="button"
          className="primary"
          onClick={() => runPipeline.mutate()}
          disabled={runPipeline.isPending}
        >
          {runPipeline.isPending ? "Running pipeline (~5 min)…" : "Run Pipeline"}
        </button>
      </div>

      {findError && <p className="action-error">{findError}</p>}
      {runError && <p className="action-error">Pipeline run failed: {runError}</p>}
      {runPipeline.isSuccess && (
        <p className="action-success">
          Pipeline run complete for {runPipeline.data.run_date}: {" "}
          {runPipeline.data.summary.stage_a.safe_count.toLocaleString()} safe,{" "}
          {runPipeline.data.summary.stage_a.excluded_count.toLocaleString()} excluded.
        </p>
      )}
    </div>
  );
}
