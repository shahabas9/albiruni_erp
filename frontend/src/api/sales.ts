/** Sales documents: company GST profile, orders, deliveries, invoices, payments. */
import { downloadFile, request, requestPage, type Page, type Quotation, type TaxTotals, type TimelineEntry } from "./client";

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

/** What a country's tax rules use (backend regimes.py). */
export interface TaxRegime {
  country: "IN" | "SA";
  country_name: string;
  currency: string;
  tax_name: "GST" | "VAT";
  tax_id_label: string;
  rates: number[];
  /** ZATCA categories (S, Z, E, O) in Saudi Arabia; empty in India. */
  categories: string[];
  round_to_unit: boolean;
  split_by_state: boolean;
  postal_code_digits: number;
  exemption_reasons: Record<string, string>;
}

export interface CompanyProfile {
  name: string;
  /** Where the company is registered; fixed once it has sales documents. */
  country: "IN" | "SA";
  currency: string;
  fy_start_month: number;
  country_locked: boolean;
  regime: TaxRegime;
  legal_name: string;
  name_ar: string;
  gstin: string;
  state_code: string;
  vat_number: string;
  cr_number: string;
  address: string;
  building_no: string;
  street: string;
  district: string;
  city: string;
  postal_code: string;
  phone: string;
  email: string;
  bank_details: string;
  invoice_terms: string;
  payment_terms_days: number;
  quotation_validity_days: number;
  allow_negative_stock: boolean;
  reminders_enabled: boolean;
  reminder_before_days: number;
  /** "1,7,15,30": days after the due date. */
  reminder_after_days: string;
}

export function fetchCompanyProfile(): Promise<CompanyProfile> {
  return request<CompanyProfile>("/api/sales/company");
}

export function updateCompanyProfile(body: Partial<Omit<CompanyProfile, "name" | "regime" | "country_locked" | "currency">>): Promise<CompanyProfile> {
  return request<CompanyProfile>("/api/sales/company", { method: "PUT", body: JSON.stringify(body) });
}

// --- Quotations ----------------------------------------------------------------

export type QuotationAction = "approve" | "send" | "accept" | "reject" | "reopen";

export function fetchQuotation(id: string): Promise<Quotation> {
  return request<Quotation>(`/api/sales/quotations/${id}`);
}

// --- Price lists ----------------------------------------------------------

export interface PriceRow {
  item_id: string;
  item_name: string;
  sku: string;
  /** The item's own price, for comparison. */
  item_price: number;
  min_qty: number;
  unit_price: number;
}

export interface PriceList {
  id: string;
  name: string;
  active: boolean;
  /** Applies to customers without a list of their own. */
  is_default: boolean;
  /** Customers on this list. */
  customers: number;
  rows: PriceRow[];
}

export interface PriceListInput {
  name: string;
  active: boolean;
  is_default: boolean;
  rows: { item_id: string; min_qty: number; unit_price: number }[];
}

export function fetchPriceLists(): Promise<PriceList[]> {
  return request<PriceList[]>("/api/sales/price-lists");
}

export function savePriceList(id: string | null, body: PriceListInput): Promise<PriceList> {
  return request<PriceList>(id ? `/api/sales/price-lists/${id}` : "/api/sales/price-lists", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(body),
  });
}

export function deletePriceList(id: string): Promise<void> {
  return request<void>(`/api/sales/price-lists/${id}`, { method: "DELETE" });
}

/** Quantity breaks per item id, lowest first. */
export type AgreedPrices = Record<string, { min_qty: number; unit_price: number }[]>;

export function fetchAgreedPrices(customerId?: string): Promise<{ price_list_id: string | null; prices: AgreedPrices }> {
  return request(`/api/sales/prices${customerId ? `?customer_id=${customerId}` : ""}`);
}

export interface QuotationInput {
  customer_id?: string;
  lines: DocLineInput[];
  discount_pct: number;
  valid_until?: string;
  notes: string;
}

