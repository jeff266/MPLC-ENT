import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  checkAlreadyEnriched,
  dispatchEnrichment,
  fetchCostEstimate,
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
  const [disabledChannels, setDisabledChannels] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data: verticals } = useQuery({
    queryKey: ["dispatchable-verticals"],
    queryFn: fetchDispatchableVerticals,
  });

  // Jeff (2026-11-13): "Some steps in the pipeline are not always
  // required. Like maybe I don't want YouTube on a particular run." —
  // only the paid channels are toggleable (see backend/enrichment.py's
  // CHANNEL_ENV_VARS for why); the list itself comes from the backend so
  // this component never has its own copy to go stale.
  const toggleableChannels = verticals?.find((v) => v.key === vertical)?.toggleable_channels ?? [];

  const toggleChannel = (channelKey: string) => {
    setDisabledChannels((prev) => {
      const next = new Set(prev);
      if (next.has(channelKey)) next.delete(channelKey);
      else next.add(channelKey);
      return next;
    });
  };

  const buildSelectionReq = (v: string) => {
    const base = selection.mode === "all-filtered"
      ? { filter: currentFilters, exclude_account_ids: Array.from(selection.excludedIds), vertical: v }
      : { account_ids: Array.from(selection.selectedIds), vertical: v };
    return disabledChannels.size > 0 ? { ...base, disabled_channels: Array.from(disabledChannels) } : base;
  };

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

  const rawSelectedCount =
    selection.mode === "all-filtered"
      ? total - selection.excludedIds.size
      : selection.selectedIds.size;

  // Once "Check Already Enriched" has run, estimate off the count that
  // will ACTUALLY dispatch (post-dedup), not the raw selection — a
  // selection that's mostly already-enriched accounts would otherwise
  // produce a wildly overstated estimate.
  const estimateAccountCount = preview.data?.to_dispatch_count ?? rawSelectedCount;
  const disabledChannelsArray = Array.from(disabledChannels).sort();

  const { data: costEstimate, isFetching: estimateLoading } = useQuery({
    queryKey: ["cost-estimate", vertical, estimateAccountCount, disabledChannelsArray],
    queryFn: () =>
      fetchCostEstimate({
        vertical,
        account_count: estimateAccountCount,
        disabled_channels: disabledChannelsArray.length > 0 ? disabledChannelsArray : undefined,
      }),
    enabled: hasSelection && !!vertical && estimateAccountCount > 0,
  });

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
          <select
            value={vertical}
            onChange={(e) => {
              setVertical(e.target.value);
              setDisabledChannels(new Set()); // different vertical = different toggleable channels
              preview.reset();
            }}
          >
            <option value="">Choose a vertical…</option>
            {verticals?.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
          </select>
        </label>

        {toggleableChannels.length > 0 && (
          <div className="channel-toggles">
            {toggleableChannels.map((c) => (
              <label key={c.key} className="channel-toggle">
                <input
                  type="checkbox"
                  checked={!disabledChannels.has(c.key)}
                  onChange={() => toggleChannel(c.key)}
                />
                {c.label}
              </label>
            ))}
          </div>
        )}

        {hasSelection && <span className="selection-summary">{selectedCountLabel}</span>}

        {hasSelection && vertical && (
          <div className="cost-estimate">
            {estimateLoading && <span className="cost-estimate-loading">Estimating cost…</span>}
            {!estimateLoading && costEstimate && costEstimate.estimable && (
              <span className={costEstimate.directional ? "cost-estimate-directional" : ""}>
                Est. ~${costEstimate.estimated_total_cost.toFixed(2)} total (~$
                {costEstimate.cost_per_account.toFixed(4)}/account) for{" "}
                {costEstimate.account_count.toLocaleString()} account(s)
                {costEstimate.directional
                  ? ` — directional only, based on just ${costEstimate.based_on_historical_accounts} historical accounts`
                  : ` — based on ${costEstimate.based_on_historical_accounts.toLocaleString()} historical accounts`}
                {costEstimate.excluded_channels.length > 0 && (
                  <> (excludes disabled channel{costEstimate.excluded_channels.length > 1 ? "s" : ""}:{" "}
                  {costEstimate.excluded_channels.map((c) => c.channel).join(", ")})</>
                )}
              </span>
            )}
            {!estimateLoading && costEstimate && !costEstimate.estimable && (
              <span className="cost-estimate-unavailable">{costEstimate.reason}</span>
            )}
          </div>
        )}
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
