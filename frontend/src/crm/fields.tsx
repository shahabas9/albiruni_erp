import { useEffect, useId, useState } from "react";
import {
  fetchCustomFields,
  fetchTags,
  type CustomField,
  type CustomValue,
  type CustomValues,
  type RecordType,
} from "../api/client";

/** The company's active custom fields for a record type (empty while loading or on error). */
export function useCustomFields(recordType: RecordType): CustomField[] {
  const [fields, setFields] = useState<CustomField[]>([]);
  useEffect(() => {
    let current = true;
    fetchCustomFields(recordType)
      .then((rows) => current && setFields(rows))
      .catch(() => current && setFields([]));
    return () => {
      current = false;
    };
  }, [recordType]);
  return fields;
}

/** Tags in use on a record type, for suggestions and filters. */
export function useTags(recordType: RecordType, version = 0): { tag: string; count: number }[] {
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([]);
  useEffect(() => {
    let current = true;
    fetchTags(recordType)
      .then((rows) => current && setTags(rows))
      .catch(() => current && setTags([]));
    return () => {
      current = false;
    };
  }, [recordType, version]);
  return tags;
}

export function TagChips({ tags, onClick }: { tags: string[]; onClick?: (tag: string) => void }) {
  if (!tags.length) return null;
  return (
    <span className="tag-chips">
      {tags.map((t) =>
        onClick ? (
          <button key={t} type="button" className="tag-chip" onClick={() => onClick(t)} title={`Show only “${t}”`}>
            {t}
          </button>
        ) : (
          <span key={t} className="tag-chip">
            {t}
          </span>
        ),
      )}
    </span>
  );
}

/** Chips plus a text box: Enter or comma adds a tag, Backspace on an empty box removes the last. */
export function TagInput({
  value,
  onChange,
  recordType,
}: {
  value: string[];
  onChange: (tags: string[]) => void;
  recordType: RecordType;
}) {
  const [text, setText] = useState("");
  const suggestions = useTags(recordType);
  const listId = useId();

  function add(raw: string) {
    const tag = raw.replace(/\s+/g, " ").trim().toLowerCase().slice(0, 40);
    if (tag && !value.includes(tag) && value.length < 20) onChange([...value, tag]);
    setText("");
  }

  return (
    <div className="tag-input">
      {value.map((t) => (
        <span key={t} className="tag-chip">
          {t}
          <button type="button" aria-label={`Remove tag ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}>
            ×
          </button>
        </span>
      ))}
      <input
        value={text}
        list={listId}
        placeholder={value.length ? "" : "Add tags…"}
        aria-label="Add a tag"
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) v.split(",").forEach((part, i, all) => (i < all.length - 1 ? add(part) : setText(part)));
          else setText(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(text);
          } else if (e.key === "Backspace" && !text && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => text && add(text)}
      />
      <datalist id={listId}>
        {suggestions
          .filter((s) => !value.includes(s.tag))
          .map((s) => (
            <option key={s.tag} value={s.tag} />
          ))}
      </datalist>
    </div>
  );
}

/** A tag dropdown for list filters. */
export function TagFilter({
  recordType,
  value,
  onChange,
  version,
}: {
  recordType: RecordType;
  value: string;
  onChange: (tag: string) => void;
  version?: number;
}) {
  const tags = useTags(recordType, version);
  if (!tags.length && !value) return null;
  return (
    <select className="filter-select" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Tag filter">
      <option value="">All tags</option>
      {value && !tags.some((t) => t.tag === value) && <option value={value}>{value}</option>}
      {tags.map((t) => (
        <option key={t.tag} value={t.tag}>
          {t.tag} ({t.count})
        </option>
      ))}
    </select>
  );
}

/** Inputs for the given custom fields; `values` holds what's entered so far. */
export function CustomFieldInputs({
  fields,
  values,
  onChange,
}: {
  fields: CustomField[];
  values: CustomValues;
  onChange: (values: CustomValues) => void;
}) {
  const set = (key: string, v: CustomValue) => onChange({ ...values, [key]: v });
  return (
    <>
      {fields.map((f) => {
        const v = values[f.key];
        if (f.field_type === "checkbox") {
          return (
            <label key={f.id} className="field check-field">
              <input type="checkbox" checked={v === true} onChange={(e) => set(f.key, e.target.checked)} />
              <span>{f.label}</span>
            </label>
          );
        }
        return (
          <label key={f.id} className="field">
            <span>{f.label}</span>
            {f.field_type === "select" ? (
              <select value={typeof v === "string" ? v : ""} onChange={(e) => set(f.key, e.target.value || null)}>
                <option value="">—</option>
                {typeof v === "string" && v && !f.options.includes(v) && <option value={v}>{v}</option>}
                {f.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={f.field_type === "number" ? "number" : f.field_type === "date" ? "date" : "text"}
                value={v === null || v === undefined ? "" : String(v)}
                onChange={(e) => set(f.key, e.target.value === "" ? null : e.target.value)}
              />
            )}
          </label>
        );
      })}
    </>
  );
}

export function formatCustomValue(field: CustomField | undefined, value: CustomValue): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (field?.field_type === "number" && typeof value === "number") return value.toLocaleString("en-IN");
  if (field?.field_type === "date" && typeof value === "string") {
    const d = new Date(`${value}T00:00:00`);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  }
  return String(value);
}

/** Read-only "Label: value" pairs for the fields that have a value. */
export function CustomFieldValues({ fields, values }: { fields: CustomField[]; values: CustomValues }) {
  const shown = fields.filter((f) => values[f.key] !== undefined && values[f.key] !== null && values[f.key] !== "");
  if (!shown.length) return null;
  return (
    <dl className="custom-values">
      {shown.map((f) => (
        <div key={f.id}>
          <dt>{f.label}</dt>
          <dd>{formatCustomValue(f, values[f.key]!)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Only the values that differ from `before` — what an update should send. */
export function changedCustom(before: CustomValues, after: CustomValues): CustomValues {
  const out: CustomValues = {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const a = before[key] ?? null;
    const b = after[key] ?? null;
    if (String(a) !== String(b)) out[key] = b;
  }
  return out;
}
