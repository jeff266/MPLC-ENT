import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, updateSetting, verifySetting, type SettingField, type VerifyResult } from "../api/client";

/** Settings tab. Added 2026-11-14 (Jeff: "would it be good to have a
 * settings page that can store variables and write to the env file? And
 * functions to verify the keys work"). Backend scope/rationale (which vars
 * are managed, exactly what each verify() call does and costs) lives in
 * backend/settings.py's module docstring -- this component just renders
 * that list and wires up the edit/verify actions. Secrets are never sent
 * back from the backend in plaintext (masked_value only shows the last 4
 * characters), so the input here is always write-only: typing a new value
 * and saving replaces it, there's nothing to "reveal". */

const CATEGORY_LABEL: Record<SettingField["category"], string> = {
  secret: "Secret",
  connection: "Connection",
  flag: "Flag",
};

function SettingRow({ field }: { field: SettingField }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);

  const save = useMutation({
    mutationFn: (value: string) => updateSetting(field.key, value),
    onSuccess: () => {
      setDraft("");
      setVerifyResult(null);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const verify = useMutation({
    mutationFn: () => verifySetting(field.key),
    onSuccess: (result) => setVerifyResult(result),
  });

  const isFlag = field.category === "flag";

  return (
    <tr className="settings-row">
      <td>
        <div className="settings-label">{field.label}</div>
        <div className="settings-help">{field.help}</div>
      </td>
      <td>
        <span className={`settings-category settings-category-${field.category}`}>
          {CATEGORY_LABEL[field.category]}
        </span>
      </td>
      <td>
        {field.is_set ? (
          <span className="settings-current-value" title={field.source_file ? `From ${field.source_file}` : undefined}>
            {isFlag ? field.value : field.masked_value}
          </span>
        ) : (
          <span className="settings-unset">not set</span>
        )}
      </td>
      <td>
        <div className="settings-edit">
          {isFlag ? (
            <select
              value={draft || field.value || "true"}
              onChange={(e) => setDraft(e.target.value)}
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input
              type="password"
              placeholder={field.is_set ? "Replace value…" : "Enter value…"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoComplete="off"
            />
          )}
          <button
            type="button"
            className="primary"
            disabled={!draft || save.isPending}
            onClick={() => save.mutate(draft)}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {field.verifiable && (
            <button
              type="button"
              disabled={!field.is_set || verify.isPending}
              onClick={() => verify.mutate()}
              title={!field.is_set ? "Set a value first" : undefined}
            >
              {verify.isPending ? "Verifying…" : "Verify"}
            </button>
          )}
        </div>
        {save.isError && <p className="action-error">{String((save.error as Error)?.message ?? save.error)}</p>}
        {verifyResult && (
          <p className={verifyResult.ok ? "action-success" : "action-error"}>
            {verifyResult.ok ? "✓" : "✗"} {verifyResult.detail}
            <span className="settings-cost-note"> ({verifyResult.cost_note})</span>
          </p>
        )}
      </td>
    </tr>
  );
}

export function Settings() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

  return (
    <div className="settings-tab">
      <p className="step-description">
        API keys and connection strings used by the production enrichment path. Saving writes
        straight to the real <code>.env</code> file the workers read (new keys go to{" "}
        <code>production/workers/.env</code>; an existing key updates wherever it's already
        defined) and takes effect immediately for the next dispatched job — no restart needed.
        Values are never shown back in plaintext once saved.
      </p>

      {isLoading && <p>Loading…</p>}
      {isError && <p className="action-error">Failed to load settings: {String(error)}</p>}

      {data && (
        <table className="accounts-table settings-table">
          <thead>
            <tr>
              <th>Setting</th>
              <th>Type</th>
              <th>Current</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {data.map((field) => (
              <SettingRow key={field.key} field={field} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