export function createQuotation(body: QuotationInput): Promise<{ quotation_id: string; number: string; status: string; warnings: string[] }> {
  return request(`/api/sales/quotations`, { method: "POST", body: JSON.stringify(body) });
}

export function updateQuotation(id: string, body: Partial<Omit<QuotationInput, "customer_id">>): Promise<Quotation> {
  return request<Quotation>(`/api/sales/quotations/${id}`, { method: "PATCH", body: JSON.stringify(body) });
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
  /** This line's own discount, before the document's. */
  discount_pct: number;
  amount: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  /** Saudi VAT (0 in India). */
  vat: number;
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
  /** Who the sale counts for in targets. */
  salesperson_id: string | null;
  salesperson_name: string | null;
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
  /** Omit for the customer's agreed price (their price list, else the item's price). */
  unit_price?: number;
  discount_pct?: number;
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
  tax_category: string;
  discount_pct: number;
  amount: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  /** Saudi VAT (0 in India). */
  vat: number;
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
  /** Saudi VAT (0 in India). */
  vat: number;
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
  /** TDS the customer deducted; settles the invoice like a payment. */
  amount_tds: number;
  /** Credit balance paid back to the customer. */
  amount_refunded: number;
  /** Saudi Arabia: "standard" (B2B) or "simplified" (B2C); "" in India. */
  invoice_kind: string;
  seller_vat_number: string;
  buyer_vat_number: string;
  /** ZATCA QR code (SVG data URI) to print. */
  zatca_qr: string;
  seller_name_ar: string;
  buyer_name_ar: string;
  seller_cr_number: string;
  /** Recorded from the GST portals after upload. */
  irn: string;
  irn_ack_no: string;
  irn_ack_date: string | null;
  eway_bill_no: string;
  eway_bill_date: string | null;
  /** Still owed: total − paid − credited − TDS. */
  balance: number;
  notes: string;
  terms: string;
  bank_details: string;
  created_at: string;
  issued_at: string | null;
  issued_by_name: string | null;
  salesperson_id: string | null;
  salesperson_name: string | null;
  lines: InvoiceLine[];
  hsn_summary: HsnRow[];
  /** Single-invoice endpoint only: receipts applied to it. */
  payments: { receipt_id: string; number: string; receipt_date: string; mode: string; reference: string; amount: number; tds_amount: number }[];
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
  /** Saudi Arabia: ZATCA QR code, VAT numbers, Arabic names; "" in India. */
  zatca_qr: string;
  invoice_kind: string;
  seller_vat_number: string;
  buyer_vat_number: string;
  seller_name_ar: string;
  buyer_name_ar: string;
  seller_cr_number: string;
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
  /** Saudi VAT (0 in India). */
  vat: number;
  round_off: number;
  grand_total: number;
  amount_in_words: string;
  created_by_name: string | null;
  created_at: string;
  lines: { invoice_line_id: string; item_id: string; description: string; hsn_code: string; uom: string; qty: number; gst_rate: number; tax_category?: string; taxable_value: number; cgst: number; sgst: number; igst: number; vat: number }[];
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
  /** TDS the customer deducted on top of `amount`. */
  tds_amount: number;
  tds_section: string;
  tds_certificate_received: boolean;
  allocated: number;
  /** Advance: received and not yet applied to an invoice. */
  unallocated: number;
  /** Part of the advance paid back to the customer. */
  refunded: number;
  amount_in_words: string;
  created_by_name: string | null;
  created_at: string;
  allocations: { invoice_id: string; invoice_number: string | null; amount: number; tds_amount: number }[];
}

export const TDS_SECTIONS = ["194Q", "194C", "194J", "194H", "194I", "194O", "Other"];

export interface Refund {
  id: string;
  number: string;
  customer_id: string;
  customer_name: string;
  refund_date: string;
  amount: number;
  mode: PaymentMode;
  reference: string;
  reason: string;
  status: "Paid" | "Voided";
  void_reason: string;
  receipt_id: string | null;
  invoice_id: string | null;
  /** The receipt or invoice it was paid from. */
  source_number: string;
  created_by_name: string | null;
  created_at: string;
}

