/** Sales documents: company GST profile, orders, deliveries, invoices, payments. */
import { request, requestPage, type Page, type Quotation, type TaxTotals, type TimelineEntry } from "./client";

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

// --- Quotations ----------------------------------------------------------------

export type QuotationAction = "approve" | "send" | "accept" | "reject" | "reopen";

export function fetchQuotation(id: string): Promise<Quotation> {
  return request<Quotation>(`/api/sales/quotations/${id}`);
}

export function quotationAction(id: string, action: QuotationAction, note = ""): Promise<Quotation> {
  return request<Quotation>(`/api/sales/quotations/${id}/${action}`, { method: "POST", body: JSON.stringify({ note }) });
}

// --- Orders ----------------------------------------------------------------------

export interface DocLine {
  id: string;
  item_id: string;
  description: string;
  hsn_code: string;
  uom: string;
  qty: number;
  unit_price: number;
  list_price: number;
  gst_rate: number;
  amount: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  delivered_qty: number;
  invoiced_qty: number;
}

export type OrderStatus = "Draft" | "Confirmed" | "Partly delivered" | "Delivered" | "Cancelled";
export const ORDER_STATUSES: OrderStatus[] = ["Draft", "Confirmed", "Partly delivered", "Delivered", "Cancelled"];

export interface SalesOrder extends TaxTotals {
  id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  customer_gstin: string;
  quotation_id: string | null;
  quotation_number: string | null;
  opportunity_id: string | null;
  order_date: string;
  customer_po: string;
  status: OrderStatus;
  invoice_status: "Not invoiced" | "Partly invoiced" | "Invoiced";
  place_of_supply: string;
  billing_address: string;
  shipping_address: string;
  notes: string;
  subtotal: number;
  discount_pct: number;
  /** A discount over the limit or a price below list, not yet approved. */
  needs_approval: boolean;
  approved_by_name: string | null;
  cancel_reason: string;
  created_by_name: string | null;
  created_at: string;
  confirmed_at: string | null;
  lines: DocLine[];
  /** Create/update responses only: low stock and the like. */
  warnings: string[];
}

export interface DocLineInput {
  item_id: string;
  qty: number;
  /** Omit for the item's list price. */
  unit_price?: number;
}

export interface OrderInput {
  customer_id: string;
  lines: DocLineInput[];
  discount_pct: number;
  customer_po: string;
  notes: string;
  order_date?: string;
}

export interface OrderQuery {
  /** One status, or "open" (confirmed and not cancelled). */
  status?: string;
  customer_id?: string;
  q?: string;
  to_invoice?: boolean;
  limit?: number;
  offset?: number;
}

export function fetchOrders(params: OrderQuery = {}): Promise<Page<SalesOrder>> {
  return requestPage<SalesOrder>("/api/sales/orders", { ...params });
}

export function fetchOrder(id: string): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/orders/${id}`);
}

export function fetchOrderTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/sales/orders/${id}/timeline`);
}

export function createOrder(body: OrderInput): Promise<SalesOrder> {
  return request<SalesOrder>("/api/sales/orders", { method: "POST", body: JSON.stringify(body) });
}

export function orderFromQuotation(quotationId: string): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/quotations/${quotationId}/order`, { method: "POST" });
}

export function updateOrder(id: string, body: Partial<Omit<OrderInput, "customer_id">>): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/orders/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteOrder(id: string): Promise<void> {
  return request<void>(`/api/sales/orders/${id}`, { method: "DELETE" });
}

export function confirmOrder(id: string): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/orders/${id}/confirm`, { method: "POST" });
}

export function cancelOrder(id: string, reason: string): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/orders/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) });
}

