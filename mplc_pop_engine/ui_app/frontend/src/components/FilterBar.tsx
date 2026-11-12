import type { AccountFilters } from "../api/client";

interface Props {
  filters: AccountFilters;
  onChange: (next: AccountFilters) => void;
  verticals: string[];
}

const SEGMENTS = ["SB", "MM", "ENT", "UNRESOLVED"];

// Real values confirmed against the full Salesforce export (2026-11-12):
// 18 distinct Operating Markets, including brand/division splits (CVLI)
// that plain country doesn't carry. Hardcoded rather than derived from
// an API call, same reasoning as KNOWN_VERTICALS in App.tsx.
const OPERATING_MARKETS = [
  "United States", "CVLI United States", "United Kingdom", "Italy", "Germany",
  "Ireland", "Poland", "Singapore", "Spain", "Denmark", "CVLI Denmark",
  "Austria", "Malaysia", "Hungary", "Switzerland", "Hong Kong", "Norway",
  "South Africa",
];

const CAPACITY_TYPES = ["Employees", "Locations", "Rooms", "Area Size", "Students"];

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

      {/* Jeff, 2026-11-12: "I've primarily focused on US MM and Enterprise" —
          country/market narrow down to that scope without hardcoding it,
          since other markets still need to stay reachable for later. */}
      <label>
        Country
        <input
          type="text"
          placeholder="e.g. United States"
          value={filters.country ?? ""}
          onChange={(e) => onChange({ ...filters, country: e.target.value || undefined })}
          list="country-options"
        />
        <datalist id="country-options">
          <option value="United States" />
          <option value="United Kingdom" />
          <option value="Italy" />
          <option value="Germany" />
        </datalist>
      </label>

      <label>
        Operating Market
        <select
          value={filters.operating_market ?? ""}
          onChange={(e) => onChange({ ...filters, operating_market: e.target.value || undefined })}
        >
          <option value="">All</option>
          {OPERATING_MARKETS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>

      <label>
        Capacity Type
        <select
          value={filters.capacity_type ?? ""}
          onChange={(e) => onChange({ ...filters, capacity_type: e.target.value || undefined })}
        >
          <option value="">All</option>
          {CAPACITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label>
        Capacity min
        <input
          type="number"
          min={0}
          value={filters.capacity_min ?? ""}
          onChange={(e) =>
            onChange({
              ...filters,
              capacity_min: e.target.value === "" ? undefined : Number(e.target.value),
            })
          }
        />
      </label>

      <label>
        Capacity max
        <input
          type="number"
          min={0}
          value={filters.capacity_max ?? ""}
          onChange={(e) =>
            onChange({
              ...filters,
              capacity_max: e.target.value === "" ? undefined : Number(e.target.value),
            })
          }
        />
      </label>

      {Object.values(filters).some((v) => v !== undefined) && (
        <button type="button" className="link-button" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </div>
  );
}