export interface RefundInput {
  receipt_id?: string;
  invoice_id?: string;
  amount: number;
  mode: PaymentMode;
  reference: string;
  reason: string;
  refund_date?: string;
}

export function fetchRefunds(params: { customer_id?: string; q?: string; limit?: number; offset?: number } = {}): Promise<Page<Refund>> {
  return requestPage<Refund>("/api/sales/refunds", { ...params });
}

export function createRefund(body: RefundInput): Promise<Refund> {
  return request<Refund>("/api/sales/refunds", { method: "POST", body: JSON.stringify(body) });
}

export function voidRefund(id: string, reason: string): Promise<Refund> {
  return request<Refund>(`/api/sales/refunds/${id}/void`, { method: "POST", body: JSON.stringify({ reason }) });
}

export interface ReceiptInput {
  customer_id: string;
  amount: number;
  mode: PaymentMode;
  receipt_date?: string;
  reference: string;
  notes: string;
  /** Omit: oldest unpaid invoices first. []: keep it all as an advance. */
  allocations?: { invoice_id: string; amount: number; tds_amount?: number }[];
  /** Needed when an allocation has tds_amount. */
  tds_section?: string;
}

export function setTdsCertificate(id: string, received: boolean): Promise<Receipt> {
  return request<Receipt>(`/api/sales/payments/${id}/tds-certificate`, { method: "POST", body: JSON.stringify({ received }) });
}

export interface TdsReport {
  rows: { date: string; receipt_number: string; receipt_id: string; customer: string; customer_pan: string; section: string; invoice_number: string; invoice_value: number; amount_received: number; tds_amount: number; certificate_received: "Yes" | "No" }[];
  total_tds: number;
  certificates_missing: number;
}

/** Saudi VAT return, sales side (boxes 1–6). */
export interface VatReturn {
  rows: { box: number; label: string; amount: number; adjustment: number; vat: number }[];
  output_vat: number;
  input_vat: number;
  net_vat_due: number;
  out_of_scope: number;
  note: string;
}

export function fetchVatReturn(dateFrom: string, dateTo: string): Promise<VatReturn> {
  return request<VatReturn>(`/api/sales/reports/vat-return?date_from=${dateFrom}&date_to=${dateTo}`);
}

export function fetchTdsReport(dateFrom: string, dateTo: string): Promise<TdsReport> {
  return request<TdsReport>(`/api/sales/reports/tds?date_from=${dateFrom}&date_to=${dateTo}`);
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

// --- Receivables ------------------------------------------------------------------

export interface AgeingRow {
  customer_id: string;
  customer_name: string;
  gstin: string;
  credit_limit: number;
  not_due: number;
  d1_30: number;
  d31_60: number;
  d61_90: number;
  d90_plus: number;
  overdue: number;
  invoiced_owed: number;
  advance: number;
  net: number;
  oldest_due: string | null;
  open_invoices: number;
}

export interface Ageing {
  as_of: string;
  rows: AgeingRow[];
  totals: Pick<AgeingRow, "not_due" | "d1_30" | "d31_60" | "d61_90" | "d90_plus" | "overdue" | "invoiced_owed" | "advance" | "net">;
}

export function fetchAgeing(q = "", asOf?: string): Promise<Ageing> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (asOf) params.set("as_of", asOf);
  const qs = params.toString();
  return request<Ageing>(`/api/sales/receivables${qs ? `?${qs}` : ""}`);
}

export interface StatementLine {
  date: string;
  kind: "Invoice" | "Credit note" | "Payment";
  number: string;
  id: string;
  details: string;
  debit: number;
  credit: number;
  balance: number;
}

export interface Statement {
  customer_id: string;
  customer_name: string;
  gstin: string;
  billing_address: string;
  date_from: string;
  date_to: string;
  opening_balance: number;
  closing_balance: number;
  total_debit: number;
  total_credit: number;
  lines: StatementLine[];
}

