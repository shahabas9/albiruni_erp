import { useEffect, useState } from "react";
import { fetchStates, type GstState } from "../api/sales";

/** GST state picker. `value` is a two-digit state code ("" for none). */
export function StateSelect({
  value,
  onChange,
  disabled,
  emptyLabel = "Not set",
}: {
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
  emptyLabel?: string;
}) {
  const [states, setStates] = useState<GstState[]>([]);
  useEffect(() => {
    let live = true;
    fetchStates()
      .then((s) => live && setStates(s))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  const known = states.some((s) => s.code === value);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="">{emptyLabel}</option>
      {value && !known && <option value={value}>{value}</option>}
      {states.map((s) => (
        <option key={s.code} value={s.code}>
          {s.code} · {s.name}
        </option>
      ))}
    </select>
  );
}
