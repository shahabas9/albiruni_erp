import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, type Quotation } from "../api/client";
import { fetchPublicDocument, type CompanyProfile, type CreditNote, type Invoice, type PublicDocument, type Receipt, type Statement } from "../api/sales";
import { CreditSheet, InvoiceSheet, QuotationSheet, ReceiptSheet, StatementSheet } from "./PrintDocument";

/** What a customer sees when they open a share link: the document, ready to print. No login. */
export function PublicDocumentPage() {
  const { token = "" } = useParams();
  const [doc, setDoc] = useState<PublicDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPublicDocument(token)
      .then((d) => {
        setDoc(d);
        document.title = `${d.company.legal_name || d.company.name}`;
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "This link couldn't be opened."));
  }, [token]);

  if (error) return <p className="print-error">{error}</p>;
  if (!doc) return <p className="print-error">Loading…</p>;
  const company = { payment_terms_days: 0, quotation_validity_days: 0, allow_negative_stock: false, ...doc.company } as CompanyProfile;
  return (
    <div className="print-shell">
      <div className="print-bar">
        <button className="primary-btn" onClick={() => window.print()}>
          Print / Save as PDF
        </button>
      </div>
      {doc.kind === "invoice" && <InvoiceSheet inv={doc.document as Invoice} />}
      {doc.kind === "credit_note" && <CreditSheet note={doc.document as CreditNote} />}
      {doc.kind === "receipt" && <ReceiptSheet receipt={doc.document as Receipt} company={company} />}
      {doc.kind === "quotation" && <QuotationSheet q={doc.document as Quotation} company={company} />}
      {doc.kind === "statement" && <StatementSheet data={doc.document as Statement} company={company} />}
    </div>
  );
}
