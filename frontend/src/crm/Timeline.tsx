import { useEffect, useState } from "react";
import { ApiError, type TimelineEntry } from "../api/client";
import { dateTime } from "../lib/format";
import { ErrorNote } from "./ui";

const SOURCE: Record<TimelineEntry["source"], string | null> = { app: null, ask_erp: "Ask ERP", import: "CSV import" };

/** Who changed what on a record, newest first. `version` refetches after an edit. */
export function Timeline({ load, version = 0 }: { load: () => Promise<TimelineEntry[]>; version?: number }) {
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    load()
      .then((rows) => current && (setEntries(rows), setError(null)))
      .catch((err) => current && setError(err instanceof ApiError ? err.message : "Couldn't load the history."));
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  if (error) return <ErrorNote message={error} />;
  if (entries === null) return <p className="card-note">Loading history…</p>;
  if (entries.length === 0) return <p className="card-note">No changes recorded yet — changes are tracked from now on.</p>;

  return (
    <ol className="timeline">
      {entries.map((e) => (
        <li key={e.id} className={`tl-${e.action}`}>
          <div className="tl-summary">
            {e.record_type === "lead" && entries.some((x) => x.record_type !== "lead") && <span className="badge muted">Lead</span>}
            {e.summary}
          </div>
          <div className="tl-meta">
            {e.actor_name ?? "System"} · {dateTime(e.at)}
            {SOURCE[e.source] && <span className="badge accent">{SOURCE[e.source]}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}
