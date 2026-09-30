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
  /** Only goods are delivered; services are just invoiced. */
  item_kind: "goods" | "service";
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


// --- Deliveries and stock ----------------------------------------------------------

export interface DeliveryNote {
  id: string;
  number: string;
  order_id: string;
  order_number: string;
  customer_id: string;
  customer_name: string;
  delivery_date: string;
  status: "Delivered" | "Cancelled";
  shipping_address: string;
  vehicle_no: string;
  transporter: string;
  notes: string;
  cancel_reason: string;
  created_at: string;
  lines: { order_line_id: string; item_id: string; description: string; uom: string; qty: number }[];
}

export interface DeliveryInput {
  lines: { order_line_id: string; qty: number }[];
  delivery_date?: string;
  vehicle_no: string;
  transporter: string;
  notes: string;
}

export function fetchDeliveries(params: { order_id?: string; q?: string; limit?: number; offset?: number } = {}): Promise<Page<DeliveryNote>> {
  return requestPage<DeliveryNote>("/api/sales/deliveries", { ...params });
}

export function fetchDelivery(id: string): Promise<DeliveryNote> {
  return request<DeliveryNote>(`/api/sales/deliveries/${id}`);
}

export function createDelivery(orderId: string, body: DeliveryInput): Promise<DeliveryNote> {
  return request<DeliveryNote>(`/api/sales/orders/${orderId}/deliveries`, { method: "POST", body: JSON.stringify(body) });
}

export function cancelDelivery(id: string, reason: string): Promise<DeliveryNote> {
  return request<DeliveryNote>(`/api/sales/deliveries/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) });
}

export interface StockMovement {
  id: string;
  kind: string;
  qty: number;
  balance_after: number;
  ref_type: string;
  ref_id: string | null;
  ref_number: string;
  note: string;
  created_by_name: string | null;
  created_at: string;
}

export function fetchStockLedger(itemId: string, limit = 50, offset = 0): Promise<Page<StockMovement>> {
  return requestPage<StockMovement>(`/api/items/${itemId}/stock`, { limit, offset });
}

export function adjustStock(itemId: string, countedQty: number, reason: string): Promise<void> {
  return request<void>(`/api/items/${itemId}/adjust`, { method: "POST", body: JSON.stringify({ counted_qty: countedQty, reason }) });
}

// --- Invoices ----------------------------------------------------------------------

export interface InvoiceLine {
  id: string;
  order_line_id: string;
  item_id: string;
  description: string;
  hsn_code: string;
  uom: string;
  qty: number;
  unit_price: number;
  gst_rate: number;
  amount: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  credited_qty: number;
  /** Taxable value already credited (returns and price corrections). */
  credited_value: number;
}

export interface HsnRow {
  hsn_code: string;
  gst_rate: number;
  qty: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
}

export type PaymentStatus = "Draft" | "Unpaid" | "Partly paid" | "Paid" | "Overdue" | "Credited";

export interface Invoice extends TaxTotals {
  id: string;
  /** null until issued. */
  number: string | null;
  status: "Draft" | "Issued";
  payment_status: PaymentStatus;
  order_id: string;
  order_number: string;
  customer_id: string;
  customer_name: string;
  invoice_date: string;
  due_date: string;
  place_of_supply: string;
  place_of_supply_name: string;
  seller_name: string;
  seller_gstin: string;
  seller_state: string;
  seller_state_name: string;
  seller_address: string;
  buyer_name: string;
  buyer_gstin: string;
  buyer_state: string;
  billing_address: string;
  shipping_address: string;
  customer_po: string;
  subtotal: number;
  discount_pct: number;
  amount_in_words: string;
  amount_paid: number;
  amount_credited: number;
  /** Still owed: total − paid − credited. */
  balance: number;
  notes: string;
  terms: string;
  bank_details: string;
  created_at: string;
  issued_at: string | null;
  issued_by_name: string | null;
  lines: InvoiceLine[];
  hsn_summary: HsnRow[];
  /** Single-invoice endpoint only: receipts applied to it. */
  payments: { receipt_id: string; number: string; receipt_date: string; mode: string; reference: string; amount: number }[];
}

export interface InvoiceQuery {
  /** Draft, Issued, unpaid, overdue or paid. */
  status?: string;
  customer_id?: string;
  order_id?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export function fetchInvoices(params: InvoiceQuery = {}): Promise<Page<Invoice>> {
  return requestPage<Invoice>("/api/sales/invoices", { ...params });
}

export function fetchInvoice(id: string): Promise<Invoice> {
  return request<Invoice>(`/api/sales/invoices/${id}`);
}

export function fetchInvoiceTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/sales/invoices/${id}/timeline`);
}

