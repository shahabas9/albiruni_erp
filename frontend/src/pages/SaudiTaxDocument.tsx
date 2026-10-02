import type { CreditNote, Invoice } from "../api/sales";
import { dayDate, plainMoney } from "../lib/format";

const CATEGORY = { S: "Standard 15%", Z: "Zero rated", E: "Exempt", O: "Out of scope" } as Record<string, string>;

/** Who's selling and buying, as printed. */
interface Parties {
  seller_name: string;
  seller_name_ar: string;
  seller_address: string;
  seller_vat_number: string;
  seller_cr_number: string;
  buyer_name: string;
  buyer_name_ar: string;
  billing_address: string;
  buyer_vat_number: string;
}

interface Line {
  key: string;
  description: string;
  qty: number;
  uom: string;
  price: number | null;
  discount_pct: number;
  taxable: number;
  rate: number;
  category: string;
  vat: number;
}

/** English label with its Arabic beside it, as ZATCA invoices are printed. */
function Bi({ en, ar }: { en: string; ar: string }) {
  return (
    <span className="bi">
      <span>{en}</span>
      <span className="ar" dir="rtl" lang="ar">
        {ar}
      </span>
    </span>
  );
}

function SaudiDocument({
  titleEn,
  titleAr,
  number,
  date,
  reference,
  dueDate,
  inv,
  lines,
  taxable,
  vat,
  total,
  words,
  qr,
  draft,
  reason,
}: {
  titleEn: string;
  titleAr: string;
  number: string;
  date: string;
  reference?: string;
  dueDate?: string;
  inv: Parties;
  lines: Line[];
  taxable: number;
  vat: number;
  total: number;
  words: string;
  qr: string;
  draft?: boolean;
  reason?: string;
}) {
  return (
    <article className="print-doc saudi-doc">
      <header className="pd-head">
        <div>
          <h1>{inv.seller_name}</h1>
          {inv.seller_name_ar && (
            <h1 className="ar" dir="rtl" lang="ar">
              {inv.seller_name_ar}
            </h1>
          )}
          <p className="pre">{inv.seller_address}</p>
          <p>
            <Bi en="VAT number" ar="الرقم الضريبي" /> <b className="mono">{inv.seller_vat_number}</b>
          </p>
          {inv.seller_cr_number && (
            <p>
              <Bi en="CR number" ar="السجل التجاري" /> <b className="mono">{inv.seller_cr_number}</b>
            </p>
          )}
        </div>
        <div className="pd-title">
          <h2>{draft ? "DRAFT — NOT A TAX INVOICE" : titleEn}</h2>
          {!draft && (
            <h2 className="ar" dir="rtl" lang="ar">
              {titleAr}
            </h2>
          )}
          {qr && <img className="zatca-qr" src={qr} alt="ZATCA QR code" />}
        </div>
      </header>

      <section className="pd-meta">
        <div>
          <h3>
            <Bi en="Buyer" ar="المشتري" />
          </h3>
          <p>
            <b>{inv.buyer_name}</b>
          </p>
          {inv.buyer_name_ar && (
            <p dir="rtl" lang="ar">
              <b>{inv.buyer_name_ar}</b>
            </p>
          )}
          <p className="pre">{inv.billing_address}</p>
          {inv.buyer_vat_number && (
            <p>
              <Bi en="VAT number" ar="الرقم الضريبي" /> <b className="mono">{inv.buyer_vat_number}</b>
            </p>
          )}
        </div>
        <dl>
          <dt>
            <Bi en="Number" ar="الرقم" />
          </dt>
          <dd className="mono">{number}</dd>
          <dt>
            <Bi en="Issue date" ar="تاريخ الإصدار" />
          </dt>
          <dd>{dayDate(date)}</dd>
          {dueDate && (
            <>
              <dt>
                <Bi en="Due date" ar="تاريخ الاستحقاق" />
              </dt>
              <dd>{dayDate(dueDate)}</dd>
            </>
          )}
          {reference && (
            <>
              <dt>
                <Bi en="Against invoice" ar="الفاتورة الأصلية" />
              </dt>
              <dd className="mono">{reference}</dd>
            </>
          )}
        </dl>
      </section>
      {reason && (
        <p>
          <Bi en="Reason" ar="السبب" />: {reason}
        </p>
      )}

      <table className="pd-lines">
        <thead>
          <tr>
            <th>#</th>
            <th>
              <Bi en="Description" ar="الوصف" />
            </th>
            <th className="num">
              <Bi en="Qty" ar="الكمية" />
            </th>
            <th className="num">
              <Bi en="Unit price" ar="سعر الوحدة" />
            </th>
            <th className="num">
              <Bi en="Taxable amount" ar="المبلغ الخاضع للضريبة" />
            </th>
            <th className="num">
              <Bi en="VAT" ar="الضريبة" />
            </th>
            <th className="num">
              <Bi en="Total" ar="المجموع" />
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={l.key}>
              <td>{i + 1}</td>
              <td>
                {l.description}
                {l.category && l.category !== "S" && <div className="print-sub">{CATEGORY[l.category] ?? l.category}</div>}
              </td>
              <td className="num">{l.qty ? `${l.qty} ${l.uom}` : "—"}</td>
              <td className="num">
                {l.price === null ? "—" : plainMoney(l.price)}
                {l.discount_pct ? <div className="print-sub">less {l.discount_pct}%</div> : null}
              </td>
              <td className="num">{plainMoney(l.taxable)}</td>
              <td className="num">
                {plainMoney(l.vat)}
                <small>{l.rate}%</small>
              </td>
              <td className="num">{plainMoney(l.taxable + l.vat)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="pd-sum">
        <div>
          <p>
            <b>Amount in words:</b> {words}
          </p>
        </div>
        <dl>
          <dt>
            <Bi en="Total excluding VAT" ar="الإجمالي غير شامل الضريبة" />
          </dt>
          <dd>{plainMoney(taxable)}</dd>
          <dt>
            <Bi en="VAT" ar="ضريبة القيمة المضافة" />
          </dt>
          <dd>{plainMoney(vat)}</dd>
          <dt className="grand">
            <Bi en="Total including VAT" ar="الإجمالي شامل الضريبة" />
          </dt>
          <dd className="grand">SAR {plainMoney(total)}</dd>
        </dl>
      </section>
    </article>
  );
}

/** A Saudi tax invoice: standard (B2B) or simplified (B2C), in English and Arabic, with ZATCA's QR code. */
export function SaudiInvoiceSheet({ inv }: { inv: Invoice }) {
  const simplified = inv.invoice_kind === "simplified";
  return (
    <>
      <SaudiDocument
        titleEn={simplified ? "SIMPLIFIED TAX INVOICE" : "TAX INVOICE"}
        titleAr={simplified ? "فاتورة ضريبية مبسطة" : "فاتورة ضريبية"}
        number={inv.number ?? "—"}
        date={inv.invoice_date}
        dueDate={inv.due_date}
        inv={inv}
        draft={inv.status === "Draft"}
        lines={inv.lines.map((l) => ({
          key: l.id,
          description: l.description,
          qty: l.qty,
          uom: l.uom,
          price: l.unit_price,
          discount_pct: l.discount_pct,
          taxable: l.taxable_value,
          rate: l.gst_rate,
          category: l.tax_category,
          vat: l.vat,
        }))}
        taxable={inv.total}
        vat={inv.vat}
        total={inv.grand_total}
        words={inv.amount_in_words}
        qr={inv.zatca_qr}
      />
      {(inv.bank_details || inv.terms) && (
        <footer className="pd-foot print-doc">
          {inv.bank_details && <p className="pre">{inv.bank_details}</p>}
          {inv.terms && <p className="pre">{inv.terms}</p>}
        </footer>
      )}
    </>
  );
}

/** A Saudi credit note (إشعار دائن) against an invoice, with its own QR code. */
export function SaudiCreditSheet({ note }: { note: CreditNote }) {
  return (
    <SaudiDocument
      titleEn="CREDIT NOTE"
      titleAr="إشعار دائن"
      number={note.number}
      date={note.note_date}
      reference={note.invoice_number}
      inv={{ ...note, buyer_name: note.customer_name }}
      reason={note.reason}
      lines={note.lines.map((l) => ({
        key: l.invoice_line_id,
        description: l.description,
        qty: l.qty,
        uom: l.uom,
        price: null,
        discount_pct: 0,
        taxable: l.taxable_value,
        rate: l.gst_rate,
        category: l.tax_category ?? "",
        vat: l.vat,
      }))}
      taxable={note.total}
      vat={note.vat}
      total={note.grand_total}
      words={note.amount_in_words}
      qr={note.zatca_qr}
    />
  );
}
