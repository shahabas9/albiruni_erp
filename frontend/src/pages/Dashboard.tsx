import { useMemo, type ReactNode } from "react";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useNavigate } from "react-router-dom";

const SPARK_VALUES = [
  14, 18, 16, 22, 19, 25, 21, 27, 24, 29, 26, 31, 28, 34, 30, 36, 33, 38, 35, 41, 37, 44, 40, 46, 42, 49, 45, 52, 48, 55,
];

export function Dashboard() {
  const { t } = useLanguage();
  const { ask } = useAskErp();
  const navigate = useNavigate();
  const max = useMemo(() => Math.max(...SPARK_VALUES), []);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">{t("dash.eyebrow")}</div>
        <h1 className="page-title">{t("dash.title")}</h1>
        <p className="page-sub">{t("dash.sub")}</p>
      </div>

      <div className="grid brief">
        <div className="card headline-card">
          <div>
            <div className="hl-label">{t("dash.hl.label")}</div>
            <div className="hl-num mono">
              ₹28.6L <span style={{ fontSize: 16, fontWeight: 500, opacity: 0.85 }}>+12.4%</span>
            </div>
            <div className="hl-sub">{t("dash.hl.sub")}</div>
          </div>
          <div className="spark-bars">
            {SPARK_VALUES.map((v, i) => (
              <i
                key={i}
                className={i === SPARK_VALUES.length - 1 ? "now" : undefined}
                style={{ height: 10 + (v / max) * 34 }}
              />
            ))}
          </div>
        </div>

        <BriefCard title={t("dash.trading")} onExplain={() => ask("Explain this month's sales trend for Kozhikode branch")} t={t}>
          <MetricRow label={t("dash.sales")} value="₹28.6L" delta="+12.4%" up />
          <MetricRow label={t("dash.returns")} value="₹0.9L" delta="+6%" />
          <MetricRow label={t("dash.margin")} value="31.2%" />
          <MetricRow label={t("dash.orders")} value="47" />
        </BriefCard>

        <BriefCard title={t("dash.cash")} onExplain={() => ask("Why is cash tight on 3 October?")} t={t}>
          <MetricRow label={t("dash.receipts")} value="₹19.2L" />
          <MetricRow label={t("dash.payments")} value="₹14.8L" />
          <MetricRow label={t("dash.bank")} value="₹42.1L" />
          <MetricRow label={t("dash.forecast")} value="Tight on Oct 3" warn />
        </BriefCard>

        <BriefCard title={t("dash.wc")} onExplain={() => ask("Show overdue customers above 90 days")} t={t}>
          <MetricRow label={t("dash.arage")} value="₹6.4L" bad />
          <MetricRow label={t("dash.apage")} value="₹3.1L" />
          <MetricRow label={t("dash.invdays")} value="38" />
          <MetricRow label={t("dash.excess")} value="6 SKUs" />
        </BriefCard>

        <BriefCard title={t("dash.ops")} onExplain={() => ask("Which deliveries are at risk this week?")} t={t}>
          <MetricRow label={t("dash.deliveries")} value="12" />
          <MetricRow label={t("dash.shortages")} value="3 items" warn />
          <MetricRow label={t("dash.delays")} value="2" />
        </BriefCard>

        <div className="card brief-card">
          <h3>
            <span>{t("dash.decisions")}</span>
          </h3>
          <MetricRow label={t("dash.pending")} value="4" warn />
          <MetricRow label={t("dash.breach")} value="1" bad />
          <button className="explain-link" onClick={() => navigate("/audit")}>
            → <span>{t("dash.viewapprovals")}</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function BriefCard({
  title,
  onExplain,
  t,
  children,
}: {
  title: string;
  onExplain: () => void;
  t: (k: string) => string;
  children: ReactNode;
}) {
  return (
    <div className="card brief-card">
      <h3>
        <span>{title}</span>
      </h3>
      {children}
      <button className="explain-link" onClick={onExplain}>
        ✦ <span>{t("dash.explain")}</span>
      </button>
    </div>
  );
}

function MetricRow({
  label,
  value,
  delta,
  up,
  warn,
  bad,
}: {
  label: string;
  value: string;
  delta?: string;
  up?: boolean;
  warn?: boolean;
  bad?: boolean;
}) {
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className="metric-value mono" style={warn ? { color: "var(--warn)" } : bad ? { color: "var(--bad)" } : undefined}>
        {value} {delta && <span className={`delta ${up ? "up" : "down"}`}>{up ? "▲" : "▲"}{delta}</span>}
      </span>
    </div>
  );
}
