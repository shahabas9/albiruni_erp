import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import { Icon, type IconName } from "../components/Icon";
import { useAppData } from "../data/AppDataProvider";
import { inrShort } from "../lib/format";
import { fetchTargets, type OpportunityStage, type Quotation, type TargetRow } from "../api/client";

const OPEN_STAGES: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];

function monthKey(d: Date) {
  return `${d.getFullYear()}-${d.getMonth()}`;
}

/** Quotation value per calendar month for the last `n` months, oldest first. */
function monthlyQuoted(quotes: Quotation[], n: number, now = new Date()) {
  const totals = new Map<string, number>();
  for (const q of quotes) {
    const k = monthKey(new Date(q.created_at));
    totals.set(k, (totals.get(k) ?? 0) + q.total);
  }
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - (n - 1 - i), 1);
    return { label: d.toLocaleDateString("en-IN", { month: "short" }), value: totals.get(monthKey(d)) ?? 0 };
  });
}

function pctChange(now: number, before: number): number | null {
  if (before === 0) return null;
  return ((now - before) / before) * 100;
}

export function Overview() {
  const { user } = useAuth();
  const { ask } = useAskErp();
  const navigate = useNavigate();
  const { quotes, crm, loading, can, version } = useAppData();
  // Your own target this month, if one is set.
  const [myTarget, setMyTarget] = useState<TargetRow | null>(null);
  useEffect(() => {
    if (!can("crm.opportunity.read") || !user) return;
    let current = true;
    fetchTargets()
      .then((r) => current && setMyTarget(r.rows.find((row) => row.user_id === user.id && row.target > 0) ?? null))
      .catch(() => current && setMyTarget(null));
    return () => {
      current = false;
    };
  }, [can, user, version]);

  const series = monthlyQuoted(quotes, 6);
  const thisMonth = series[series.length - 1]!.value;
  const lastMonth = series[series.length - 2]!.value;
  const quotedDelta = pctChange(thisMonth, lastMonth);

  const won = crm?.won_deals ?? 0;
  const lost = crm?.lost_deals ?? 0;
  const winRate = won + lost > 0 ? Math.round((won / (won + lost)) * 100) : null;
  const pending = quotes.filter((q) => q.status === "Pending approval");
  const overdueCount = crm?.overdue_followups ?? 0;
  const unassigned = crm?.unassigned ?? 0;
  const staleCount = crm?.stale_deals ?? 0;

  const dash = loading && quotes.length === 0 ? "…" : null;

  return (
    <section>
      <div className="page-head">
        <div>
          <h1 className="page-title">Your business, at a glance.</h1>
          <p className="page-sub">Welcome back, {user?.display_name ?? "there"}.</p>
        </div>
        <span className="chip-btn" style={{ cursor: "default" }}>
          <Icon name="calendar" size={18} />
          {new Date().toLocaleDateString("en-IN", { month: "long", year: "numeric" })}
        </span>
      </div>

      <div className="kpi-grid">
        <Kpi icon="chart" label="Quoted this month" value={dash ?? inrShort(thisMonth)}>
          {quotedDelta === null ? (
            <span>No quotes last month to compare</span>
          ) : (
            <>
              <b className={quotedDelta >= 0 ? "up" : "down"}>
                <Icon name="trend" size={14} />
                {quotedDelta >= 0 ? "+" : ""}
                {quotedDelta.toFixed(1)}%
              </b>
              <span>vs. last month</span>
            </>
          )}
        </Kpi>
        <Kpi icon="target" label="Open pipeline" value={dash ?? inrShort(crm?.open_value ?? 0)}>
          <span>
            {crm?.open_deals ?? 0} open deal{crm?.open_deals === 1 ? "" : "s"} · weighted {inrShort(crm?.weighted_value ?? 0)}
          </span>
        </Kpi>
        <Kpi icon="wallet" label="Won deals" value={dash ?? inrShort(crm?.won_value ?? 0)}>
          <Icon name="clock" size={15} />
          <span>{winRate === null ? "No closed deals yet" : `${winRate}% win rate on closed deals`}</span>
        </Kpi>
        <Kpi icon="file" label="Pending approvals" value={dash ?? String(pending.length)}>
          <span>Quotations over the discount limit</span>
        </Kpi>
      </div>

      <div className="overview-row">
        <div className="card">
          <div className="card-head">
            <span className="card-title">Quotation value</span>
            <span className="card-note">₹ in Lakhs · last 6 months</span>
          </div>
          <AreaChart points={series} />
        </div>
        <div className="card">
          <div className="card-head">
            <span className="card-title">Pipeline by stage</span>
            <span className="card-note">₹ in Lakhs</span>
          </div>
          <StageBars
            rows={OPEN_STAGES.map((s) => ({
              label: s,
              value: crm?.by_stage.find((b) => b.stage === s)?.value ?? 0,
            }))}
          />
        </div>
      </div>

      <div className="overview-row even">
        <div className="card">
          <div className="card-head">
            <span className="card-title">Needs your attention</span>
            <button className="link-btn" onClick={() => navigate("/activities?show=overdue")}>
              View all
            </button>
          </div>
          <div className="attention-list">
            {myTarget && (
              <Attention
                tone={(myTarget.pct ?? 0) >= 100 ? "ok" : "warn"}
                icon="target"
                title={`Your target: ${myTarget.pct}% reached`}
                sub={`${inrShort(myTarget.won_value)} won of ${inrShort(myTarget.target)} this month · forecast ${inrShort(myTarget.forecast)}`}
                onView={() => navigate("/crm/targets")}
              />
            )}
            {overdueCount > 0 && (
              <Attention
                tone="bad"
                icon="alert"
                title={`${overdueCount} follow-up${overdueCount === 1 ? "" : "s"} overdue`}
                sub={(crm?.overdue_items ?? [])
                  .slice(0, 2)
                  .map((a) => a.related_label)
                  .join(", ")}
                onView={() => navigate("/activities?show=overdue")}
              />
            )}
            {pending.length > 0 && (
              <Attention
                tone="warn"
                icon="file"
                title={`${pending.length} quotation${pending.length === 1 ? "" : "s"} awaiting approval`}
                sub={`Total ${inrShort(pending.reduce((s, q) => s + q.total, 0))}`}
                onView={() => navigate("/sales?status=pending")}
              />
            )}
            {staleCount > 0 && (
              <Attention
                tone="warn"
                icon="clock"
                title={`${staleCount} deal${staleCount === 1 ? "" : "s"} going stale`}
                sub={`${inrShort(crm?.stale_value ?? 0)} with no recent activity`}
                onView={() => navigate("/opportunities?stale=1")}
              />
            )}
            {unassigned > 0 && (
              <Attention
                tone="warn"
                icon="user"
                title={`${unassigned} lead${unassigned === 1 ? "" : "s"} / deal${unassigned === 1 ? "" : "s"} without an owner`}
                sub="Nobody is accountable for these yet"
                onView={() => navigate("/leads?owner=unassigned")}
              />
            )}
            {overdueCount === 0 && pending.length === 0 && unassigned === 0 && staleCount === 0 && (
              <Attention tone="ok" icon="check" title="All clear" sub="No overdue follow-ups, approvals, stale or unowned deals." />
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title">Quick actions</span>
          </div>
          <div className="quick-grid">
            <QuickAction
              tone="qa-green"
              icon="mic"
              title="Create quotation"
              sub="Say or type it to Ask ERP"
              onClick={() => ask("Create a quotation for Rahman Traders: 50 boxes Product A and 20 boxes Product B. Give 3% discount.")}
            />
            {can("crm.lead.write") && (
              <QuickAction tone="qa-blue" icon="user" title="New lead" sub="Capture a prospect" onClick={() => navigate("/leads?new=1")} />
            )}
            {can("crm.opportunity.write") && (
              <QuickAction
                tone="qa-violet"
                icon="target"
                title="New opportunity"
                sub="Open a deal for a customer"
                onClick={() => navigate("/opportunities?new=1")}
              />
            )}
            <QuickAction tone="qa-green" icon="chart" title="View pipeline" sub="Deals by stage and owner" onClick={() => navigate("/crm")} />
          </div>
        </div>
      </div>

    </section>
  );
}

function Kpi({ icon, label, value, children }: { icon: IconName; label: string; value: string; children: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="kpi-icon">
        <Icon name={icon} size={24} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="kpi-label">{label}</div>
        <div className="kpi-value num">{value}</div>
        <div className="kpi-delta">{children}</div>
      </div>
    </div>
  );
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  const n = v / mag;
  return (n <= 1.2 ? 1.2 : n <= 2 ? 2 : n <= 3 ? 3 : n <= 4 ? 4 : n <= 6 ? 6 : n <= 8 ? 8 : 12) * mag;
}

function AreaChart({ points }: { points: { label: string; value: number }[] }) {
  const W = 600;
  const H = 240;
  const pad = { l: 44, r: 16, t: 14, b: 30 };
  const lakhs = points.map((p) => p.value / 100_000);
  const max = niceMax(Math.max(...lakhs));
  const x = (i: number) => pad.l + (i * (W - pad.l - pad.r)) / (points.length - 1);
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const line = lakhs.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const area = `${line} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const fmt = (v: number) => (v === 0 ? "0" : `${v % 1 === 0 ? v : v.toFixed(1)}L`);

  return (
    <svg className="area-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Quotation value by month">
      <defs>
        <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line className="grid-line" x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} />
          <text x={pad.l - 8} y={y(t) + 4} textAnchor="end">
            {fmt(t)}
          </text>
        </g>
      ))}
      <line className="axis-line" x1={pad.l} x2={pad.l} y1={pad.t} y2={y(0)} />
      <path d={area} fill="url(#areaFill)" />
      <path className="series" d={line} />
      {lakhs.map((v, i) => (
        <g key={i}>
          <circle className="dot" cx={x(i)} cy={y(v)} r={4.5}>
            <title>
              {points[i]!.label}: {inrShort(points[i]!.value)}
            </title>
          </circle>
          <text x={x(i)} y={H - 8} textAnchor="middle">
            {points[i]!.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function StageBars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <span className="label">{r.label}</span>
          <div className="track">
            <div className="fill" style={{ width: `${(r.value / max) * 100}%`, opacity: r.value ? 1 : 0 }} />
          </div>
          <span className="value num">{(r.value / 100_000).toFixed(1)}L</span>
        </div>
      ))}
    </div>
  );
}

function Attention({
  tone,
  icon,
  title,
  sub,
  onView,
}: {
  tone: "bad" | "warn" | "ok";
  icon: IconName;
  title: string;
  sub: string;
  onView?: () => void;
}) {
  return (
    <div className="attention-item">
      <div className={`ai-icon ${tone}`}>
        <Icon name={icon} size={20} />
      </div>
      <div className="txt">
        <b>{title}</b>
        <small>{sub}</small>
      </div>
      {onView && (
        <button className="link-btn" onClick={onView}>
          View <Icon name="right" size={14} />
        </button>
      )}
    </div>
  );
}

function QuickAction({
  tone,
  icon,
  title,
  sub,
  onClick,
}: {
  tone: string;
  icon: IconName;
  title: string;
  sub: string;
  onClick: () => void;
}) {
  return (
    <button className={`quick-action ${tone}`} onClick={onClick}>
      <span className="qa-icon">
        <Icon name={icon} size={22} />
      </span>
      <span className="qa-txt">
        <b>{title}</b>
        <small>{sub}</small>
      </span>
      <Icon name="right" size={16} />
    </button>
  );
}