/** lines omitted: what's delivered and not invoiced (services: everything not invoiced). */
export function createInvoiceDraft(orderId: string, lines?: { order_line_id: string; qty: number }[]): Promise<Invoice> {
  return request<Invoice>(`/api/sales/orders/${orderId}/invoices`, { method: "POST", body: JSON.stringify({ lines: lines ?? null }) });
}

export function deleteInvoice(id: string): Promise<void> {
  return request<void>(`/api/sales/invoices/${id}`, { method: "DELETE" });
}

export function issueInvoice(id: string, invoiceDate?: string): Promise<Invoice> {
  return request<Invoice>(`/api/sales/invoices/${id}/issue`, { method: "POST", body: JSON.stringify({ invoice_date: invoiceDate ?? null }) });
}

// --- Credit notes ----------------------------------------------------------------

export interface CreditNote {
  id: string;
  number: string;
  invoice_id: string;
  invoice_number: string;
  invoice_date: string;
  customer_id: string;
  customer_name: string;
  buyer_gstin: string;
  billing_address: string;
  place_of_supply: string;
  place_of_supply_name: string;
  seller_name: string;
  seller_gstin: string;
  seller_address: string;
  note_date: string;
  kind: "Return" | "Price correction";
  reason: string;
  restocked: boolean;
  total: number;
  cgst: number;
  sgst: number;
  igst: number;
  round_off: number;
  grand_total: number;
  amount_in_words: string;
  created_by_name: string | null;
  created_at: string;
  lines: { invoice_line_id: string; item_id: string; description: string; hsn_code: string; uom: string; qty: number; gst_rate: number; taxable_value: number; cgst: number; sgst: number; igst: number }[];
}

export interface CreditNoteInput {
  kind: CreditNote["kind"];
  reason: string;
  /** Returns: qty. Price corrections: amount (taxable value; GST added on top). */
  lines: { invoice_line_id: string; qty?: number; amount?: number }[];
  restock: boolean;
  note_date?: string;
}

export function fetchCreditNotes(params: { invoice_id?: string; customer_id?: string; q?: string; limit?: number; offset?: number } = {}): Promise<Page<CreditNote>> {
  return requestPage<CreditNote>("/api/sales/credit-notes", { ...params });
}

export function fetchCreditNote(id: string): Promise<CreditNote> {
  return request<CreditNote>(`/api/sales/credit-notes/${id}`);
}

export function createCreditNote(invoiceId: string, body: CreditNoteInput): Promise<CreditNote> {
  return request<CreditNote>(`/api/sales/invoices/${invoiceId}/credit-notes`, { method: "POST", body: JSON.stringify(body) });
}

// --- Payments ------------------------------------------------------------------------

export const PAYMENT_MODES = ["UPI", "Bank transfer", "Cheque", "Cash", "Card", "Other"] as const;
export type PaymentMode = (typeof PAYMENT_MODES)[number];

export interface Receipt {
  id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  receipt_date: string;
  amount: number;
  mode: PaymentMode;
  reference: string;
  notes: string;
  status: "Received" | "Voided";
  void_reason: string;
  allocated: number;
  /** Advance: received and not yet applied to an invoice. */
  unallocated: number;
  amount_in_words: string;
  created_by_name: string | null;
  created_at: string;
  allocations: { invoice_id: string; invoice_number: string | null; amount: number }[];
}

export interface ReceiptInput {
  customer_id: string;
  amount: number;
  mode: PaymentMode;
  receipt_date?: string;
  reference: string;
  notes: string;
  /** Omit: oldest unpaid invoices first. []: keep it all as an advance. */
  allocations?: { invoice_id: string; amount: number }[];
}

export function fetchPayments(params: { customer_id?: string; invoice_id?: string; q?: string; with_advance?: boolean; limit?: number; offset?: number } = {}): Promise<Page<Receipt>> {
  return requestPage<Receipt>("/api/sales/payments", { ...params });
}

export function fetchPayment(id: string): Promise<Receipt> {
  return request<Receipt>(`/api/sales/payments/${id}`);
}

export function recordPayment(body: ReceiptInput): Promise<Receipt> {
  return request<Receipt>("/api/sales/payments", { method: "POST", body: JSON.stringify(body) });
}

export function allocatePayment(id: string, allocations?: { invoice_id: string; amount: number }[]): Promise<Receipt> {
  return request<Receipt>(`/api/sales/payments/${id}/allocate`, { method: "POST", body: JSON.stringify({ allocations: allocations ?? null }) });
}

export function voidPayment(id: string, reason: string): Promise<Receipt> {
  return request<Receipt>(`/api/sales/payments/${id}/void`, { method: "POST", body: JSON.stringify({ reason }) });
}
