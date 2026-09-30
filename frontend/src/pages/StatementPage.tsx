import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { fetchStatement, type Statement } from "../api/sales";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, inr, todayIso } from "../lib/format";
import { PaymentModal } from "../sales/PaymentModal";

function fyStart(): string {
  const d = new Date();
  const year = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${year}-04-01`;
}

const LINK = { Invoice: "/sales/invoices/", Payment: null, "Credit note": null } as const;

export function StatementPage() {
  const { customerId = "" } = useParams();
  const { can } = useAppData();
  const [from, setFrom] = useState(fyStart());
  const [to, setTo] = useState(todayIso());
  const [data, setData] = useState<Statement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [changes, setChanges] = useState(0);

  useEffect(() => {
    let live = true;
    fetchStatement(customerId, from, to)
      .then((d) => live && (setData(d), setError(null)))
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load the statement."));
    return () => {
      live = false;
    };
  }, [customerId, from, to, changes]);

  return (
    <section>
      <Link to="/sales/receivables" className="back-link">
        ← Receivables
      </Link>
      <div className="page-head">
        <div>
          <div className="eyebrow">Account statement</div>
          <h1 className="page-title">{data?.customer_name ?? "…"}</h1>
          {data && (
            <p className="page-sub">
              <Link to={`/customers/${customerId}`}>Customer page</Link>
              {data.gstin && <> · GSTIN <span className="mono">{data.gstin}</span></>}
            </p>
          )}
        </div>
        <div className="head-actions">
          <label className="inline-date">
            From
            <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="inline-date">
            To
            <input type="date" value={to} min={from} max={todayIso()} onChange={(e) => setTo(e.target.value)} />
          </label>
          <a className="ghost-btn" href={`/print/statement/${customerId}?from=${from}&to=${to}`} target="_blank" rel="noreferrer">
            Print / PDF
          </a>
          {can("sales.payment.write") && data && (
            <button className="primary-btn" onClick={() => setPaying(true)}>
              Record payment
            </button>
          )}
        </div>
      </div>
      <ErrorNote message={error} />
      {data && (
        <div className="card">
          <StatementTable data={data} />
        </div>
      )}
      {paying && data && (
        <PaymentModal
          customer={{ id: customerId, name: data.customer_name }}
          onClose={() => setPaying(false)}
          onDone={() => {
            setPaying(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
    </section>
  );
}

/** Shared by the page and the printed statement. */
export function StatementTable({ data, links = true }: { data: Statement; links?: boolean }) {
  const balance = (n: number) => (n < 0 ? `${inr(-n)} Cr` : inr(n));
  return (
    <div className="table-wrap">
      <table className="doc-lines statement">
        <thead>
          <tr>
            <th>Date</th>
            <th>Document</th>
            <th>Details</th>
            <th className="num">Debit</th>
            <th className="num">Credit</th>
            <th className="num">Balance</th>
          </tr>
        </thead>
        <tbody>
          <tr className="muted-row">
            <td>{dayDate(data.date_from)}</td>
            <td colSpan={4}>Balance brought forward</td>
            <td className="num">{balance(data.opening_balance)}</td>
          </tr>
          {data.lines.map((l) => (
            <tr key={`${l.kind}-${l.id}`}>
              <td>{dayDate(l.date)}</td>
              <td>
                {l.kind}{" "}
                {links && LINK[l.kind] ? (
                  <Link className="mono" to={`${LINK[l.kind]}${l.id}`}>
                    {l.number}
                  </Link>
                ) : (
                  <span className="mono">{l.number}</span>
                )}
              </td>
              <td>{l.details}</td>
              <td className="num">{l.debit ? inr(l.debit) : ""}</td>
              <td className="num">{l.credit ? inr(l.credit) : ""}</td>
              <td className="num">{balance(l.balance)}</td>
            </tr>
          ))}
          <tr className="total-row">
            <td colSpan={3}>Closing balance {dayDate(data.date_to)}</td>
            <td className="num">{inr(data.total_debit)}</td>
            <td className="num">{inr(data.total_credit)}</td>
            <td className="num">{balance(data.closing_balance)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
