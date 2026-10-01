import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCreditNotes, fetchEinvoice, saveJson } from "../api/sales";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, inr } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

export function CreditNotes() {
  const { version } = useAppData();
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const list = usePaged((limit, offset) => fetchCreditNotes({ q: search, limit, offset }), search, version);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Credit notes</h1>
        <p className="page-sub">Returns and price corrections against issued invoices. Make one from the invoice.</p>
      </div>
      <div className="toolbar">
        <div />
        <SearchBox value={search} onChange={onSearch} placeholder="CN no., customer or reason" />
      </div>
      {list.error && <div className="error-banner">{list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search ? "No credit notes match." : "No credit notes yet."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Credit note</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Invoice</th>
                <th>Kind</th>
                <th>Reason</th>
                <th className="num">Amount</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.rows.map((n) => (
                <tr key={n.id}>
                  <td className="mono">{n.number}</td>
                  <td>{dayDate(n.note_date)}</td>
                  <td>{n.customer_name}</td>
                  <td>
                    <Link className="link-btn mono" style={{ padding: 0 }} to={`/sales/invoices/${n.invoice_id}`}>
                      {n.invoice_number}
                    </Link>
                  </td>
                  <td>
                    {n.kind}
                    {n.restocked && <small> · restocked</small>}
                  </td>
                  <td>{n.reason}</td>
                  <td className="num">{inr(n.grand_total)}</td>
                  <td>
                    <a className="ghost-btn sm" href={`/print/credit-note/${n.id}`} target="_blank" rel="noreferrer">
                      Print
                    </a>{" "}
                    <button
                      className="ghost-btn sm"
                      title="e-Invoice JSON for the credit note"
                      onClick={async () => {
                        try {
                          const file = await fetchEinvoice("credit-notes", n.id);
                          if (file.problems.length && !window.confirm(`Fix before uploading:\n\n${file.problems.join("\n")}\n\nDownload anyway?`)) return;
                          saveJson(file);
                        } catch (err) {
                          window.alert(err instanceof Error ? err.message : "Couldn't build the e-invoice.");
                        }
                      }}
                    >
                      e-Invoice
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}
