import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAppData } from "../data/AppDataProvider";
import { ApiError, type Quotation } from "../api/client";
import { orderFromQuotation, quotationAction, updateQuotation, type QuotationAction } from "../api/sales";
import { Drawer, ErrorNote } from "../crm/ui";
import { dateTime, dayDate, inr, quoteStatusClass, taxLabel } from "../lib/format";
import { DocTotals } from "../sales/DocTotals";
import { ReasonModal } from "../sales/ReasonModal";
import { SendModal } from "../sales/SendModal";

type QuoteStatus = Quotation["status"];

const FILTERS: { key: "all" | QuoteStatus; labelKey?: string; label?: string }[] = [
  { key: "all", labelKey: "sales.f.all" },
  { key: "Draft", labelKey: "sales.f.draft" },
  { key: "Pending approval", labelKey: "sales.f.pending" },
  { key: "Sent", labelKey: "sales.f.sent" },
  { key: "Accepted", label: "Accepted" },
  { key: "Rejected", label: "Rejected" },
];

/** The API doesn't (yet) return a per-record action level; approximate it
 * from status, same as the original prototype: a quote still needing sign-off
 * needs an L3 Execute to move forward, everything else only ever needed a
 * Prepare-level AI action to reach its current state. */
function riskFor(status: QuoteStatus): string {
  return status === "Pending approval" ? "L3 Execute" : "L2 Prepare";
}

