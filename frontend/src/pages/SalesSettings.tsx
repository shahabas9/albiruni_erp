import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { fetchCompanyProfile, updateCompanyProfile, type CompanyProfile } from "../api/sales";
import { StateSelect } from "../components/StateSelect";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** The seller's details printed on every tax invoice, and sales defaults — per the company's country. */
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
  const saudi = draft.country === "SA";
  const missing = (
    saudi
      ? [
          !draft.legal_name && "legal name",
          !draft.vat_number && "VAT number",
          !draft.cr_number && "CR number",
          !(draft.street && draft.building_no && draft.district && draft.city && draft.postal_code) && "national address",
        ]
      : [!draft.legal_name && "legal name", !draft.gstin && "GSTIN", !(gstinState || draft.state_code) && "state", !draft.address && "address"]
  ).filter(Boolean);

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const { name: _name, regime: _regime, country_locked: _locked, currency: _currency, ...body } = draft;
      const next = await updateCompanyProfile({ ...body, gstin: body.gstin.trim(), state_code: gstinState || body.state_code });
      if (next.country !== profile?.country) {
        // Currency and tax screens follow the country everywhere — start afresh.
        window.location.reload();
        return;
      }
      setProfile(next);
      setDraft(next);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const text = (
    key: "legal_name" | "phone" | "email" | "name_ar" | "vat_number" | "cr_number" | "building_no" | "street" | "district" | "city" | "postal_code",
    label: string,
    placeholder = "",
  ) => (
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
        <h1 className="page-title">Company &amp; Tax</h1>
        <p className="page-sub">Printed on every tax invoice for {profile.name}. {saudi ? "VAT is charged at 15% (or zero-rated / exempt per item) and invoices carry ZATCA's QR code." : "The state decides CGST + SGST versus IGST."}</p>
      </div>

      {missing.length > 0 && (
        <div className="notice-banner">Tax invoices need your {missing.join(", ")}. Fill them in below.</div>
      )}

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Seller details</span>
        </div>
        <div className="field-grid">
          <label className="field">
            <span>Registered in</span>
            <select
              value={draft.country}
              disabled={!canEdit || profile.country_locked}
              onChange={(e) => {
                const country = e.target.value as "IN" | "SA";
                setDraft({ ...draft, country, fy_start_month: country === "SA" ? 1 : 4 });
                setSaved(false);
              }}
            >
              <option value="IN">India — GST, ₹</option>
              <option value="SA">Saudi Arabia — VAT, SAR</option>
            </select>
            {profile.country_locked && <small className="card-note">Fixed: the company already has sales documents. Another country means a new company.</small>}
          </label>
          <label className="field">
            <span>Financial year starts</span>
            <select
              value={draft.fy_start_month}
              disabled={!canEdit || profile.country_locked}
              onChange={(e) => set("fy_start_month", Number(e.target.value))}
            >
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          {text("legal_name", "Legal name", saudi ? "As on the Commercial Registration" : "As registered for GST")}
          {saudi ? (
            <>
              <label className="field">
                <span>Legal name in Arabic</span>
                <input dir="rtl" value={draft.name_ar} disabled={!canEdit} onChange={(e) => set("name_ar", e.target.value)} />
              </label>
              {text("vat_number", "VAT number", "15 digits, starts and ends with 3")}
              {text("cr_number", "CR number", "10 digits")}
              {text("building_no", "Building number", "4 digits")}
              {text("street", "Street")}
              {text("district", "District")}
              {text("city", "City")}
              {text("postal_code", "Postal code", "5 digits")}
            </>
          ) : (
            <>
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
            </>
          )}
          {text("phone", "Phone")}
          {text("email", "Email")}
          {area("address", saudi ? "Address (optional, printed as written)" : "Address")}
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

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Payment reminders</span>
        </div>
        <p className="card-note">
          Emailed to each customer's billing email with a link to the invoice, once per stage, while money is owed. Needs email (SMTP) set up on the
          server.
        </p>
        <div className="field-grid">
          <label className="field checkbox-field">
            <input type="checkbox" checked={draft.reminders_enabled} disabled={!canEdit} onChange={(e) => set("reminders_enabled", e.target.checked)} />
            <span>Send payment reminders</span>
          </label>
          <label className="field">
            <span>Days before the due date (0: none)</span>
            <input
              type="number"
              min={0}
              max={60}
              value={draft.reminder_before_days}
              disabled={!canEdit}
              onChange={(e) => set("reminder_before_days", Number(e.target.value))}
            />
          </label>
          <label className="field">
            <span>Days after the due date</span>
            <input value={draft.reminder_after_days} disabled={!canEdit} onChange={(e) => set("reminder_after_days", e.target.value)} placeholder="1, 7, 15, 30" />
          </label>
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
