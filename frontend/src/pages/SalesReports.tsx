import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { downloadReport, fetchGstr1, fetchSalesRegister, GSTR1_SECTIONS, type Gstr1, type SalesRegister } from "../api/sales";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, inr, inrShort } from "../lib/format";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** A month as yyyy-mm → its first and last day. */
function monthRange(month: string): [string, string] {
  const [y, m] = month.split("-").map(Number);
  return [iso(new Date(y!, m! - 1, 1)), iso(new Date(y!, m!, 0))];
}

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

export function SalesReports() {
  const { version } = useAppData();
  const [month, setMonth] = useState(lastMonth());
  const [custom, setCustom] = useState(false);
  const [from, setFrom] = useState(monthRange(lastMonth())[0]);
  const [to, setTo] = useState(monthRange(lastMonth())[1]);
  const [register, setRegister] = useState<SalesRegister | null>(null);
  const [gstr1, setGstr1] = useState<Gstr1 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [start, end] = custom ? [from, to] : monthRange(month);

  useEffect(() => {
    let live = true;
    Promise.all([fetchSalesRegister(start, end), fetchGstr1(start, end)])
      .then(([r, g]) => live && (setRegister(r), setGstr1(g), setError(null)))
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load the reports."));
    return () => {
      live = false;
    };
  }, [start, end, version]);

  async function download(kind: Parameters<typeof downloadReport>[0]) {
    setBusy(kind);
    setError(null);
    try {
      await downloadReport(kind, start, end);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't download.");
    } finally {
      setBusy(null);
    }
  }

  const t = register?.totals;
  return (
    <section>
      <div className="page-head">
        <div>
          <div className="eyebrow">Sales</div>
          <h1 className="page-title">Sales reports</h1>
          <p className="page-sub">The sales register and GSTR-1 figures for a period, as CSV files for your accountant. Check them before filing.</p>
        </div>
        <div className="head-actions">
          {custom ? (
            <>
              <label className="inline-date">
                From
                <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className="inline-date">
                To
                <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
              </label>
            </>
          ) : (
            <label className="inline-date">
              Month
              <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
            </label>
          )}
          <button className="ghost-btn sm" onClick={() => setCustom((v) => !v)}>
            {custom ? "Whole month" : "Custom dates"}
          </button>
        </div>
      </div>
      <ErrorNote message={error} />

      {t && register && (
        <div className="forecast-strip">
          <div className="card stat">
            <div className="stat-label">Taxable sales</div>
            <div className="stat-value num">{inrShort(t.taxable_value)}</div>
            <div className="stat-sub">
              {register.invoices} invoice{register.invoices === 1 ? "" : "s"}, {register.credit_notes} credit note{register.credit_notes === 1 ? "" : "s"}
            </div>
          </div>
          <div className="card stat">
            <div className="stat-label">GST charged</div>
            <div className="stat-value num">{inrShort(t.cgst + t.sgst + t.igst)}</div>
            <div className="stat-sub">
              IGST {inrShort(t.igst)} · CGST {inrShort(t.cgst)} · SGST {inrShort(t.sgst)}
            </div>
          </div>
          <div className="card stat">
            <div className="stat-label">Invoice value</div>
            <div className="stat-value num">{inrShort(t.total)}</div>
            <div className="stat-sub">
              {dayDate(start)} – {dayDate(end)}
            </div>
          </div>
        </div>
      )}

      {gstr1 && (
        <div className="card">
          <div className="card-head">
            <span className="card-title">GSTR-1</span>
            <span className="card-note">Section-wise CSVs in the GST portal's column order</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Section</th>
                  <th className="num">Rows</th>
                  <th className="num">Taxable value</th>
                  <th className="num">Tax</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {GSTR1_SECTIONS.map((s) => {
                  const row = gstr1.summary[s.key];
                  return (
                    <tr key={s.key}>
                      <td>
                        <b>{s.label}</b>
                        <small className="card-note"> {s.hint}</small>
                      </td>
                      <td className="num">{row.count}</td>
                      <td className="num">{s.key === "docs" ? "—" : inr(row.taxable_value)}</td>
                      <td className="num">{s.key === "docs" ? "—" : inr(row.tax)}</td>
                      <td>
                        <button className="ghost-btn sm" disabled={busy !== null || row.count === 0} onClick={() => download(s.key)}>
                          {busy === s.key ? "…" : "CSV"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {register && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-head">
            <span className="card-title">Sales register</span>
            <button className="ghost-btn sm" disabled={busy !== null || register.rows.length === 0} onClick={() => download("register")}>
              {busy === "register" ? "Downloading…" : "Download CSV"}
            </button>
          </div>
          {register.rows.length === 0 ? (
            <p className="card-note">No invoices or credit notes in this period.</p>
          ) : (
            <div className="table-wrap">
              <table className="doc-lines">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Document</th>
                    <th>Customer</th>
                    <th>GSTIN</th>
                    <th className="num">Taxable</th>
                    <th className="num">CGST</th>
                    <th className="num">SGST</th>
                    <th className="num">IGST</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {register.rows.slice(0, 200).map((r) => (
                    <tr key={`${r.type}-${r.id}`}>
                      <td>{dayDate(r.date)}</td>
                      <td>
                        {r.type === "Invoice" ? (
                          <Link className="mono" to={`/sales/invoices/${r.id}`}>
                            {r.number}
                          </Link>
                        ) : (
                          <span className="mono">{r.number}</span>
                        )}
                      </td>
                      <td>{r.customer}</td>
                      <td className="mono">{r.gstin || "—"}</td>
                      <td className="num">{inr(r.taxable_value)}</td>
                      <td className="num">{inr(r.cgst)}</td>
                      <td className="num">{inr(r.sgst)}</td>
                      <td className="num">{inr(r.igst)}</td>
                      <td className="num">{inr(r.total)}</td>
                    </tr>
                  ))}
                  <tr className="total-row">
                    <td colSpan={4}>Total{register.rows.length > 200 ? ` (first 200 of ${register.rows.length} shown; the CSV has all)` : ""}</td>
                    <td className="num">{inr(register.totals.taxable_value)}</td>
                    <td className="num">{inr(register.totals.cgst)}</td>
                    <td className="num">{inr(register.totals.sgst)}</td>
                    <td className="num">{inr(register.totals.igst)}</td>
                    <td className="num">{inr(register.totals.total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