function riskClass(risk: string) {
  if (risk.startsWith("L1")) return "l1";
  if (risk.startsWith("L2")) return "l2";
  return "l3";
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function Sales() {
  const { t } = useLanguage();
  const { open } = useAskErp();
  const { quotes, loading, quotesError: error, refresh, can } = useAppData();
  const navigate = useNavigate();
  const [openId, setOpenId] = useState<string | null>(null);
  const opened = quotes.find((q) => q.id === openId) ?? null;
  const [params, setParams] = useSearchParams();
  const fromUrl: "all" | QuoteStatus = params.get("status") === "pending" ? "Pending approval" : "all";
  const [filter, setFilterState] = useState<"all" | QuoteStatus>(fromUrl);
  // The sidebar's Approvals entry is /sales?status=pending — keep the filter and URL in step.
  useEffect(() => setFilterState(fromUrl), [fromUrl]);
  const setFilter = (next: "all" | QuoteStatus) => {
    setFilterState(next);
    setParams(next === "Pending approval" ? { status: "pending" } : {}, { replace: true });
  };

  const visible = filter === "all" ? quotes : quotes.filter((q) => q.status === filter);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">{t("sales.eyebrow")}</div>
        <h1 className="page-title">{t("sales.title")}</h1>
        <p className="page-sub">{t("sales.sub")}</p>
      </div>

      <div className="toolbar">
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f.key} className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
              {f.labelKey ? t(f.labelKey) : f.label} ({f.key === "all" ? quotes.length : quotes.filter((q) => q.status === f.key).length})
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost-btn" onClick={open}>
            ✦ <span>{t("sales.new")}</span>
          </button>
          {can("sales.quotation.create") && (
            <button className="primary-btn" onClick={() => navigate("/sales/quotations/new")}>
              + New quotation
            </button>
          )}
        </div>
      </div>

      {error && <p className="footnote" style={{ color: "var(--bad)" }}>{error}</p>}
      {!error && loading && quotes.length === 0 && <p className="footnote">Loading quotations…</p>}

      {!loading && !error && quotes.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No quotations yet — try "{t("sales.new")}" above.
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("sales.col.id")}</th>
                <th>{t("sales.col.customer")}</th>
                <th>{t("sales.col.items")}</th>
                <th>{t("sales.col.value")}</th>
                <th>{t("sales.col.status")}</th>
                <th>{t("sales.col.risk")}</th>
                <th>{t("sales.col.updated")}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((q) => (
                <tr key={q.id} className="clickable" onClick={() => setOpenId(q.id)}>
                  <td className="mono">
                    <button className="link-btn mono" style={{ padding: 0 }} onClick={() => setOpenId(q.id)}>
                      {q.number}
                    </button>
                  </td>
                  <td>{q.customer_name}</td>
                  <td>
                    {q.lines.length} line{q.lines.length === 1 ? "" : "s"}
                  </td>
                  <td className="mono">{inr(q.grand_total || q.total)}</td>
                  <td>
                    <span className={`badge ${quoteStatusClass(q.status)}`}>{q.status}</span>
                    {q.is_expired && <span className="badge status-rejected">Expired</span>}
                    {q.order_number && <small className="mono"> → {q.order_number}</small>}
                  </td>
                  <td>
                    <span className={`badge ${riskClass(riskFor(q.status))}`}>{riskFor(q.status)}</span>
                  </td>
                  <td>{formatDateTime(q.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="footnote">{t("sales.foot")}</p>
      {opened && <QuotationDrawer quotation={opened} onClose={() => setOpenId(null)} onChanged={() => void refresh()} />}
    </section>
  );
}

function QuotationDrawer({ quotation: q, onClose, onChanged }: { quotation: Quotation; onClose: () => void; onChanged: () => void }) {
  const { can } = useAppData();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [sending, setSending] = useState(false);
  const canAct = can("sales.quotation.create");

  async function run(action: QuotationAction) {
    setBusy(true);
    setError(null);
    try {
      await quotationAction(q.id, action);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't do that.");
    } finally {
      setBusy(false);
    }
  }

  async function makeOrder() {
    setBusy(true);
    setError(null);
    try {
      const order = await orderFromQuotation(q.id);
      onChanged();
      navigate(`/sales/orders/${order.id}`, { state: { warnings: order.warnings } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't make the order.");
      setBusy(false);
    }
  }

  async function extend() {
    setBusy(true);
    setError(null);
    try {
      const d = new Date();
      d.setDate(d.getDate() + 15);
      await updateQuotation(q.id, { valid_until: d.toISOString().slice(0, 10) });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't extend it.");
    } finally {
      setBusy(false);
    }
  }

  const button = (action: QuotationAction, label: string, primary = false) => (
    <button key={action} className={primary ? "primary-btn" : "ghost-btn"} disabled={busy} onClick={() => run(action)}>
      {label}
    </button>
  );

  return (
    <Drawer title={q.number} subtitle={`${q.customer_name} · ${dateTime(q.created_at)}`} onClose={onClose}>
      <p>
        <span className={`badge ${quoteStatusClass(q.status)}`}>{q.status}</span>
        {q.is_expired && <span className="badge status-rejected">Expired</span>}
        {q.status_note && <span className="card-note"> {q.status_note}</span>}
      </p>
      {q.valid_until && <p className="card-note">Valid until {dayDate(q.valid_until)}</p>}
      {q.notes && <p className="card-note">{q.notes}</p>}
      <ErrorNote message={error} />
      <div className="table-wrap">
        <table className="doc-lines">
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Qty</th>
              <th className="num">Rate</th>
              <th className="num">{taxLabel()}</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {q.lines.map((l, i) => (
              <tr key={i}>
                <td>{l.item_name}</td>
                <td className="num">{l.qty}</td>
                <td className="num">{inr(l.unit_price)}</td>
                <td className="num">{l.gst_rate ?? 0}%</td>
                <td className="num">{inr(l.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DocTotals doc={q} subtotal={q.subtotal} discountPct={q.discount_pct} />
      {q.order_id && (
        <p className="card-note">
          On order <Link to={`/sales/orders/${q.order_id}`}>{q.order_number}</Link>.
        </p>
      )}
      {canAct && (
        <div className="head-actions" style={{ marginTop: 16 }}>
          <a className="ghost-btn" href={`/print/quotation/${q.id}`} target="_blank" rel="noreferrer">
            Print / PDF
          </a>
          {q.customer_id && ["Draft", "Sent", "Accepted"].includes(q.status) && (
            <button className="ghost-btn" onClick={() => setSending(true)}>
              Send
            </button>
          )}
          {["Draft", "Pending approval"].includes(q.status) && !q.order_id && (
            <button className="ghost-btn" onClick={() => navigate(`/sales/quotations/${q.id}/edit`)}>
              Edit
            </button>
          )}
          {q.is_expired && q.status === "Sent" && (
            <button className="ghost-btn" disabled={busy} onClick={() => extend()}>
              Extend 15 days
            </button>
          )}
          {q.status === "Pending approval" && can("sales.quotation.approve") && button("approve", "Approve discount", true)}
          {q.status === "Draft" && button("send", "Mark as sent")}
          {(q.status === "Draft" || q.status === "Sent") && button("accept", "Customer accepted")}
          {q.status === "Rejected" && button("reopen", "Reopen")}
          {!q.order_id && ["Draft", "Sent", "Accepted"].includes(q.status) && can("sales.order.write") && (
            <button className="primary-btn" disabled={busy} onClick={makeOrder}>
              Create sales order
            </button>
          )}
          {["Draft", "Sent", "Pending approval"].includes(q.status) && (
            <button className="danger-btn" disabled={busy} onClick={() => setRejecting(true)}>
              Rejected
            </button>
          )}
        </div>
      )}
      {sending && q.customer_id && (
        <SendModal kind="quotation" id={q.id} customerId={q.customer_id} title={`quotation ${q.number}`} onClose={() => setSending(false)} />
      )}
      {rejecting && (
        <ReasonModal
          title={`Mark ${q.number} as rejected?`}
          label="Why did the customer say no?"
          action="Mark rejected"
          onClose={() => setRejecting(false)}
          onConfirm={async (reason) => {
            await quotationAction(q.id, "reject", reason);
            setRejecting(false);
            onChanged();
          }}
        />
      )}
    </Drawer>
  );
}
