import { useState } from "react";
import { ApiError } from "../api/client";
import { useAppData } from "../data/AppDataProvider";

/** Who a sale counts for (targets, commission); changeable when `onSave` is given. */
export function SalespersonField({
  id,
  name,
  onSave,
}: {
  id: string | null;
  name: string | null;
  onSave?: (userId: string | null) => Promise<void>;
}) {
  const { assignees } = useAppData();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <span>Salesperson</span>
      {onSave ? (
        <select
          value={id ?? ""}
          disabled={busy}
          aria-label="Salesperson"
          onChange={async (e) => {
            setBusy(true);
            setError(null);
            try {
              await onSave(e.target.value || null);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Couldn't change the salesperson.");
            } finally {
              setBusy(false);
            }
          }}
        >
          <option value="">Nobody</option>
          {id && !assignees.some((a) => a.id === id) && <option value={id}>{name ?? "Former user"}</option>}
          {assignees.map((a) => (
            <option key={a.id} value={a.id}>
              {a.display_name}
            </option>
          ))}
        </select>
      ) : (
        <p>{name ?? "—"}</p>
      )}
      {error && <small className="below-list">{error}</small>}
    </div>
  );
}
