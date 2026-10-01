import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { fetchAgeing, type Ageing } from "../api/sales";
import { ErrorNote, SearchBox } from "../crm/ui";
import { SendModal } from "../sales/SendModal";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, inr, inrShort } from "../lib/format";

const BUCKETS = [
  { key: "not_due", label: "Not due" },
  { key: "d1_30", label: "1–30 days" },
  { key: "d31_60", label: "31–60" },
  { key: "d61_90", label: "61–90" },
  { key: "d90_plus", label: "90+" },
] as const;

export function Receivables() {
  const { version } = useAppData();
  const [data, setData] = useState<Ageing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const [reminding, setReminding] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    let live = true;
    fetchAgeing(search)
      .then((d) => live && (setData(d), setError(null)))
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load receivables."));
    return () => {
      live = false;
    };
  }, [search, version]);

  const t = data?.totals;
  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Receivables</h1>
        <p className="page-sub">Who owes what, and for how long. Days are counted from each invoice's due date; advances are money received and not yet applied.</p>
      </div>
      <ErrorNote message={error} />
      {t && (
        <div className="forecast-strip">
          <div className="card stat">
            <div className="stat-label">Owed to you</div>
            <div className="stat-value num">{inrShort(t.invoiced_owed)}</div>
            <div className="stat-sub">{data!.rows.filter((r) => r.invoiced_owed > 0).length} customers</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Overdue</div>
            <div className="stat-value num" style={{ color: t.overdue > 0 ? "var(--bad)" : undefined }}>
              {inrShort(t.overdue)}
            </div>
            <div className="stat-sub">{inrShort(t.d90_plus)} over 90 days</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Advances held</div>
            <div className="stat-value num">{inrShort(t.advance)}</div>
            <div className="stat-sub">To apply to later invoices</div>
          </div>
          <div className="card stat">
            <div className="stat-label">Net receivable</div>
            <div className="stat-value num">{inrShort(t.net)}</div>
            <div className="stat-sub">As of {dayDate(data!.as_of)}</div>
          </div>
        </div>
      )}
      <div className="toolbar">
        <div />
        <SearchBox value={search} onChange={onSearch} placeholder="Customer or GSTIN" />
      </div>
      {data && data.rows.length === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search ? "No customers match." : "Nobody owes anything right now."}
        </div>
      )}
      {data && data.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                {BUCKETS.map((b) => (
                  <th key={b.key} className="num">
                    {b.label}
                  </th>
                ))}
                <th className="num">Advance</th>
                <th className="num">Net owed</th>
                <th>Oldest due</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.customer_id}>
                  <td>
                    <Link className="link-btn" style={{ padding: 0 }} to={`/sales/receivables/${r.customer_id}`}>
                      {r.customer_name}
                    </Link>
                    {r.credit_limit > 0 && r.net > r.credit_limit && <small className="below-list">Over credit limit</small>}
                  </td>
                  {BUCKETS.map((b) => (
                    <td key={b.key} className={`num${b.key !== "not_due" && r[b.key] > 0 ? " qty-out" : ""}`}>
                      {r[b.key] ? inr(r[b.key]) : "—"}
                    </td>
                  ))}
                  <td className="num">{r.advance ? inr(r.advance) : "—"}</td>
                  <td className="num">
                    <b>{r.net < 0 ? `${inr(-r.net)} in credit` : inr(r.net)}</b>
                  </td>
                  <td>{r.oldest_due ? dayDate(r.oldest_due) : "—"}</td>
                  <td>
                    {r.net > 0 && (
                      <button className="ghost-btn sm" onClick={() => setReminding({ id: r.customer_id, name: r.customer_name })}>
                        Remind
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reminding && (
        <SendModal
          kind="statement"
          id={reminding.id}
          customerId={reminding.id}
          title={reminding.name}
          reminder
          onClose={() => setReminding(null)}
        />
      )}
    </section>
  );
}
