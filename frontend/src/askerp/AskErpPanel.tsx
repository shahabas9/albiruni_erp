import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useAskErp } from "./AskErpContext";
import { useAppData } from "../data/AppDataProvider";
import { useAuth } from "../auth/AuthProvider";
import { useLanguage } from "../i18n/LanguageProvider";
import { ApiError, askErp, confirmAsk, type AskResponse } from "../api/client";
import { BrandMark, Icon, type IconName } from "../components/Icon";
import { useSpeech } from "../lib/useSpeech";
import type { Lang } from "../i18n/strings";

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

const SUGGESTIONS: { key: string; icon: IconName; prompt: string }[] = [
  {
    key: "panel.chip.create",
    icon: "file",
    prompt: "Create a quotation for Rahman Traders: 50 boxes Product A and 20 boxes Product B. Give 3% discount.",
  },
  { key: "panel.chip.report", icon: "chart", prompt: "This month's sales by branch" },
  { key: "panel.chip.learn", icon: "chat", prompt: "How do I make a stock transfer?" },
];

export function AskErpPanel() {
  const { isOpen, open, close, registerRunner } = useAskErp();
  const { refresh } = useAppData();
  const { logout } = useAuth();
  const { t, lang, setLang } = useLanguage();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  const speech = useSpeech(lang === "ml" ? "ml-IN" : "en-IN", (text) => {
    if (!busyRef.current) runQuery(text);
  });

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

  if (!isOpen) {
    return (
      <button className="copilot-fab" onClick={open} aria-label="Open Ask ERP">
        <span className="dot-mic">
          <Icon name="mic" size={18} />
        </span>
        {t("panel.title")}
      </button>
    );
  }

  const live = speech.listening;
  const compact = messages.length > 1;

  return (
    <>
      <div className="copilot-scrim" onClick={close} />
      <aside className="copilot" aria-label="Ask ERP copilot">
        <div className="copilot-head">
          <div>
            <div className="copilot-title">
              <Icon name="chat" size={24} /> {t("panel.title")} <span className="live" aria-label="online" />
            </div>
            <p className="copilot-sub">Your business copilot</p>
          </div>
          <div className="copilot-head-actions">
            <select
              className="lang"
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
              aria-label="Conversation language"
            >
              <option value="en">English</option>
              <option value="ml">Malayalam + English</option>
            </select>
            <button className="icon-btn" onClick={close} aria-label="Close Ask ERP">
              <Icon name="x" />
            </button>
          </div>
        </div>

        <div className={`voice-hero${compact ? " compact" : ""}`}>
          <div className="orb-wrap">
            <Wave live={live} />
            <button
              className={`orb${live ? " live" : ""}`}
              onClick={speech.toggle}
              disabled={!speech.supported || busy}
              aria-label={live ? "Stop listening" : "Start voice conversation"}
            >
              <Icon name="mic" size={compact ? 26 : 52} />
            </button>
            <Wave live={live} />
          </div>
          <div className="voice-label">{live ? speech.interim || "Listening…" : "Voice conversation"}</div>
        </div>

        <div className="thread" ref={threadRef}>
          {messages.map((m, idx) => (
            <MessageView
              key={m.id}
              message={m}
              onConfirm={confirmQuote}
              onCancel={cancelPreview}
              suggestions={
                idx === 0 ? (
                  <div className="suggestions">
                    {SUGGESTIONS.map((sug) => (
                      <button key={sug.key} disabled={busy} onClick={() => runQuery(sug.prompt)}>
                        <Icon name={sug.icon} size={16} /> {t(sug.key)}
                      </button>
                    ))}
                  </div>
                ) : null
              }
            />
          ))}
          {live && speech.interim && <div className="msg user">{speech.interim}…</div>}
        </div>

        <div className="speak">
          <button
            className={`speak-btn${live ? " live" : ""}`}
            onClick={speech.toggle}
            disabled={!speech.supported || busy}
            aria-label={live ? "Stop listening" : "Tap to speak"}
          >
            <Icon name="mic" size={30} />
          </button>
          <small>{live ? "Listening — tap to stop" : "Tap to speak"}</small>
          {!speech.supported && <span className="hint">Voice needs Chrome, Edge or Safari — typing works everywhere.</span>}
          {speech.error && <span className="hint">{speech.error}</span>}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
        >
          <Icon name="keyboard" />
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
            aria-label="Type your question"
          />
          <button type="submit" className="icon-btn send" disabled={busy || !input.trim()} aria-label="Send">
            <Icon name="send" />
          </button>
        </form>
      </aside>
    </>
  );
}

const WAVE = [10, 22, 14, 34, 18, 44, 26, 52, 30, 40, 20, 46, 24, 36, 16, 28, 12];

function Wave({ live }: { live: boolean }) {
  return (
    <div className={`wave${live ? " live" : ""}`} aria-hidden="true">
      {WAVE.map((h, i) => (
        <i key={i} style={{ "--h": `${h}px`, "--d": `${(i % 6) * 0.12}s` } as CSSProperties} />
      ))}
    </div>
  );
}

function MessageView({
  message,
  onConfirm,
  onCancel,
  suggestions,
}: {
  message: Message;
  onConfirm: (messageId: string, previewToken: string) => void;
  onCancel: (messageId: string) => void;
  suggestions: ReactNode;
}) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <span>{message.text}</span>
        <Icon name="user" size={18} className="who" />
      </div>
    );
  }
  const body = (() => {
    if (message.role === "ai-text") {
      return <div className="bubble">{message.text}</div>;
    }
    if (message.role === "ai-steps") {
      return (
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
      );
    }
    const { preview, settled, confirming, confirmedNumber } = message;
    return (
      <div className={`preview-card${settled ? " settled" : ""}`}>
        <div className="pc-title">{settled ? "✓ Draft submitted" : "Confirm quotation draft"}</div>
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
          <span style={{ fontSize: 12.5, color: "var(--copilot-dim)" }}>Submitting…</span>
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
    );
  })();

  return (
    <div className="msg ai">
      <span className="bot">
        <BrandMark size={20} />
      </span>
      <div className="body">
        {body}
        {suggestions}
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
