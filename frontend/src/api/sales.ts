/** Sales documents: company GST profile, orders, deliveries, invoices, payments. */
import { request } from "./client";

export const GST_RATES = [0, 0.25, 3, 5, 12, 18, 28, 40];

export interface GstState {
  code: string;
  name: string;
}

let statesCache: Promise<GstState[]> | null = null;

/** GST state codes; fetched once per session. */
export function fetchStates(): Promise<GstState[]> {
  statesCache ??= request<GstState[]>("/api/sales/states").catch((err) => {
    statesCache = null;
    throw err;
  });
  return statesCache;
}

export interface CompanyProfile {
  name: string;
  legal_name: string;
  gstin: string;
  state_code: string;
  address: string;
  phone: string;
  email: string;
  bank_details: string;
  invoice_terms: string;
  payment_terms_days: number;
  allow_negative_stock: boolean;
}

export function fetchCompanyProfile(): Promise<CompanyProfile> {
  return request<CompanyProfile>("/api/sales/company");
}

export function updateCompanyProfile(body: Partial<Omit<CompanyProfile, "name">>): Promise<CompanyProfile> {
  return request<CompanyProfile>("/api/sales/company", { method: "PUT", body: JSON.stringify(body) });
}