export function fetchStatement(customerId: string, dateFrom?: string, dateTo?: string): Promise<Statement> {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const qs = params.toString();
  return request<Statement>(`/api/sales/receivables/${customerId}/statement${qs ? `?${qs}` : ""}`);
}

// --- Reports ------------------------------------------------------------------------

export interface RegisterRow {
  date: string;
  type: "Invoice" | "Credit note";
  number: string;
  customer: string;
  gstin: string;
  place_of_supply: string;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  /** Saudi VAT (0 in India). */
  vat: number;
  /** Saudi Arabia: the buyer's VAT number. */
  vat_number: string;
  round_off: number;
  total: number;
  id: string;
}

export interface SalesRegister {
  date_from: string;
  date_to: string;
  rows: RegisterRow[];
  totals: Pick<RegisterRow, "taxable_value" | "cgst" | "sgst" | "igst" | "vat" | "round_off" | "total">;
  invoices: number;
  credit_notes: number;
}

export const GSTR1_SECTIONS = [
  { key: "b2b", label: "B2B", hint: "Invoices to registered buyers" },
  { key: "b2cl", label: "B2CL", hint: "Unregistered, other state, over ₹1 lakh" },
  { key: "b2cs", label: "B2CS", hint: "Other unregistered sales, by state and rate" },
  { key: "cdnr", label: "CDNR", hint: "Credit notes to registered buyers" },
  { key: "cdnur", label: "CDNUR", hint: "Credit notes against B2CL invoices" },
  { key: "hsn", label: "HSN", hint: "Quantities and values per HSN code" },
  { key: "docs", label: "Documents", hint: "Number ranges issued" },
] as const;
export type Gstr1Section = (typeof GSTR1_SECTIONS)[number]["key"];

export interface Gstr1 {
  date_from: string;
  date_to: string;
  summary: Record<Gstr1Section, { count: number; taxable_value: number; tax: number }>;
}

export function fetchSalesRegister(dateFrom: string, dateTo: string): Promise<SalesRegister> {
  return request<SalesRegister>(`/api/sales/reports/register?date_from=${dateFrom}&date_to=${dateTo}`);
}

export function fetchGstr1(dateFrom: string, dateTo: string): Promise<Gstr1> {
  return request<Gstr1>(`/api/sales/reports/gstr1?date_from=${dateFrom}&date_to=${dateTo}`);
}

export function downloadReport(kind: "register" | "tds" | "vat_return" | Gstr1Section, dateFrom: string, dateTo: string): Promise<number> {
  return downloadFile(`/api/sales/reports/${kind}.csv?date_from=${dateFrom}&date_to=${dateTo}`, `${kind}.csv`);
}

/** Vouchers for TallyPrime (Import → Transactions). */
export function downloadTally(dateFrom: string, dateTo: string): Promise<number> {
  return downloadFile(`/api/sales/reports/tally.xml?date_from=${dateFrom}&date_to=${dateTo}`, "tally.xml");
}

// --- Counter sale ----------------------------------------------------------------------

export interface QuickSaleInput {
  /** Omit for the company's walk-in customer. */
  customer_id?: string;
  lines: DocLineInput[];
  discount_pct: number;
  notes: string;
  /** Omit when the customer pays later. */
  payment?: { amount: number; mode: PaymentMode; reference: string };
}

export function quickSale(body: QuickSaleInput): Promise<{ order_id: string; invoice_id: string; receipt_id: string | null }> {
  return request(`/api/sales/quick-sale`, { method: "POST", body: JSON.stringify(body) });
}

// --- Sending documents ---------------------------------------------------------------

export type ShareKind = "invoice" | "quotation" | "credit_note" | "receipt" | "statement";

export interface ShareResult {
  url: string;
  message: string;
  subject: string;
  /** The message, URL-encoded for a wa.me link. */
  whatsapp_text: string;
  emailed_to: string | null;
  expires: string;
}

