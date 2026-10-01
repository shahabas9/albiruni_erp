import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { fetchCompanyProfile, updateCompanyProfile, type CompanyProfile } from "../api/sales";
import { StateSelect } from "../components/StateSelect";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";

/** The seller's details printed on every tax invoice, and sales defaults. */
export function SalesSettings() {
  const { can } = useAppData();
  const canEdit = can("sales.settings.write");
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [draft, setDraft] = useState<CompanyProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCompanyProfile()
      .then((p) => (setProfile(p), setDraft(p)))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the company profile."));
  }, []);

  if (!draft || !profile) {
    return (
      <section>
        <ErrorNote message={error} />
        {!error && <p className="card-note">Loading…</p>}
      </section>
    );
  }

  const set = <K extends keyof CompanyProfile>(key: K, value: CompanyProfile[K]) => {
    setDraft({ ...draft, [key]: value });
    setSaved(false);
  };
  const gstinState = draft.gstin.trim().length === 15 ? draft.gstin.trim().slice(0, 2) : "";
  const missing = [!draft.legal_name && "legal name", !draft.gstin && "GSTIN", !(gstinState || draft.state_code) && "state", !draft.address && "address"].filter(Boolean);

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const { name: _name, ...body } = draft;
      const next = await updateCompanyProfile({ ...body, gstin: body.gstin.trim(), state_code: gstinState || body.state_code });
      setProfile(next);
      setDraft(next);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const text = (key: "legal_name" | "phone" | "email", label: string, placeholder = "") => (
    <label className="field">
      <span>{label}</span>
      <input value={draft[key]} disabled={!canEdit} placeholder={placeholder} onChange={(e) => set(key, e.target.value)} />
    </label>
  );
  const area = (key: "address" | "bank_details" | "invoice_terms", label: string, rows = 3) => (
    <label className="field full">
      <span>{label}</span>
      <textarea rows={rows} value={draft[key]} disabled={!canEdit} onChange={(e) => set(key, e.target.value)} />
    </label>
  );

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Company &amp; GST</h1>
        <p className="page-sub">Printed on every tax invoice for {profile.name}. The state decides CGST + SGST versus IGST.</p>
      </div>

      {missing.length > 0 && (
        <div className="notice-banner">Tax invoices need your {missing.join(", ")}. Fill them in below.</div>
      )}

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Seller details</span>
        </div>
        <div className="field-grid">
          {text("legal_name", "Legal name", "As registered for GST")}
          <label className="field">
            <span>GSTIN</span>
            <input
              value={draft.gstin}
              disabled={!canEdit}
              maxLength={15}
              className="mono"
              onChange={(e) => set("gstin", e.target.value.toUpperCase())}
              placeholder="e.g. 32ABCDE1234F1Z9"
            />
          </label>
          <label className="field">
            <span>State</span>
            <StateSelect value={gstinState || draft.state_code} onChange={(v) => set("state_code", v)} disabled={!canEdit || Boolean(gstinState)} />
          </label>
          {text("phone", "Phone")}
          {text("email", "Email")}
          {area("address", "Address")}
        </div>
      </div>

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Invoice defaults</span>
        </div>
        <div className="field-grid">
          <label className="field">
            <span>Payment terms (days)</span>
            <input
              type="number"
              min={0}
              max={365}
              value={draft.payment_terms_days}
              disabled={!canEdit}
              onChange={(e) => set("payment_terms_days", Number(e.target.value))}
            />
          </label>
          <label className="field">
            <span>Quotations valid for (days)</span>
            <input
              type="number"
              min={0}
              max={365}
              value={draft.quotation_validity_days}
              disabled={!canEdit}
              onChange={(e) => set("quotation_validity_days", Number(e.target.value))}
            />
          </label>
          <label className="field checkbox-field">
            <input
              type="checkbox"
              checked={draft.allow_negative_stock}
              disabled={!canEdit}
              onChange={(e) => set("allow_negative_stock", e.target.checked)}
            />
            <span>Allow deliveries to take stock below zero</span>
          </label>
          {area("bank_details", "Bank details (for payment)")}
          {area("invoice_terms", "Terms printed on invoices", 4)}
        </div>
      </div>

      <ErrorNote message={error} />
      {canEdit ? (
        <div className="form-actions">
          <button className="primary-btn" disabled={saving} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
          {saved && <span className="card-note">Saved.</span>}
        </div>
      ) : (
        <p className="card-note">Changing these needs the sales.settings.write permission.</p>
      )}
    </section>
  );
}
