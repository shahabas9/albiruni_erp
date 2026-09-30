import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { ErrorNote, Modal } from "./ui";

export interface DuplicateRecord {
  id: string;
  title: string;
  detail: string;
}

/** Groups of likely duplicates; pick the one to keep and merge the rest into it. */
export function MergeDuplicates({
  noun,
  load,
  merge,
  explain,
  onClose,
  onMerged,
}: {
  noun: string;
  load: () => Promise<{ reason: string; records: DuplicateRecord[] }[]>;
  merge: (keepId: string, removeId: string) => Promise<unknown>;
  explain: string;
  onClose: () => void;
  onMerged: () => void;
}) {
  const [groups, setGroups] = useState<{ reason: string; records: DuplicateRecord[] }[] | null>(null);
  const [keep, setKeep] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(0);

  async function refresh() {
    try {
      const g = await load();
      setGroups(g);
      setKeep(Object.fromEntries(g.map((grp, i) => [i, grp.records[0]!.id])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't look for duplicates.");
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function mergeGroup(i: number) {
    const group = groups![i]!;
    const keepId = keep[i]!;
    const others = group.records.filter((r) => r.id !== keepId);
    if (!window.confirm(`Merge ${others.length} ${noun}${others.length === 1 ? "" : "s"} into “${group.records.find((r) => r.id === keepId)!.title}”? This can't be undone.`)) return;
    setBusy(i);
    setError(null);
    try {
      for (const other of others) await merge(keepId, other.id);
      setDone((n) => n + others.length);
      onMerged();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't merge.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal title={`Duplicate ${noun}s`} onClose={onClose} wide footer={<button className="primary-btn" onClick={onClose}>Done</button>}>
      <p className="card-note" style={{ marginTop: 0 }}>{explain}</p>
      {done > 0 && <div className="notice good">Merged {done} {noun}{done === 1 ? "" : "s"}.</div>}
      <ErrorNote message={error} />
      {groups === null && !error && <p className="card-note">Looking for duplicates…</p>}
      {groups?.length === 0 && <p className="card-note">No likely duplicates found.</p>}
      {groups?.map((g, i) => (
        <fieldset className="choice-list dup-group" key={g.records.map((r) => r.id).join()}>
          <legend>{g.reason} — keep which one?</legend>
          {g.records.map((r) => (
            <label key={r.id} className={keep[i] === r.id ? "on" : ""}>
              <input type="radio" name={`keep-${i}`} checked={keep[i] === r.id} onChange={() => setKeep({ ...keep, [i]: r.id })} />
              <span>
                <b>{r.title}</b>
                <small>{r.detail}</small>
              </span>
            </label>
          ))}
          <div>
            <button className="primary-btn sm" disabled={busy !== null} onClick={() => mergeGroup(i)}>
              {busy === i ? "Merging…" : `Merge ${g.records.length - 1} into the one kept`}
            </button>
          </div>
        </fieldset>
      ))}
    </Modal>
  );
}
