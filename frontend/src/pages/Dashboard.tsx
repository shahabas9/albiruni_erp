import type { ReactNode } from "react";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import { useAppData } from "../data/AppDataProvider";
import { useNavigate } from "react-router-dom";

function formatInr(amount: number): string {
  if (amount >= 100_000) return `₹${(amount / 100_000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export function Dashboard() {
  const { t } = useLanguage();
  const { ask } = useAskErp();
  const { user } = useAuth();
  const { quotes, loading } = useAppData();
  const navigate = useNavigate();

  const totalValue = quotes.reduce((sum, q) => sum + q.total, 0);
  const draftCount = quotes.filter((q) => q.status === "Draft").length;
  const pendingCount = quotes.filter((q) => q.status === "Pending approval").length;
  const sentCount = quotes.filter((q) => q.status === "Sent").length;

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">{t("dash.eyebrow")}</div>
        <h1 className="page-title">
          {t("dash.title")}
          {user ? `, ${user.display_name}` : ""}
        </h1>
        <p className="page-sub">Live from your Sales data — nothing else is wired up yet, so that's all this shows.</p>
      </div>

      <div className="grid brief">
        <div className="card headline-card">
          <div>
            <div className="hl-label">Quotation pipeline — all statuses</div>
            <div className="hl-num mono">{loading ? "…" : quotes.length === 0 ? "No quotations yet" : formatInr(totalValue)}</div>
            {quotes.length > 0 && (
              <div className="hl-sub">
                {quotes.length} quotation{quotes.length === 1 ? "" : "s"} recorded
              </div>
            )}
          </div>
        </div>

        <BriefCard title={t("dash.trading")} onExplain={() => ask("Explain this month's sales trend")} t={t}>
          <MetricRow label="Pipeline value" value={loading ? "…" : formatInr(totalValue)} />
          <MetricRow label={t("sales.status.draft")} value={String(draftCount)} />
          <MetricRow label={t("sales.status.pending")} value={String(pendingCount)} warn={pendingCount > 0} />
          <MetricRow label={t("sales.status.sent")} value={String(sentCount)} />
        </BriefCard>

        <div className="card brief-card">
          <h3>
            <span>{t("dash.decisions")}</span>
          </h3>
          <MetricRow label={t("dash.pending")} value={loading ? "…" : String(pendingCount)} warn={pendingCount > 0} />
          <button className="explain-link" onClick={() => navigate("/audit")}>
            → <span>{t("dash.viewapprovals")}</span>
          </button>
        </div>

        <div className="card brief-card" style={{ gridColumn: "1 / -1" }}>
          <h3>
            <span>Not connected yet</span>
          </h3>
          <p style={{ fontSize: 13, color: "var(--ink-dim)", margin: "4px 0 0" }}>
            Cash, working capital, operations and people all need their own backend modules (Finance, Inventory,
            Logistics, HR) — none exist yet, so this dashboard doesn't show invented numbers for them. Only Sales
            (quotations) and the AI audit trail are wired to real data right now.
          </p>
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

function MetricRow({ label, value, warn, bad }: { label: string; value: string; warn?: boolean; bad?: boolean }) {
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className="metric-value mono" style={warn ? { color: "var(--warn)" } : bad ? { color: "var(--bad)" } : undefined}>
        {value}
      </span>
    </div>
  );
}
