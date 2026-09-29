import { useEffect, useRef, useState } from "react";
import { useAskErp } from "./AskErpContext";
import { useAppData, nextQuoteId, type ActionLevel } from "../data/AppDataProvider";
import { useLanguage } from "../i18n/LanguageProvider";

type StepState = "" | "active" | "done";
interface StepItem {
  label: string;
  state: StepState;
}

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "ai-text"; html: string }
  | { id: string; role: "ai-steps"; steps: StepItem[] }
  | { id: string; role: "ai-preview"; quoteId: string; settled: boolean };

let msgCounter = 0;
const uid = () => `m${msgCounter++}`;

const FLOW_LABELS = [
  "Understand — parse customer, items, discount",
  "Resolve — match Rahman Traders, Product A/B",
  "Authorize — check quotation-create access",
  "Enrich — load price list, tax, live stock",
  "Validate — compute totals, check discount policy",
  "Preview — build confirmable draft",
];

export function AskErpPanel() {
  const { isOpen, close, registerRunner } = useAskErp();
  const { addQuote, addAuditEntry } = useAppData();
  const { t } = useLanguage();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && messages.length === 0) {
      setMessages([{ id: uid(), role: "ai-text", html: t("panel.intro") }]);
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

  function runQuery(text: string) {
    pushMessage({ id: uid(), role: "user", text });
    const lower = text.toLowerCase();

    if (lower.includes("quotation") || lower.includes("ക്വട്ടേഷൻ")) {
      runQuotationFlow();
    } else if (lower.includes("sales by branch") || lower.includes("this month") || lower.includes("വിൽപ്പന")) {
      setTimeout(() => {
        pushMessage({
          id: uid(),
          role: "ai-text",
          html:
            "<b>This month, Kozhikode branch</b><br>Net sales: <span class=\"mono\">₹28.6L</span> — up 12.4% vs previous month, excluding cancelled invoices." +
            '<div style="margin-top:8px;font-size:11.5px;color:var(--ink-dim)">Scope: Kozhikode HQ · Sep 2026 · refreshed 08:14</div>' +
            '<div class="audit-chip">✓ Logged as AI read event</div>',
        });
      }, 500);
    } else if (lower.includes("can't submit") || lower.includes("cant submit") || lower.includes("diagnose") || lower.includes("error")) {
      setTimeout(() => {
        pushMessage({
          id: uid(),
          role: "ai-text",
          html:
            "This PO can't be submitted: the supplier's active bank details are missing, required for payments above ₹5L.<br><br><b>Next step:</b> add the supplier's bank account, or route this PO under ₹5L to skip the check.",
        });
      }, 500);
    } else if (lower.includes("stock transfer") || lower.includes("teach")) {
      setTimeout(() => {
        pushMessage({
          id: uid(),
          role: "ai-steps",
          steps: [
            { label: "Open Inventory → Transfers → New", state: "done" },
            { label: "Choose source and destination warehouse", state: "done" },
            { label: "Scan or enter items and quantities", state: "active" },
            { label: "Confirm and post the transfer", state: "" },
          ],
        });
      }, 500);
    } else {
      setTimeout(() => {
        pushMessage({
          id: uid(),
          role: "ai-text",
          html: "I can help navigate, explain a number, or draft an action like a quotation or transfer. Try: “Create a quotation for Coastal Traders, 10 units of Product A.”",
        });
      }, 500);
    }
  }

  function runQuotationFlow() {
    const stepsId = uid();
    const initialSteps: StepItem[] = FLOW_LABELS.map((label) => ({ label, state: "" }));
    pushMessage({ id: stepsId, role: "ai-steps", steps: initialSteps });

    let i = 0;
    function tick() {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === stepsId && m.role === "ai-steps"
            ? {
                ...m,
                steps: FLOW_LABELS.map((label, idx) => ({
                  label,
                  state: idx < i ? "done" : idx === i ? "active" : "",
                })),
              }
            : m,
        ),
      );
      i++;
      if (i <= FLOW_LABELS.length) {
        setTimeout(tick, 420);
      } else {
        setTimeout(() => {
          const quoteId = nextQuoteId();
          pushMessage({ id: uid(), role: "ai-preview", quoteId, settled: false });
        }, 350);
      }
    }
    tick();
  }

  function confirmQuote(messageId: string, quoteId: string) {
    addQuote({
      id: quoteId,
      customer: "Rahman Traders",
      items: "2 lines",
      value: "₹32,204",
      status: "Pending approval",
      risk: "L3 Execute" as ActionLevel,
      updated: "Just now",
      isNew: true,
    });
    addAuditEntry({
      id: `AE-${Math.floor(88300 + Math.random() * 90)}`,
      time: "Just now",
      actor: "user_ahmed",
      intent: "sales.create_quotation",
      risk: "L2 Prepare",
      tool: "sales.create_quotation_draft.v1",
      result: `${quoteId} · Draft created, routed for approval`,
      context: "Sales / Quotation / new · discount exception",
      corr: `corr_${Math.random().toString(16).slice(2, 8)}`,
    });
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId && m.role === "ai-preview" ? { ...m, settled: true } : m)),
    );
  }

  function cancelPreview(messageId: string) {
    setMessages((prev) => prev.filter((m) => m.id !== messageId));
  }

  function handleSend() {
    const v = input.trim();
    if (!v) return;
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
            onClick={() =>
              runQuery("Create a quotation for Rahman Traders: 50 boxes Product A and 20 boxes Product B. Give 3% discount.")
            }
          >
            {t("panel.chip.create")}
          </button>
          <button onClick={() => runQuery("This month's sales by branch")}>{t("panel.chip.report")}</button>
          <button onClick={() => runQuery("Why can't I submit this PO?")}>{t("panel.chip.diagnose")}</button>
          <button onClick={() => runQuery("How do I make a stock transfer?")}>{t("panel.chip.learn")}</button>
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
          <button className="send-btn" onClick={handleSend} aria-label="Send">
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
  onConfirm: (messageId: string, quoteId: string) => void;
  onCancel: (messageId: string) => void;
}) {
  // Declared unconditionally (rules-of-hooks) even though only the
  // "ai-preview" branch below uses it.
  const [confirming, setConfirming] = useState(false);

  if (message.role === "user") {
    return <div className="msg user">{message.text}</div>;
  }
  if (message.role === "ai-text") {
    return (
      <div className="msg ai">
        <div className="bubble" dangerouslySetInnerHTML={{ __html: message.html }} />
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
  // ai-preview
  return (
    <div className="msg ai">
      <div className={`preview-card${message.settled ? " settled" : ""}`}>
        <div className="pc-title">{message.settled ? "✓ Draft submitted for approval" : "⚠ Confirm quotation draft"}</div>
        {!message.settled && (
          <>
            <PreviewLine k="Customer" v="Rahman Traders" />
            <PreviewLine k="Product A" v="50 boxes @ ₹420" />
            <PreviewLine k="Product B" v="20 boxes @ ₹610" />
            <PreviewLine k="Discount requested" v="3%" />
            <PreviewLine k="Subtotal" v="₹33,200" />
            <PreviewLine k="Total after discount" v="₹32,204" />
            <div className="preview-flag">
              Discount 3% exceeds your 2% auto-approve limit — this will route to your Sales Manager for approval.
            </div>
          </>
        )}
        {message.settled ? (
          <div className="audit-chip">✓ Recorded to AI audit trail · {message.quoteId}</div>
        ) : confirming ? (
          <span style={{ fontSize: 12, color: "var(--ink-dim)" }}>Submitting…</span>
        ) : (
          <div className="pc-actions">
            <button
              className="confirm"
              onClick={() => {
                setConfirming(true);
                setTimeout(() => onConfirm(message.id, message.quoteId), 600);
              }}
            >
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
