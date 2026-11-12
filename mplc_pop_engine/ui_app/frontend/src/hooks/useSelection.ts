import { useCallback, useMemo, useState } from "react";

/**
 * Selection state for the triage table. Two modes, per Jeff's
 * "select-all-filtered" requirement (2026-11-12): a solo user acting on a
 * whole vertical/segment slice (e.g. all 13,432 Corporations/UNRESOLVED
 * rows) can't be expected to scroll through pages checking boxes one at a
 * time.
 *
 *  - "explicit": selectedIds is the full set of chosen account_ids, built
 *    by checking individual rows across however many pages.
 *  - "all-filtered": every row matching the CURRENT filters is selected,
 *    except whatever's in excludedIds (someone selects all, then
 *    unchecks a couple). The actual id list is resolved server-side by
 *    the backend's `filter` + `exclude_account_ids` — this hook never
 *    needs to know how many rows that really is.
 */
export function useSelection() {
  const [mode, setMode] = useState<"explicit" | "all-filtered">("explicit");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());

  const isSelected = useCallback(
    (accountId: string) =>
      mode === "all-filtered" ? !excludedIds.has(accountId) : selectedIds.has(accountId),
    [mode, selectedIds, excludedIds],
  );

  const toggleRow = useCallback(
    (accountId: string) => {
      if (mode === "all-filtered") {
        setExcludedIds((prev) => {
          const next = new Set(prev);
          if (next.has(accountId)) next.delete(accountId);
          else next.add(accountId);
          return next;
        });
      } else {
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(accountId)) next.delete(accountId);
          else next.add(accountId);
          return next;
        });
      }
    },
    [mode],
  );

  const selectAllFiltered = useCallback(() => {
    setMode("all-filtered");
    setExcludedIds(new Set());
  }, []);

  const clearSelection = useCallback(() => {
    setMode("explicit");
    setSelectedIds(new Set());
    setExcludedIds(new Set());
  }, []);

  /** Count label for the toolbar. In "all-filtered" mode this is an upper
   * bound shown as "~N" until the server resolves the real count, since
   * the hook deliberately never fetches the full id list itself. */
  const summary = useMemo(
    () => ({ mode, selectedCount: selectedIds.size, excludedCount: excludedIds.size }),
    [mode, selectedIds, excludedIds],
  );

  return { mode, isSelected, toggleRow, selectAllFiltered, clearSelection, summary, selectedIds, excludedIds };
}

export type SelectionState = ReturnType<typeof useSelection>;
