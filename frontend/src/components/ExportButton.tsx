import { useState } from "react";
import { ApiError, downloadExport, type ExportKind, type Params } from "../api/client";
import { useAppData } from "../data/AppDataProvider";

/** "Export CSV" for a list, with that list's current filters. Hidden without crm.export. */
export function ExportButton({ kind, filters, onError }: { kind: ExportKind; filters: Params; onError: (message: string) => void }) {
  const { can } = useAppData();
  const [busy, setBusy] = useState(false);
  if (!can("crm.export")) return null;
  return (
    <button
      className="ghost-btn"
      disabled={busy}
      title="Download what this list shows (all pages) as a spreadsheet"
      onClick={async () => {
        setBusy(true);
        try {
          await downloadExport(kind, filters);
        } catch (err) {
          onError(err instanceof ApiError ? err.message : "Couldn't export.");
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "Exporting…" : "Export CSV"}
    </button>
  );
}
