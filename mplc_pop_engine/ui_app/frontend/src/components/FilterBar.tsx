import type { AccountFilters } from "../api/client";

interface Props {
  filters: AccountFilters;
  onChange: (next: AccountFilters) => void;
  verticals: string[];
}

const SEGMENTS = ["SB", "MM", "ENT", "UNRESOLVED"];

export function FilterBar({ filters, onChange, verticals }: Props) {
  return (
    <div className="filter-bar">
      <label>
        Vertical
        <select
          value={filters.vertical ?? ""}
          onChange={(e) => onChange({ ...filters, vertical: e.target.value || undefined })}
        >
          <option value="">All</option>
          {verticals.map((v) => (
            <option key={v || "(blank)"} value={v}>
              {v || "(blank)"}
            </option>
          ))}
        </select>
      </label>

      <label>
        Segment
        <select
          value={filters.segment ?? ""}
          onChange={(e) => onChange({ ...filters, segment: e.target.value || undefined })}
        >
          <option value="">All</option>
          {SEGMENTS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      <label>
        Excluded
        <select
          value={filters.excluded === undefined ? "" : String(filters.excluded)}
          onChange={(e) =>
            onChange({
              ...filters,
              excluded: e.target.value === "" ? undefined : e.target.value === "true",
            })
          }
        >
          <option value="">All</option>
          <option value="false">Safe only</option>
          <option value="true">Excluded only</option>
        </select>
      </label>

      {(filters.vertical || filters.segment || filters.excluded !== undefined) && (
        <button type="button" className="link-button" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </div>
  );
}
