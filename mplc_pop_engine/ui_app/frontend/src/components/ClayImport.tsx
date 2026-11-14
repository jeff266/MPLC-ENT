import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ClayColumnMapping,
  ClayImportResult,
  detectClayColumns,
  runClayDedupe,
} from "../api/client";

const MAPPING_FIELDS: { key: keyof ClayColumnMapping; label: string; required: boolean }[] = [
  { key: "company_name", label: "Company name", required: true },
  { key: "website", label: "Website", required: true },
  { key: "phone", label: "Phone", required: false },
  { key: "address", label: "Address", required: false },
  { key: "city", label: "City", required: false },
  { key: "state", label: "State", required: false },
];

/** Upload a Clay/ZoomInfo/other export, review (and correct) the
 * auto-detected column mapping, then run the dedupe against this app's
 * own Salesforce universe. Closes the gap Jeff flagged (2026-11-14):
 * "export data from ZoomInfo or Clay, cross-reference against Salesforce"
 * -- clay_dedupe.py already did this as a standalone CLI; this is the
 * missing UI path that writes into the same clay_matches table the
 * "Clay Ambiguous" queue below already reads.
 *
 * The mapping step is NOT optional or hidden: column naming is
 * inconsistent across export tools (Clay vs. ZoomInfo vs. others), so the
 * auto-detected guess is shown as an editable form the person confirms
 * before anything runs -- never applied blind (same bar CLAUDE.md sets
 * for entity attribution elsewhere in this pipeline: a silently wrong
 * mapping is worse than one flagged for a human to fix). */
export function ClayImport() {
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Partial<ClayColumnMapping> | null>(null);
  const [columns, setColumns] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, string>[]>([]);
  const [rowCount, setRowCount] = useState<number>(0);
  const [result, setResult] = useState<ClayImportResult | null>(null);

  const detectMutation = useMutation({
    mutationFn: (f: File) => detectClayColumns(f),
    onSuccess: (data) => {
      setMapping(data.detected_mapping);
      setColumns(data.columns);
      setPreviewRows(data.preview_rows);
      setRowCount(data.row_count);
      setResult(null);
    },
  });

  const runMutation = useMutation({
    mutationFn: () => {
      if (!file || !mapping) throw new Error("Pick a file and confirm the column mapping first");
      return runClayDedupe(file, mapping);
    },
    onSuccess: (data) => setResult(data),
  });

  function handleFileChange(f: File | null) {
    setFile(f);
    setMapping(null);
    setResult(null);
    if (f) detectMutation.mutate(f);
  }

  const requiredFieldsMissing = MAPPING_FIELDS.filter(
    (f) => f.required && !mapping?.[f.key],
  );

  return (
    <div className="clay-import">
      <p className="step-description">
        Upload a Clay, ZoomInfo, or other export CSV to check it against the Salesforce
        accounts already loaded into this app (from Step 1's weekly upload) — net-new vs.
        already in Salesforce, and whether an existing match is currently protected or
        available.
      </p>

      <input
        type="file"
        accept=".csv,.xlsx,.xls"
        onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
      />

      {detectMutation.isPending && <p>Reading file…</p>}
      {detectMutation.isError && (
        <p className="action-error">
          Could not read that file: {String(detectMutation.error)}
        </p>
      )}

      {mapping && (
        <div className="clay-mapping-form">
          <h3>Confirm column mapping</h3>
          <p className="field-hint">
            {rowCount.toLocaleString()} rows found. Auto-detected below from the real
            headers in your file — naming varies across export tools, so check these
            before running.
          </p>
          <table className="mapping-table">
            <tbody>
              {MAPPING_FIELDS.map((f) => (
                <tr key={f.key}>
                  <td>
                    {f.label}
                    {f.required && <span className="required-marker"> *</span>}
                  </td>
                  <td>
                    <select
                      value={mapping[f.key] ?? ""}
                      onChange={(e) =>
                        setMapping((prev) => ({
                          ...(prev ?? {}),
                          [f.key]: e.target.value || null,
                        }))
                      }
                    >
                      <option value="">— not mapped —</option>
                      {columns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {requiredFieldsMissing.length > 0 && (
            <p className="field-hint">
              Required: {requiredFieldsMissing.map((f) => f.label).join(", ")}
            </p>
          )}

          {previewRows.length > 0 && (
            <>
              <h4>Preview (first {previewRows.length} rows)</h4>
              <table className="accounts-table">
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, i) => (
                    <tr key={i}>
                      {columns.map((c) => (
                        <td key={c}>{row[c]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <button
            type="button"
            disabled={requiredFieldsMissing.length > 0 || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? "Running…" : "Run dedupe against Salesforce"}
          </button>
        </div>
      )}

      {runMutation.isError && (
        <p className="action-error">Dedupe failed: {String(runMutation.error)}</p>
      )}

      {result && (
        <div className="clay-import-result">
          <h3>Done</h3>
          <p>
            {result.rows_processed.toLocaleString()} rows processed, batch{" "}
            <code>{result.batch_id}</code>.
          </p>
          <ul>
            {Object.entries(result.classification_counts).map(([cls, count]) => (
              <li key={cls}>
                {cls}: {count.toLocaleString()}
              </li>
            ))}
          </ul>
          {result.ambiguous_count > 0 && (
            <p>
              {result.ambiguous_count.toLocaleString()} row(s) matched more than one
              Salesforce account — see the Clay Ambiguous queue below to resolve them.
            </p>
          )}
          {!result.eligibility_data_available && (
            <p className="field-hint">
              No eligibility run found yet — matches couldn't be split into
              protected/available (they're classified MATCHED_UNKNOWN instead). Run Step 1
              to populate that.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
