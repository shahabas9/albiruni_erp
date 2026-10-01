import { useEffect, useState } from "react";
import { ApiError, fetchTargets, saveTargets, setTargetBasis, type TargetReport } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inrShort } from "../lib/format";

function monthKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(key: string, by: number) {
  const [y, m] = key.split("-").map(Number);
  return monthKey(new Date(y!, m! - 1 + by, 1));
}

function monthLabel(key: string) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y!, m! - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

/** Each person's monthly target against the deals they won, or the sales invoiced for them. */
export function Targets() {
  const { user } = useAuth();
  const { can, version } = useAppData();
  const canEdit = can("crm.settings.write");
  const [month, setMonth] = useState(() => monthKey(new Date()));
  const [report, setReport] = useState<TargetReport | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let current = true;
    setNotice(null);
    fetchTargets(month)
      .then((r) => {
        if (!current) return;
        setReport(r);
        setDrafts({});
        setError(null);
      })
      .catch((err) => current && setError(err instanceof ApiError ? err.message : "Couldn't load targets."));
    return () => {
      current = false;
    };
  }, [month, version]);

  const changed = Object.entries(drafts).filter(([id, v]) => {
    const row = report?.rows.find((r) => r.user_id === id);
    return row && Number(v || 0) !== row.target;
  });

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const saved = await saveTargets(
        month,
        changed.map(([user_id, v]) => ({ user_id, amount: Math.max(0, Number(v || 0)) })),
      );
      setReport(saved);
      setDrafts({});
      setNotice("Targets saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const isThisMonth = month === monthKey(new Date());

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Targets</h1>
        <p className="page-sub">
          What each person should sell in a month, measured on the deals they closed as Won or on the sales invoiced with them as
          salesperson (less credit notes). Forecast is their open deals expected to close this month, weighted by probability.
        </p>
      </div>

      <div className="toolbar">
        {report && (
          <div className="filters" aria-label="Measure targets on">
            {(["won", "invoiced"] as const).map((b) => (
              <button
                key={b}
                className={report.basis === b ? "on" : ""}
                disabled={!canEdit}
                title={canEdit ? "What targets are measured on, for everyone" : undefined}
                onClick={async () => {
                  if (b === report.basis) return;
                  try {
                    setReport(await setTargetBasis(b, month));
                    setNotice(`Targets are now measured on ${b === "won" ? "deals won" : "sales invoiced"}.`);
                  } catch (err) {
                    setError(err instanceof ApiError ? err.message : "Couldn't change it.");
                  }
                }}
              >
                {b === "won" ? "On deals won" : "On sales invoiced"}
              </button>
            ))}
          </div>
        )}
        <div className="month-switch">
          <button className="ghost-btn sm" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">
            ←
          </button>
          <b>{monthLabel(month)}</b>
          <button className="ghost-btn sm" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month">
            →
          </button>
          {!isThisMonth && (
            <button className="link-btn" onClick={() => setMonth(monthKey(new Date()))}>
              This month
            </button>
          )}
        </div>
      </div>

      <ErrorNote message={error} />
      {notice && <div className="notice good">{notice}</div>}

      {report && (
        <>
          <div className="card target-team">
            <div className="card-head">
              <span className="card-title">Team</span>
              <span className="card-note">
                {report.basis === "invoiced" ? `${inrShort(report.team_invoiced)} invoiced` : `${inrShort(report.team_won)} won`}
                {report.team_target > 0 ? ` of ${inrShort(report.team_target)}` : " · no targets set"}
              </span>
            </div>
            <Progress pct={report.team_pct} />
            {report.unowned_won_count > 0 && (
              <p className="card-note" style={{ marginBottom: 0 }}>
                Includes {inrShort(report.unowned_won_value)} from {report.unowned_won_count} won deal
                {report.unowned_won_count === 1 ? "" : "s"} with no owner.
              </p>
            )}
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Target</th>
                  <th>Won</th>
                  <th>Invoiced</th>
                  <th style={{ minWidth: 180 }}>Progress</th>
                  <th>Forecast</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={r.user_id} className={r.user_id === user?.id ? "me-row" : undefined}>
                    <td>
                      <b>{r.name}</b>
                      {!r.active && <span className="sub">Deactivated</span>}
                    </td>
                    <td>
                      {canEdit && r.active ? (
                        <input
                          className="target-input"
                          type="number"
                          min={0}
                          step={1000}
                          aria-label={`Target for ${r.name}`}
                          value={drafts[r.user_id] ?? (r.target ? String(r.target) : "")}
                          placeholder="No target"
                          onChange={(e) => {
                            setNotice(null);
                            setDrafts({ ...drafts, [r.user_id]: e.target.value });
                          }}
                        />
                      ) : (
                        <span className="num">{r.target ? inrShort(r.target) : "—"}</span>
                      )}
                    </td>
                    <td>
                      <span className="num">{inrShort(r.won_value)}</span>
                      <span className="sub">
                        {r.won_count} deal{r.won_count === 1 ? "" : "s"}
                      </span>
                    </td>
                    <td>
                      <span className="num">{inrShort(r.invoiced_value)}</span>
                      <span className="sub">
                        {r.invoiced_count} invoice{r.invoiced_count === 1 ? "" : "s"}
                      </span>
                    </td>
                    <td>
                      <Progress pct={r.pct} />
                    </td>
                    <td className="num">{r.forecast ? inrShort(r.forecast) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {canEdit && (
            <div className="form-actions">
              <button className="primary-btn" disabled={changed.length === 0 || saving} onClick={save}>
                {saving ? "Saving…" : `Save targets for ${monthLabel(month)}`}
              </button>
              {changed.length > 0 && (
                <button className="ghost-btn" onClick={() => setDrafts({})}>
                  Discard changes
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function Progress({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="card-note">No target</span>;
  const tone = pct >= 100 ? "good" : pct >= 60 ? "mid" : "low";
  return (
    <div className="target-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="track">
        <div className={`fill ${tone}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="num">{pct}%</span>
    </div>
  );
}
