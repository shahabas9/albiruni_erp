import { useState } from "react";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAppData } from "../data/AppDataProvider";
import type { Quotation } from "../api/client";

type QuoteStatus = Quotation["status"];

const FILTERS: { key: "all" | QuoteStatus; labelKey: string }[] = [
  { key: "all", labelKey: "sales.f.all" },
  { key: "Draft", labelKey: "sales.f.draft" },
  { key: "Pending approval", labelKey: "sales.f.pending" },
  { key: "Sent", labelKey: "sales.f.sent" },
];

function statusClass(status: QuoteStatus) {
  if (status === "Sent") return "status-confirmed";
  if (status === "Pending approval") return "status-pending";
  return "status-draft";
}

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
  const { quotes, loading, error } = useAppData();
  const [filter, setFilter] = useState<"all" | QuoteStatus>("all");

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
              {t(f.labelKey)} ({f.key === "all" ? quotes.length : quotes.filter((q) => q.status === f.key).length})
            </button>
          ))}
        </div>
        <button className="primary-btn" onClick={open}>
          ✦ <span>{t("sales.new")}</span>
        </button>
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
                <tr key={q.id}>
                  <td className="mono">{q.number}</td>
                  <td>{q.customer_name}</td>
                  <td>
                    {q.lines.length} line{q.lines.length === 1 ? "" : "s"}
                  </td>
                  <td className="mono">₹{q.total.toLocaleString("en-IN")}</td>
                  <td>
                    <span className={`badge ${statusClass(q.status)}`}>{q.status}</span>
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
    </section>
  );
}
