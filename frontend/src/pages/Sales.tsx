import { useState } from "react";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAppData, type QuoteStatus } from "../data/AppDataProvider";

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

function riskClass(risk: string) {
  if (risk.startsWith("L1")) return "l1";
  if (risk.startsWith("L2")) return "l2";
  return "l3";
}

export function Sales() {
  const { t } = useLanguage();
  const { open } = useAskErp();
  const { quotes } = useAppData();
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
              <tr key={q.id} className={q.isNew ? "new-row" : undefined}>
                <td className="mono">{q.id}</td>
                <td>{q.customer}</td>
                <td>{q.items}</td>
                <td className="mono">{q.value}</td>
                <td>
                  <span className={`badge ${statusClass(q.status)}`}>{q.status}</span>
                </td>
                <td>
                  <span className={`badge ${riskClass(q.risk)}`}>{q.risk}</span>
                </td>
                <td>{q.updated}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="footnote">{t("sales.foot")}</p>
    </section>
  );
}