export function shareDocument(body: { kind: ShareKind; id: string; email?: string; date_from?: string; date_to?: string; reminder?: boolean }): Promise<ShareResult> {
  return request<ShareResult>("/api/sales/share", { method: "POST", body: JSON.stringify(body) });
}

export function fetchShareRecipients(customerId: string): Promise<{ name: string; email: string; phone: string }[]> {
  return request(`/api/sales/share/recipients?customer_id=${customerId}`);
}

export interface PublicDocument {
  kind: ShareKind;
  document: unknown;
  company: Pick<CompanyProfile, "name" | "legal_name" | "gstin" | "state_code" | "address" | "phone" | "email" | "bank_details" | "invoice_terms">;
  expires: number;
}

export function fetchPublicDocument(token: string): Promise<PublicDocument> {
  return request<PublicDocument>(`/api/public/documents/${encodeURIComponent(token)}`);
}

// --- Dashboard ------------------------------------------------------------

export interface SalesDashboard {
  as_of: string;
  /** Needs sales.invoice.read. */
  money?: {
    invoiced_this_month: number;
    invoiced_last_month: number;
    /** Payments received less refunds paid, this month. */
    collected_this_month: number;
    outstanding: number;
    overdue: number;
    advances: number;
    overdue_customers: { customer_id: string; name: string; overdue: number }[];
    /** Invoiced less credit notes per month, oldest first. */
    monthly: { month: string; label: string; value: number }[];
    top_customers: { customer_id: string; name: string; value: number }[];
    fy_label: string;
  };
  orders?: { to_invoice: number; drafts: number };
  quotations?: { awaiting_reply: number; awaiting_value: number };
}

export function fetchSalesDashboard(): Promise<SalesDashboard> {
  return request<SalesDashboard>("/api/sales/dashboard");
}

// --- GST portals ----------------------------------------------------------

export interface PortalJson {
  filename: string;
  /** India: NIC JSON in payload. Saudi Arabia: ZATCA UBL XML in content. */
  format?: "json" | "xml";
  payload?: unknown;
  content?: string;
  /** What isn't in the file yet and why (e.g. ZATCA signing). */
  notes?: string[];
  /** What the portal would reject; fix before uploading. */
  problems: string[];
}

export function fetchEinvoice(kind: "invoices" | "credit-notes", id: string): Promise<PortalJson> {
  return request<PortalJson>(`/api/sales/${kind}/${id}/einvoice`);
}

export function fetchEwayBill(id: string, params: { distance_km: number; vehicle_no: string; transporter_id: string }): Promise<PortalJson> {
  const q = new URLSearchParams({ distance_km: String(params.distance_km), vehicle_no: params.vehicle_no, transporter_id: params.transporter_id });
  return request<PortalJson>(`/api/sales/invoices/${id}/ewaybill?${q}`);
}

export function recordGstRefs(
  id: string,
  body: Partial<{ irn: string; irn_ack_no: string; irn_ack_date: string; eway_bill_no: string; eway_bill_date: string }>,
): Promise<Invoice> {
  return request<Invoice>(`/api/sales/invoices/${id}/gst-refs`, { method: "PUT", body: JSON.stringify(body) });
}

/** Saves the JSON as a file for the portal's upload. */
export function saveJson(file: PortalJson) {
  const blob =
    file.format === "xml"
      ? new Blob([file.content ?? ""], { type: "application/xml" })
      : new Blob([JSON.stringify(file.payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function setOrderSalesperson(id: string, userId: string | null): Promise<SalesOrder> {
  return request<SalesOrder>(`/api/sales/orders/${id}/salesperson`, { method: "PUT", body: JSON.stringify({ user_id: userId }) });
}

export function setInvoiceSalesperson(id: string, userId: string | null): Promise<Invoice> {
  return request<Invoice>(`/api/sales/invoices/${id}/salesperson`, { method: "PUT", body: JSON.stringify({ user_id: userId }) });
}
