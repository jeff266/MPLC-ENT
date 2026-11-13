import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchIncomingFiles, uploadWeeklyFiles } from "../api/client";

const ROLE_LABELS: Record<string, string> = {
  salesforce_export: "Salesforce accounts export",
  open_deals: "Open deals",
  activity_90_days: "90-day activity",
  lost_deals_9_months: "Closed-lost (9mo)",
};

const REQUIRED_ROLES = ["salesforce_export", "open_deals"];

/** Jeff (2026-11-12): "wouldn't it be better to add a drop the files
 * feature and it is stored in that directory" — replaces the
 * Finder-navigation workflow (manually placing files in
 * ~/mplc_pop_engine_data/incoming/) with drag-and-drop here. Files land
 * in exactly the same incoming/ directory discover_weekly_files() reads
 * from, so "Run Pipeline" in ActionBar works unchanged once the required
 * files show up matched below. */
export function UploadPanel() {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const incoming = useQuery({
    queryKey: ["incoming-files"],
    queryFn: fetchIncomingFiles,
    refetchOnWindowFocus: true,
  });

  const upload = useMutation({
    mutationFn: uploadWeeklyFiles,
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["incoming-files"] });
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
        ) : (
          <p>Drop this week's Salesforce export files here, or click to browse</p>
        )}
      </div>

      {error && <p className="action-error">Upload failed: {error}</p>}

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
      {missingRequired.length === 0 && incoming.data && incoming.data.files.length > 0 && (
        <p className="upload-ready">Ready — click Run Pipeline below.</p>
      )}
    </div>
  );
}
