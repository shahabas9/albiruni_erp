import { useEffect, useRef, useState } from "react";
import { useAskErp } from "./AskErpContext";
import { useAppData } from "../data/AppDataProvider";
import { useAuth } from "../auth/AuthProvider";
import { useLanguage } from "../i18n/LanguageProvider";
import { ApiError, askErp, confirmAsk, type AskResponse } from "../api/client";

type StepState = "" | "active" | "done";
interface StepItem {
  label: string;
  state: StepState;
}

type PreviewData = Extract<AskResponse, { type: "preview" }>;

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "ai-text"; text: string }
  | { id: string; role: "ai-steps"; steps: StepItem[] }
  | { id: string; role: "ai-preview"; preview: PreviewData; settled: boolean; confirming: boolean; confirmedNumber?: string };

let msgCounter = 0;
const uid = () => `m${msgCounter++}`;

const FLOW_LABELS = [
  "Understand — parse customer, items, discount",
  "Resolve — match customer and items",
  "Authorize — check quotation-create access",
  "Enrich — load price list, tax, live stock",
  "Validate — compute totals, check discount policy",
  "Preview — build confirmable draft",
];

export function AskErpPanel() {
  const { isOpen, close, registerRunner } = useAskErp();
  const { refresh } = useAppData();
  const { logout } = useAuth();
  const { t } = useLanguage();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && messages.length === 0) {
      setMessages([{ id: uid(), role: "ai-text", text: t("panel.intro") }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    registerRunner(runQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pushMessage(m: Message) {
    setMessages((prev) => [...prev, m]);
  }

  function playSteps(): Promise<void> {
    const stepsId = uid();
    pushMessage({ id: stepsId, role: "ai-steps", steps: FLOW_LABELS.map((label) => ({ label, state: "" })) });

    return new Promise((resolve) => {
      let i = 0;
      function tick() {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === stepsId && m.role === "ai-steps"
              ? {
                  ...m,
                  steps: FLOW_LABELS.map((label, idx) => ({
                    label,
                    state: idx < i ? "done" : idx === i ? "active" : ("" as StepState),
                  })),
                }
              : m,
          ),
        );
        i++;
        if (i <= FLOW_LABELS.length) {
          setTimeout(tick, 260);
        } else {
          resolve();
        }
      }
      tick();
    });
  }

  async function runQuery(text: string) {
    pushMessage({ id: uid(), role: "user", text });
    setBusy(true);
    try {
      const response = await askErp(text);
      if (response.type === "preview") {
        await playSteps();
        pushMessage({ id: uid(), role: "ai-preview", preview: response, settled: false, confirming: false });
      } else {
        pushMessage({ id: uid(), role: "ai-text", text: response.message });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        pushMessage({ id: uid(), role: "ai-text", text: "Your session expired — signing you out." });
        setTimeout(logout, 1200);
      } else {
        const detail = err instanceof ApiError ? err.message : "Could not reach the Albiruni API.";
        pushMessage({ id: uid(), role: "ai-text", text: `Something went wrong: ${detail}` });
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmQuote(messageId: string, previewToken: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId && m.role === "ai-preview" ? { ...m, confirming: true } : m)),
    );
    try {
      const result = await confirmAsk(previewToken);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId && m.role === "ai-preview"
            ? { ...m, settled: true, confirming: false, confirmedNumber: result.number }
            : m,
        ),
      );
      await refresh();
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId && m.role === "ai-preview" ? { ...m, confirming: false } : m)),
      );
      const detail = err instanceof ApiError ? err.message : "Could not reach the Albiruni API.";
      pushMessage({ id: uid(), role: "ai-text", text: `Couldn't confirm: ${detail}` });
    }
  }

  function cancelPreview(messageId: string) {
    setMessages((prev) => prev.filter((m) => m.id !== messageId));
  }

  function handleSend() {
    const v = input.trim();
    if (!v || busy) return;
    setInput("");
    runQuery(v);
  }

  return (
    <>
      <div className={`scrim${isOpen ? " open" : ""}`} onClick={close} />
      <aside className={`panel${isOpen ? " open" : ""}`}>
        <div className="panel-head">
          <div className="ph-title">
            <span className="mark">✦</span> <span>{t("panel.title")}</span>
          </div>
          <button className="icon-btn" onClick={close} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="mode-chips">
          <button
            disabled={busy}
            onClick={() =>
              runQuery("Create a quotation for Rahman Traders: 50 boxes Product A and 20 boxes Product B. Give 3% discount.")
            }
          >
            {t("panel.chip.create")}
          </button>
          <button disabled={busy} onClick={() => runQuery("This month's sales by branch")}>
            {t("panel.chip.report")}
          </button>
          <button disabled={busy} onClick={() => runQuery("Why can't I submit this PO?")}>
            {t("panel.chip.diagnose")}
          </button>
          <button disabled={busy} onClick={() => runQuery("How do I make a stock transfer?")}>
            {t("panel.chip.learn")}
          </button>
        </div>
        <div className="thread" ref={threadRef}>
          {messages.map((m) => (
            <MessageView key={m.id} message={m} onConfirm={confirmQuote} onCancel={cancelPreview} />
          ))}
        </div>
        <div className="panel-input">
          <textarea
            rows={1}
            placeholder={t("panel.placeholder")}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button className="send-btn" onClick={handleSend} disabled={busy} aria-label="Send">
            ➤
          </button>
        </div>
      </aside>
    </>
  );
}

