import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchIncomingFiles,
  triggerPipelineRunAuto,
  uploadWeeklyFiles,
  type AutoRunResult,
} from "../api/client";

const ROLE_LABELS: Record<string, string> = {
  salesforce_export: "Salesforce accounts export",
  open_deals: "Open deals",
  activity_90_days: "90-day activity",
  lost_deals_9_months: "Closed-lost (9mo)",
};

const REQUIRED_ROLES = ["salesforce_export", "open_deals"];

interface Props {
  /** Jeff (2026-11-18): "when i drop a file into duplicates, I also want
   * to then pass it into the Find Safe Accounts feature as well. So I'd
   * catch net new AND we can run the rest thru safe to distribute." —
   * when true, a successful upload that satisfies the required roles
   * automatically fires the same pipeline run ActionBar's "Run Pipeline"
   * button triggers, instead of waiting for a manual click. Step 1 keeps
   * the manual button (prop omitted there) since Jeff's "each step is its
   * own distinct module" call still holds for that tab; this is additive,
   * used only where a caller opts in (the Duplicates tab). */
  autoRunAfterUpload?: boolean;
  /** Fires once the auto-triggered run finishes successfully. Lets a
   * caller (e.g. DuplicatesPanel) refresh whatever it shows once the
   * newly-dropped file has actually been ingested and protection-filtered,
   * not just uploaded. */
  onPipelineComplete?: (result: AutoRunResult) => void;
}

/** Jeff (2026-11-12): "wouldn't it be better to add a drop the files
 * feature and it is stored in that directory" — replaces the
 * Finder-navigation workflow (manually placing files in
 * ~/mplc_pop_engine_data/incoming/) with drag-and-drop here. Files land
 * in exactly the same incoming/ directory discover_weekly_files() reads
 * from, so "Run Pipeline" in ActionBar works unchanged once the required
 * files show up matched below. */
export function UploadPanel({ autoRunAfterUpload = false, onPipelineComplete }: Props = {}) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastReplaced, setLastReplaced] = useState<string[]>([]);
  const [autoRunError, setAutoRunError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const incoming = useQuery({
    queryKey: ["incoming-files"],
    queryFn: fetchIncomingFiles,
    refetchOnWindowFocus: true,
  });

  const autoRun = useMutation({
    mutationFn: triggerPipelineRunAuto,
    onSuccess: (result) => {
      setAutoRunError(null);
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      onPipelineComplete?.(result);
    },
    onError: (err: Error) => setAutoRunError(err.message),
  });

  const upload = useMutation({
    mutationFn: uploadWeeklyFiles,
    onSuccess: async (result) => {
      setError(null);
      setAutoRunError(null);
      // Jeff (2026-11-13): "I'd prefer we delete the old files and only
      // work with the new ones" — confirm it actually happened, since a
      // silent delete is as unclear as a silent stale-file bug would be.
      setLastReplaced(result.deleted);
      queryClient.invalidateQueries({ queryKey: ["incoming-files"] });

      if (!autoRunAfterUpload) return;

      // Re-fetch rather than trust the stale `incoming` query snapshot —
      // we need THIS upload's matched roles, not whatever rendered before
      // the drop, to decide whether it's safe to auto-fire the run.
      const fresh = await queryClient.fetchQuery({
        queryKey: ["incoming-files"],
        queryFn: fetchIncomingFiles,
      });
      const freshMatchedRoles = new Set(
        fresh.files.map((f) => f.matched_role).filter((r): r is string => !!r),
      );
      const stillMissing = REQUIRED_ROLES.filter((r) => !freshMatchedRoles.has(r));
      if (stillMissing.length === 0) {
        autoRun.mutate();
      }
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    upload.mutate(Array.from(fileList));
  };

  const matchedRoles = new Set(
    (incoming.data?.files ?? []).map((f) => f.matched_role).filter((r): r is string => !!r),
  );
  const missingRequired = REQUIRED_ROLES.filter((r) => !matchedRoles.has(r));

  return (
    <div className="upload-panel">
      <div
        className={`upload-dropzone${dragOver ? " drag-over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".csv"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />
        {upload.isPending ? (
          <p>Uploading…</p>
        ) : autoRun.isPending ? (
          <p>Running pipeline (~5 min)…</p>
        ) : (
          <p>Drop this week's Salesforce export files here, or click to browse</p>
        )}
      </div>

      {error && <p className="action-error">Upload failed: {error}</p>}
      {autoRunError && <p className="action-error">Pipeline run failed: {autoRunError}</p>}
      {!error && lastReplaced.length > 0 && (
        <p className="upload-ready">Replaced previous version(s): {lastReplaced.join(", ")}</p>
      )}
      {autoRunAfterUpload && autoRun.isSuccess && !autoRun.isPending && (
        <p className="upload-ready">
          Pipeline run complete — {autoRun.data.summary.stage_a.safe_count.toLocaleString()} safe,{" "}
          {autoRun.data.summary.stage_a.excluded_count.toLocaleString()} excluded.
        </p>
      )}

      {incoming.data && incoming.data.files.length > 0 && (
        <table className="incoming-files-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Matched as</th>
            </tr>
          </thead>
          <tbody>
            {incoming.data.files.map((f) => (
              <tr key={f.filename}>
                <td>{f.filename}</td>
                <td>
                  {f.matched_role ? (
                    ROLE_LABELS[f.matched_role] ?? f.matched_role
                  ) : (
                    <span className="unmatched-file">unmatched — won't be used</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {missingRequired.length > 0 && (
        <p className="upload-missing">
          Still need: {missingRequired.map((r) => ROLE_LABELS[r] ?? r).join(", ")}
        </p>
      )}
      {missingRequired.length === 0 &&
        incoming.data &&
        incoming.data.files.length > 0 &&
        !autoRun.isPending && (
          <p className="upload-ready">
            {autoRunAfterUpload
              ? "Ready — the pipeline run fires automatically once both required files are matched."
              : "Ready — click Run Pipeline below."}
          </p>
        )}
    </div>
  );
}
