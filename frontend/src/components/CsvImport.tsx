import { useState } from "react";
import { ApiError, importCsv, type ImportKind, type ImportResult } from "../api/client";
import { ErrorNote, Modal } from "../crm/ui";
import { Icon } from "./Icon";

const TEMPLATES: Record<ImportKind, { columns: string[]; rows: string[][]; hint: string }> = {
  leads: {
    columns: ["Name", "Company", "Phone", "Email", "Source", "Notes", "Owner"],
    rows: [
      ["Nisha R", "Kannur Tiles & Co", "94460 44556", "nisha@example.com", "Referral", "Wants a price list", ""],
      ["", "Calicut Build Mart", "98470 11223", "", "IndiaMART", "", ""],
    ],
    hint: "A name or company is required. Owner is a user's name — leave it blank to own them yourself (or to hand them out by the lead rotation, when that's on). Headers like “Mobile” or “Business” work too.",
  },
  customers: {
    columns: ["Name", "GSTIN", "Credit limit"],
    rows: [
      ["Coastal Traders", "32ABCDE1234F1Z9", "150000"],
      ["Rahman Traders", "", "0"],
    ],
    hint: "Name is required. GSTIN is checked (format and check character). Headers like “Party Name” or “GSTIN/UIN” work too.",
  },
};

function toCsv(rows: string[][]): string {
  return rows.map((r) => r.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(",")).join("\n");
}

function downloadTemplate(kind: ImportKind) {
  const t = TEMPLATES[kind];
  const blob = new Blob([toCsv([t.columns, ...t.rows]) + "\n"], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: `${kind}-template.csv` });
  a.click();
  URL.revokeObjectURL(url);
}

/** Pick a CSV, see exactly what will happen (dry run), then import. */
export function CsvImport({ kind, onClose, onImported }: { kind: ImportKind; onClose: () => void; onImported: () => void }) {
  const [fileName, setFileName] = useState("");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noun = kind === "leads" ? "lead" : "customer";

  async function run(commit: boolean, csv = text) {
    setBusy(true);
    setError(null);
    try {
      const result = await importCsv(kind, csv, commit);
      if (commit) {
        setDone(result);
        onImported();
      } else {
        setPreview(result);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the Albiruni API.");
      if (!commit) setPreview(null); // a failed import keeps the preview so it can be retried
    } finally {
      setBusy(false);
    }
  }

  async function pick(file: File | undefined) {
    if (!file) return;
    setFileName(file.name);
    setDone(null);
    const content = await file.text();
    setText(content);
    await run(false, content);
  }

  const shown = preview?.rows.filter((r) => r.status !== "ok").concat(preview.rows.filter((r) => r.status === "ok")).slice(0, 100) ?? [];
  const columns = preview ? Object.keys(preview.columns) : [];

  return (
    <Modal
      title={`Import ${kind} from CSV`}
      onClose={onClose}
      wide
      footer={
        done ? (
          <button className="primary-btn" onClick={onClose}>
            Done
          </button>
        ) : (
          <>
            <button type="button" className="ghost-btn" onClick={onClose}>
              Cancel
            </button>
            <button className="primary-btn" disabled={!preview || preview.ok === 0 || busy} onClick={() => run(true)}>
              {busy ? "Working…" : preview ? `Import ${preview.ok} ${noun}${preview.ok === 1 ? "" : "s"}` : "Import"}
            </button>
          </>
        )
      }
    >
      <div className="import">
        {done ? (
          <div className="notice good">
            Imported {done.created} {noun}
            {done.created === 1 ? "" : "s"}.
            {done.duplicates + done.errors > 0 && ` Skipped ${done.duplicates} duplicate${done.duplicates === 1 ? "" : "s"} and ${done.errors} with errors.`}
          </div>
        ) : (
          <>
            <p className="card-note" style={{ marginTop: 0 }}>
              {TEMPLATES[kind].hint}{" "}
              <button type="button" className="link-btn" style={{ padding: 0 }} onClick={() => downloadTemplate(kind)}>
                Download a template
              </button>
            </p>
            <label className="file-drop">
              <Icon name="file" />
              <span>{fileName || "Choose a .csv file"}</span>
              <input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0])} />
            </label>
            <ErrorNote message={error} />
            {busy && !preview && <p className="card-note">Checking the file…</p>}
          </>
        )}

        {preview && !done && (
          <>
            <div className="import-counts">
              <span className="badge good">{preview.ok} ready</span>
              <span className="badge muted">{preview.duplicates} duplicate{preview.duplicates === 1 ? "" : "s"} (skipped)</span>
              <span className={`badge ${preview.errors ? "bad" : "muted"}`}>
                {preview.errors} with errors (skipped)
              </span>
            </div>
            <p className="card-note">
              Read columns: {Object.entries(preview.columns).map(([k, h]) => `${h} → ${k.replace("_", " ")}`).join(" · ")}
            </p>
            <div className="table-wrap import-table">
              <table>
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Status</th>
                    {columns.map((c) => (
                      <th key={c}>{c.replace("_", " ")}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.line}>
                      <td className="num">{r.line}</td>
                      <td>
                        <span className={`badge ${r.status === "ok" ? "good" : r.status === "duplicate" ? "muted" : "bad"}`}>
                          {r.status === "ok" ? "Ready" : r.status === "duplicate" ? "Duplicate" : "Error"}
                        </span>
                        {r.messages.length > 0 && <span className="sub">{r.messages.join(" ")}</span>}
                      </td>
                      {columns.map((c) => (
                        <td key={c}>{r.values[c] || "—"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.total > shown.length && (
              <p className="card-note">Showing problems first, then the first rows — {preview.total} rows in total.</p>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
