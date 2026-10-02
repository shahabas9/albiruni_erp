import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { fetchEinvoice, fetchEwayBill, recordGstRefs, saveJson, type Invoice, type PortalJson } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";

/** e-Invoice and e-way bill JSON for the government portals, and the numbers they give back. */
export function GstPortalModal({
  invoice,
  canWrite,
  onClose,
  onSaved,
}: {
  invoice: Invoice;
  canWrite: boolean;
  onClose: () => void;
  onSaved: (invoice: Invoice) => void;
}) {
  const [einvoice, setEinvoice] = useState<PortalJson | null>(null);
  const [eway, setEway] = useState<PortalJson | null>(null);
  const [distance, setDistance] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [transporterId, setTransporterId] = useState("");
  const [irn, setIrn] = useState(invoice.irn);
  const [ackNo, setAckNo] = useState(invoice.irn_ack_no);
  const [ackDate, setAckDate] = useState(invoice.irn_ack_date ?? "");
  const [ewbNo, setEwbNo] = useState(invoice.eway_bill_no);
  const [ewbDate, setEwbDate] = useState(invoice.eway_bill_date ?? "");
  const [busy, setBusy] = useState(false);
  const saudi = Boolean(invoice.invoice_kind);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEinvoice("invoices", invoice.id)
      .then(setEinvoice)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't build the e-invoice."));
  }, [invoice.id]);

  async function buildEway() {
    setError(null);
    try {
      setEway(await fetchEwayBill(invoice.id, { distance_km: Number(distance) || 0, vehicle_no: vehicle, transporter_id: transporterId }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't build the e-way bill.");
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(
        await recordGstRefs(invoice.id, {
          irn,
          irn_ack_no: ackNo,
          eway_bill_no: ewbNo,
          ...(ackDate ? { irn_ack_date: ackDate } : {}),
          ...(ewbDate ? { eway_bill_date: ewbDate } : {}),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={saudi ? `ZATCA e-invoice · ${invoice.number}` : `GST portals · ${invoice.number}`}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Close
          </button>
          {canWrite && !saudi && (
            <button className="primary-btn" disabled={busy} onClick={save}>
              {busy ? "Saving…" : "Save numbers"}
            </button>
          )}
        </>
      }
    >
      <ErrorNote message={error} />
      <h3 className="card-title">e-Invoice</h3>
      <p className="card-note">
        {saudi
          ? `A ${invoice.invoice_kind} tax invoice in ZATCA's UBL XML format, with its QR code. Standard (B2B) invoices are cleared by ZATCA before they reach the buyer; simplified (B2C) ones are reported within 24 hours.`
          : "Download the JSON and upload it on the e-invoice portal (or through your GST Suvidha Provider), then record the IRN it gives back."}
      </p>
      <Problems file={einvoice} />
      {einvoice?.notes?.map((n) => (
        <p key={n} className="card-note">
          {n}
        </p>
      ))}
      <div className="head-actions" style={{ margin: "8px 0 16px" }}>
        <button className="ghost-btn" disabled={!einvoice} onClick={() => einvoice && saveJson(einvoice)}>
          {saudi ? "Download ZATCA XML" : "Download e-invoice JSON"}
        </button>
      </div>
      {!saudi && (
        <>

      <h3 className="card-title">e-Way bill</h3>
      <div className="fields">
        <label className="field">
          Distance (km)
          <input type="number" min={1} max={4000} value={distance} onChange={(e) => setDistance(e.target.value)} />
        </label>
        <label className="field">
          Vehicle no.
          <input value={vehicle} placeholder="From the delivery note" onChange={(e) => setVehicle(e.target.value.toUpperCase())} />
        </label>
        <label className="field">
          Transporter GSTIN / ID (optional)
          <input value={transporterId} maxLength={15} onChange={(e) => setTransporterId(e.target.value.toUpperCase())} />
        </label>
      </div>
      <Problems file={eway} />
      <div className="head-actions" style={{ margin: "8px 0 16px" }}>
        <button className="ghost-btn" onClick={buildEway}>
          Check
        </button>
        <button className="ghost-btn" disabled={!eway} onClick={() => eway && saveJson(eway)}>
          Download e-way bill JSON
        </button>
      </div>

      <h3 className="card-title">Numbers from the portals</h3>
      <div className="fields">
        <label className="field full">
          IRN
          <input value={irn} maxLength={64} disabled={!canWrite} className="mono" onChange={(e) => setIrn(e.target.value.trim())} />
        </label>
        <label className="field">
          Ack no.
          <input value={ackNo} maxLength={20} disabled={!canWrite} onChange={(e) => setAckNo(e.target.value)} />
        </label>
        <label className="field">
          Ack date
          <input type="date" value={ackDate} disabled={!canWrite} onChange={(e) => setAckDate(e.target.value)} />
        </label>
        <label className="field">
          e-Way bill no.
          <input value={ewbNo} maxLength={14} disabled={!canWrite} onChange={(e) => setEwbNo(e.target.value)} />
        </label>
        <label className="field">
          e-Way bill date
          <input type="date" value={ewbDate} disabled={!canWrite} onChange={(e) => setEwbDate(e.target.value)} />
        </label>
      </div>
        </>
      )}
    </Modal>
  );
}

function Problems({ file }: { file: PortalJson | null }) {
  if (!file) return null;
  if (file.problems.length === 0) return <p className="card-note">Ready to upload.</p>;
  return (
    <ul className="notice-banner" style={{ margin: "8px 0", paddingLeft: 28 }}>
      {file.problems.map((p) => (
        <li key={p}>{p}</li>
      ))}
    </ul>
  );
}
