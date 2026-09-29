import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  ATTACHMENT_MAX_MB,
  deleteAttachment,
  downloadAttachment,
  fetchAttachments,
  uploadAttachment,
  type Attachment,
  type RecordType,
} from "../api/client";
import { Icon } from "../components/Icon";
import { dateTime } from "../lib/format";
import { ErrorNote } from "./ui";

function size(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

/** Files on a lead, deal or customer: list, download, upload and remove. */
export function Attachments({
  recordType,
  recordId,
  canWrite,
  onChange,
}: {
  recordType: RecordType;
  recordId: string;
  canWrite: boolean;
  /** After an upload or delete (e.g. to refresh the record's history). */
  onChange?: () => void;
}) {
  const [files, setFiles] = useState<Attachment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setFiles(await fetchAttachments(recordType, recordId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the files.");
    }
  }

  useEffect(() => {
    setFiles(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordType, recordId]);

  async function upload(list: FileList | null) {
    if (!list?.length) return;
    setError(null);
    const problems: string[] = [];
    for (const file of Array.from(list)) {
      if (file.size > ATTACHMENT_MAX_MB * 1024 * 1024) {
        problems.push(`${file.name} is over ${ATTACHMENT_MAX_MB} MB.`);
        continue;
      }
      setBusy(`Uploading ${file.name}…`);
      try {
        await uploadAttachment(recordType, recordId, file);
      } catch (err) {
        problems.push(`${file.name}: ${err instanceof ApiError ? err.message : "upload failed."}`);
      }
    }
    setBusy(null);
    if (input.current) input.current.value = "";
    if (problems.length) setError(problems.join(" "));
    await load();
    onChange?.();
  }

  async function remove(a: Attachment) {
    if (!window.confirm(`Remove ${a.filename}? This can't be undone.`)) return;
    setError(null);
    try {
      await deleteAttachment(a.id);
      await load();
      onChange?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the file.");
    }
  }

  async function download(a: Attachment) {
    setError(null);
    try {
      await downloadAttachment(a);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't download the file.");
    }
  }

  return (
    <div
      className="attachments"
      onDragOver={(e) => canWrite && e.preventDefault()}
      onDrop={(e) => {
        if (!canWrite) return;
        e.preventDefault();
        void upload(e.dataTransfer.files);
      }}
    >
      {files === null && !error && <p className="card-note">Loading files…</p>}
      {files && files.length === 0 && (
        <p className="card-note" style={{ margin: 0 }}>
          No files yet{canWrite ? " — attach quotes, drawings, GST certificates or photos." : "."}
        </p>
      )}
      {files && files.length > 0 && (
        <div className="mini-list">
          {files.map((a) => (
            <div className="row" key={a.id}>
              <Icon name="file" size={18} />
              <div className="grow">
                <button className="link-btn file-name" onClick={() => download(a)} title="Download">
                  {a.filename}
                </button>
                <small>
                  {size(a.size_bytes)} · {a.uploaded_by_name ?? "Someone"} · {dateTime(a.created_at)}
                </small>
              </div>
              {canWrite && (
                <button className="ghost-btn sm" onClick={() => remove(a)} aria-label={`Remove ${a.filename}`}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <ErrorNote message={error} />
      {canWrite && (
        <div className="attach-actions">
          <input ref={input} type="file" multiple hidden onChange={(e) => upload(e.target.files)} aria-label="Choose files" />
          <button className="ghost-btn sm" disabled={Boolean(busy)} onClick={() => input.current?.click()}>
            <Icon name="plus" size={14} /> {busy ?? "Attach files"}
          </button>
          <small className="card-note">Up to {ATTACHMENT_MAX_MB} MB each · or drop files here</small>
        </div>
      )}
    </div>
  );
}