function MessageView({
  message,
  onConfirm,
  onCancel,
}: {
  message: Message;
  onConfirm: (messageId: string, previewToken: string) => void;
  onCancel: (messageId: string) => void;
}) {
  if (message.role === "user") {
    return <div className="msg user">{message.text}</div>;
  }
  if (message.role === "ai-text") {
    return (
      <div className="msg ai">
        <div className="bubble">{message.text}</div>
      </div>
    );
  }
  if (message.role === "ai-steps") {
    return (
      <div className="msg ai">
        <div className="bubble">
          <div className="step-tracker">
            {message.steps.map((s, idx) => (
              <div key={idx} className={`step ${s.state}`}>
                <span className="n">{s.state === "done" ? "✓" : idx + 1}</span>
                {s.label}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const { preview, settled, confirming, confirmedNumber } = message;
  return (
    <div className="msg ai">
      <div className={`preview-card${settled ? " settled" : ""}`}>
        <div className="pc-title">{settled ? "✓ Draft submitted" : "⚠ Confirm quotation draft"}</div>
        {!settled && (
          <>
            <PreviewLine k="Customer" v={preview.customer} />
            {preview.lines.map((line, idx) => (
              <PreviewLine key={idx} k={line.item_name} v={`${line.qty} @ ₹${line.unit_price.toLocaleString("en-IN")}`} />
            ))}
            <PreviewLine k="Discount requested" v={`${preview.discount_pct}%`} />
            <PreviewLine k="Subtotal" v={`₹${preview.subtotal.toLocaleString("en-IN")}`} />
            <PreviewLine k="Total after discount" v={`₹${preview.total.toLocaleString("en-IN")}`} />
            {preview.warnings.map((w, idx) => (
              <div className="preview-flag" key={idx}>
                {w}
              </div>
            ))}
          </>
        )}
        {settled ? (
          <div className="audit-chip">✓ Recorded to AI audit trail · {confirmedNumber}</div>
        ) : confirming ? (
          <span style={{ fontSize: 12, color: "var(--ink-dim)" }}>Submitting…</span>
        ) : (
          <div className="pc-actions">
            <button className="confirm" onClick={() => onConfirm(message.id, preview.preview_token)}>
              Confirm &amp; submit
            </button>
            <button className="cancel" onClick={() => onCancel(message.id)}>
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function PreviewLine({ k, v }: { k: string; v: string }) {
  return (
    <div className="preview-line">
      <span>{k}</span>
      <span className="mono">{v}</span>
    </div>
  );
}
