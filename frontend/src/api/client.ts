export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const TOKEN_KEY = "albiruni-token";

/** A record a create would duplicate (409 from the lead/customer forms). */
export interface DuplicateMatch {
  id: string;
  label: string;
  detail: string;
}

export class ApiError extends Error {
  status: number;
  /** Set when the server refused a create as a likely duplicate. */
  duplicates: DuplicateMatch[] | null;
  constructor(status: number, message: string, duplicates: DuplicateMatch[] | null = null) {
    super(message);
    this.status = status;
    this.duplicates = duplicates;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // non-fatal: session just won't persist across reloads
  }
}

/** One page of a list plus how many rows match in total (X-Total-Count). */
export interface Page<T> {
  rows: T[];
  total: number;
}

export type Params = Record<string, string | number | boolean | null | undefined>;

export function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function requestPage<T>(path: string, params: Params): Promise<Page<T>> {
  const res = await send(`${path}${query(params)}`);
  const rows = (await res.json()) as T[];
  return { rows, total: Number(res.headers.get("X-Total-Count") ?? rows.length) };
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await send(path, options);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function send(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // FormData sets its own multipart boundary; everything else we send is JSON.
  if (options.body && !(options.body instanceof URLSearchParams) && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    let duplicates: DuplicateMatch[] | null = null;
    try {
      const body = await res.json();
      // FastAPI validation errors arrive as a list of {loc, msg}; show their messages.
      if (Array.isArray(body.detail)) {
        detail = body.detail.map((d: { msg?: string }) => String(d.msg ?? "").replace(/^Value error, /, "")).join(" ");
      } else if (body.detail && typeof body.detail === "object") {
        detail = body.detail.message ?? detail;
        duplicates = body.detail.duplicates ?? null;
      } else {
        detail = body.detail ?? detail;
      }
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail, duplicates);
  }
  return res;
}

// --- Auth ---------------------------------------------------------------

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  locale: string;
  role: string | null;
  permissions: string[];
  company: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export function login(username: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams({ username, password });
  return request<LoginResponse>("/api/auth/login", { method: "POST", body });
}

export function fetchMe(): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me");
}

// --- Setup (first-run bootstrap) -------------------------------------------

export interface SetupStatus {
  needs_setup: boolean;
}

export function fetchSetupStatus(): Promise<SetupStatus> {
  return request<SetupStatus>("/api/setup/status");
}

export interface BootstrapRequest {
  organization_name: string;
  company_name: string;
  admin_name: string;
  username: string;
  password: string;
}

export function bootstrap(body: BootstrapRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/api/setup/bootstrap", { method: "POST", body: JSON.stringify(body) });
}

// --- Sales ----------------------------------------------------------------

export interface QuotationLine {
  item_name: string;
  qty: number;
  unit_price: number;
  line_total: number;
  hsn_code?: string;
  gst_rate?: number;
  taxable_value?: number;
  tax_amount?: number;
}

/** GST figures every sales document carries. */
export interface TaxTotals {
  /** After discount, before GST. */
  total: number;
  cgst: number;
  sgst: number;
  igst: number;
  round_off: number;
  /** What the customer pays. */
  grand_total: number;
}

export interface Quotation extends TaxTotals {
  id: string;
  number: string;
  customer_name: string;
  opportunity_id: string | null;
  opportunity_title: string | null;
  subtotal: number;
  discount_pct: number;
  place_of_supply: string;
  status: "Draft" | "Pending approval" | "Sent" | "Accepted" | "Rejected";
  status_note: string;
  customer_id: string | null;
  /** The order this quotation became (not cancelled), if any. */
  order_id: string | null;
  order_number: string | null;
  created_at: string;
  lines: QuotationLine[];
}

export function fetchQuotations(customerId?: string): Promise<Quotation[]> {
  return request<Quotation[]>(`/api/sales/quotations${query({ customer_id: customerId })}`);
}

export function fetchSalesItems(): Promise<Item[]> {
  return request<Item[]>("/api/sales/items");
}

export interface QuotationLineInput {
  item_name: string;
  qty: number;
}

export interface CreateQuotationResult {
  quotation_id: string;
  number: string;
  status: string;
  total: number;
  warnings: string[];
  requires_approval: boolean;
}

// --- Ask ERP ----------------------------------------------------------------

export type AskResponse =
  | { type: "preview"; preview_token: string; correlation_id: string; tool_name: string; risk_level: string; customer: string; lines: QuotationLine[]; subtotal: number; discount_pct: number; discount_amount: number; total: number; cgst: number; sgst: number; igst: number; round_off: number; grand_total: number; requires_approval: boolean; warnings: string[] }
  | ActionPreview
  | AskAnswer
  | { type: "message" | "clarify" | "denied" | "error"; message: string; options?: string[] };

/** A CRM write Ask ERP will perform only after you confirm it. */
export interface ActionPreview {
  type: "action_preview";
  preview_token: string;
  correlation_id: string;
  tool_name: string;
  risk_level: string;
  title: string;
  lines: { label: string; value: string }[];
  warnings: string[];
}

/** A read Ask ERP answered straight away (overdue follow-ups, stale deals, pipeline). */
export interface AskAnswer {
  type: "answer";
  message: string;
  items: { title: string; subtitle: string; tone: "bad" | "warn" | null; link: string | null }[];
  link: { label: string; to: string } | null;
}

export function askErp(text: string): Promise<AskResponse> {
  // The browser's timezone, so "tomorrow at 3pm" means the user's 3pm.
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  return request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ text, timezone }) });
}

export interface ConfirmResponse {
  /** CRM tools: what was done, and where to see it. */
  result_summary?: string;
  link?: { label: string; to: string };
  quotation_id: string;
  number: string;
  status: string;
  customer: string;
  subtotal: number;
  discount_pct: number;
  total: number;
  warnings: string[];
  requires_approval: boolean;
}

export function confirmAsk(previewToken: string): Promise<ConfirmResponse> {
  return request<ConfirmResponse>("/api/ask/confirm", {
    method: "POST",
    body: JSON.stringify({ preview_token: previewToken }),
  });
}

// --- Audit ----------------------------------------------------------------

export interface AuditEvent {
  id: string;
  correlation_id: string;
  actor: string;
  intent: string;
  risk_level: string;
  tool_name: string;
  validation_result: string;
  confirmed: boolean;
  result_summary: string;
  created_at: string;
}

export function fetchAuditEvents(): Promise<AuditEvent[]> {
  return request<AuditEvent[]>("/api/audit/events");
}

// --- Customers --------------------------------------------------------------

export interface Customer {
  id: string;
  name: string;
  credit_limit: number;
  active: boolean;
  /** GST registration number; "" if unregistered. */
  gstin: string;
  tags: string[];
  /** Custom field values by field key. */
  custom: CustomValues;
  billing_address: string;
  shipping_address: string;
  /** GST state code; follows the GSTIN when there is one. */
  state_code: string;
  /** null: the company's default terms. */
  payment_terms_days: number | null;
}

export interface CustomerInput {
  name: string;
  credit_limit: number;
  gstin?: string;
  /** Create even though a customer with this name or GSTIN exists. */
  allow_duplicate?: boolean;
  tags?: string[];
  /** On update only the keys sent change; null or "" clears one. */
  custom?: CustomValues;
  billing_address?: string;
  shipping_address?: string;
  state_code?: string;
  payment_terms_days?: number | null;
}

export interface CustomerQuery {
  /** Only records carrying this tag. */
  tag?: string;
  /** Every word must appear in the name or GSTIN. */
  q?: string;
  active?: boolean;
  limit?: number;
  offset?: number;
}

export function fetchCustomers(params: CustomerQuery = {}): Promise<Page<Customer>> {
  return requestPage<Customer>("/api/customers", { ...params });
}

export function fetchCustomer(id: string): Promise<Customer> {
  return request<Customer>(`/api/customers/${id}`);
}

export function createCustomer(body: CustomerInput): Promise<Customer> {
  return request<Customer>("/api/customers", { method: "POST", body: JSON.stringify(body) });
}

export function updateCustomer(id: string, body: Partial<CustomerInput & { active: boolean }>): Promise<Customer> {
  return request<Customer>(`/api/customers/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// --- Items --------------------------------------------------------------

export interface Item {
  id: string;
  sku: string;
  name: string;
  uom: string;
  unit_price: number;
  stock_qty: number;
  kind: "goods" | "service";
  hsn_code: string;
  /** null until set; invoices refuse items without a rate. */
  gst_rate: number | null;
}

export type ItemInput = Omit<Item, "id">;

export function fetchItems(): Promise<Item[]> {
  return request<Item[]>("/api/items");
}

export function createItem(body: ItemInput): Promise<Item> {
  return request<Item>("/api/items", { method: "POST", body: JSON.stringify(body) });
}

export function updateItem(id: string, body: Partial<ItemInput>): Promise<Item> {
  return request<Item>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// --- Admin: roles & users -----------------------------------------------

export interface Role {
  id: string;
  name: string;
  permissions: string[];
}

export function fetchRoles(): Promise<Role[]> {
  return request<Role[]>("/api/admin/roles");
}

export function createRole(body: { name: string; permissions: string[] }): Promise<Role> {
  return request<Role>("/api/admin/roles", { method: "POST", body: JSON.stringify(body) });
}

export function updateRole(id: string, body: Partial<{ name: string; permissions: string[] }>): Promise<Role> {
  return request<Role>(`/api/admin/roles/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  role_id: string;
  role_name: string | null;
  locale: string;
  active: boolean;
  /** Where their notifications are emailed; "" for in-app only. */
  email: string;
}

export function fetchAdminUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>("/api/admin/users");
}

export function createAdminUser(body: {
  username: string;
  display_name: string;
  password: string;
  role_id: string;
  email?: string;
}): Promise<AdminUser> {
  return request<AdminUser>("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
}

export function updateAdminUser(
  id: string,
  body: Partial<{ display_name: string; role_id: string; password: string; active: boolean; email: string }>,
): Promise<AdminUser> {
  return request<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// --- Permission catalog ---------------------------------------------------
// Not backend-enumerated (there's no registry endpoint) — this is every
// permission string actually checked somewhere in the API today, kept next
// to the role-creation UI so it can't silently drift out of sync.
export const KNOWN_PERMISSIONS = [
  "sales.quotation.read",
  "sales.quotation.create",
  "sales.quotation.approve",
  "sales.customer.read",
  "sales.customer.write",
  "sales.settings.write",
  "sales.order.read",
  "sales.order.write",
  "sales.credit.override",
  "sales.delivery.write",
  "sales.invoice.read",
  "sales.invoice.write",
  "inventory.stock.adjust",
  "inventory.item.read",
  "inventory.item.write",
  "crm.lead.read",
  "crm.lead.write",
  "crm.lead.convert",
  "crm.lead.assign",
  "crm.contact.read",
  "crm.contact.write",
  "crm.opportunity.read",
  "crm.opportunity.write",
  "crm.opportunity.assign",
  "crm.activity.read",
  "crm.activity.write",
  "crm.settings.write",
  "crm.records.all",
  "crm.lead.delete",
  "crm.opportunity.delete",
  "sales.customer.delete",
  "crm.export",
  "admin.users.read",
  "admin.users.write",
  "audit.read",
] as const;

// --- CRM: Leads -----------------------------------------------------------

export type LeadStatus = "New" | "Contacted" | "Qualified" | "Converted" | "Lost";
export const LEAD_STATUSES: LeadStatus[] = ["New", "Contacted", "Qualified", "Converted", "Lost"];

/** Open/overdue follow-up counts the API attaches to leads and opportunities. */
export interface FollowUpSummary {
  open_activities: number;
  overdue_activities: number;
  next_due_at: string | null;
}

export interface Assignee {
  id: string;
  display_name: string;
}

export function fetchAssignees(): Promise<Assignee[]> {
  return request<Assignee[]>("/api/assignees");
}

export interface Lead extends FollowUpSummary {
  id: string;
  name: string;
  company_name: string;
  email: string;
  phone: string;
  source: string;
  status: LeadStatus;
  notes: string;
  owner_user_id: string | null;
  owner_name: string | null;
  converted_customer_id: string | null;
  converted_opportunity_id: string | null;
  tags: string[];
  /** Custom field values by field key. */
  custom: CustomValues;
  created_at: string;
}

export interface LeadInput {
  name: string;
  company_name?: string;
  email?: string;
  phone?: string;
  source?: string;
  notes?: string;
  /** Anyone but yourself needs crm.lead.assign. */
  owner_user_id?: string | null;
  /** Create even though a lead with this phone or email exists. */
  allow_duplicate?: boolean;
  /** Give it to the next person in the lead rotation (owner_user_id is then ignored). */
  assign_by_rotation?: boolean;
  tags?: string[];
  /** On update only the keys sent change; null or "" clears one. */
  custom?: CustomValues;
  billing_address?: string;
  shipping_address?: string;
  state_code?: string;
  payment_terms_days?: number | null;
}

/** owner: "me", "unassigned" or a user id. status: a status or "open". */
export interface LeadQuery {
  /** Only records carrying this tag. */
  tag?: string;
  q?: string;
  status?: string;
  owner?: string;
  limit?: number;
  offset?: number;
}

export function fetchLeads(params: LeadQuery = {}): Promise<Page<Lead>> {
  return requestPage<Lead>("/api/leads", { ...params });
}

export function fetchLead(id: string): Promise<Lead> {
  return request<Lead>(`/api/leads/${id}`);
}

export interface CustomerMatch {
  id: string;
  name: string;
  gstin: string;
  reasons: string[];
}

export function fetchLeadCustomerMatches(id: string): Promise<CustomerMatch[]> {
  return request<CustomerMatch[]>(`/api/leads/${id}/customer-matches`);
}

export interface TimelineEntry {
  id: string;
  at: string;
  record_type: "lead" | "opportunity" | "customer";
  action: string;
  summary: string;
  changes: Record<string, [unknown, unknown]>;
  /** Where the change was made. */
  source: "app" | "ask_erp" | "import" | "web_form";
  actor_name: string | null;
}

export function fetchLeadTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/leads/${id}/timeline`);
}

export function createLead(body: LeadInput): Promise<Lead> {
  return request<Lead>("/api/leads", { method: "POST", body: JSON.stringify(body) });
}

export function updateLead(
  id: string,
  body: Partial<Omit<LeadInput, "owner_user_id"> & { status: LeadStatus }>,
): Promise<Lead> {
  return request<Lead>(`/api/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function assignLead(id: string, owner_user_id: string | null): Promise<Lead> {
  return request<Lead>(`/api/leads/${id}/owner`, { method: "PATCH", body: JSON.stringify({ owner_user_id }) });
}

export interface ConvertLeadResult {
  lead_id: string;
  customer_id: string;
  contact_id: string;
  opportunity_id: string | null;
}

export function convertLead(
  id: string,
  body: {
    /** Link to this existing customer; omit to create a new one. */
    customer_id?: string | null;
    create_opportunity: boolean;
    opportunity_name?: string;
    opportunity_value: number;
    expected_close_date?: string | null;
  },
): Promise<ConvertLeadResult> {
  return request<ConvertLeadResult>(`/api/leads/${id}/convert`, { method: "POST", body: JSON.stringify(body) });
}

// --- CRM: Contacts ----------------------------------------------------------

export interface Contact {
  id: string;
  customer_id: string;
  customer_name: string;
  name: string;
  title: string;
  email: string;
  phone: string;
}

export interface ContactQuery {
  /** Every word must appear in the name, customer, phone or email. */
  q?: string;
  customer_id?: string;
  limit?: number;
  offset?: number;
}

export function fetchContacts(params: ContactQuery = {}): Promise<Page<Contact>> {
  return requestPage<Contact>("/api/contacts", { ...params });
}

export function createContact(body: {
  customer_id: string;
  name: string;
  title?: string;
  email?: string;
  phone?: string;
}): Promise<Contact> {
  return request<Contact>("/api/contacts", { method: "POST", body: JSON.stringify(body) });
}

export function updateContact(
  id: string,
  body: Partial<{ name: string; title: string; email: string; phone: string }>,
): Promise<Contact> {
  return request<Contact>(`/api/contacts/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// --- CRM: Opportunities -------------------------------------------------------

export type OpportunityStage = "New" | "Qualified" | "Proposal" | "Negotiation" | "Won" | "Lost";
export const OPPORTUNITY_STAGES: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"];

export interface Opportunity extends FollowUpSummary {
  id: string;
  customer_id: string;
  customer_name: string;
  lead_id: string | null;
  name: string;
  stage: OpportunityStage;
  value: number;
  probability_pct: number;
  expected_close_date: string | null;
  notes: string;
  /** Set when stage is Lost. */
  lost_reason: string;
  /** When the stage last changed (the won/lost date for closed deals). */
  stage_changed_at: string;
  owner_user_id: string | null;
  owner_name: string | null;
  quotations: Quotation[];
  /** Last stage change, follow-up or quotation on the deal. */
  last_touch_at: string;
  idle_days: number;
  /** Open deal untouched longer than its stage allows. */
  is_stale: boolean;
  tags: string[];
  /** Custom field values by field key. */
  custom: CustomValues;
  created_at: string;
}

/** Suggestions for the lost-reason picker; any text is accepted. */
export const LOST_REASONS = [
  "Price too high",
  "Chose a competitor",
  "No budget",
  "No response",
  "Timing / postponed",
  "Requirement changed",
];

export interface OpportunityInput {
  customer_id: string;
  name: string;
  value?: number;
  probability_pct?: number;
  expected_close_date?: string | null;
  notes?: string;
  /** Anyone but yourself needs crm.opportunity.assign. */
  owner_user_id?: string | null;
  tags?: string[];
  /** On update only the keys sent change; null or "" clears one. */
  custom?: CustomValues;
  billing_address?: string;
  shipping_address?: string;
  state_code?: string;
  payment_terms_days?: number | null;
}

/** stage: a stage, "open" or "closed". closed_since: open deals plus those closed since (YYYY-MM-DD). */
export interface OpportunityQuery {
  customer_id?: string;
  /** Only records carrying this tag. */
  tag?: string;
  q?: string;
  stage?: string;
  owner?: string;
  closed_since?: string;
  stale?: boolean;
  limit?: number;
  offset?: number;
}

export function fetchOpportunities(params: OpportunityQuery = {}): Promise<Page<Opportunity>> {
  return requestPage<Opportunity>("/api/opportunities", { ...params });
}

export function fetchOpportunity(id: string): Promise<Opportunity> {
  return request<Opportunity>(`/api/opportunities/${id}`);
}

export function fetchOpportunityTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/opportunities/${id}/timeline`);
}

export function createOpportunity(body: OpportunityInput): Promise<Opportunity> {
  return request<Opportunity>("/api/opportunities", { method: "POST", body: JSON.stringify(body) });
}

export function updateOpportunity(
  id: string,
  body: Partial<Omit<OpportunityInput, "customer_id" | "owner_user_id"> & { stage: OpportunityStage; lost_reason: string }>,
): Promise<Opportunity> {
  return request<Opportunity>(`/api/opportunities/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function assignOpportunity(id: string, owner_user_id: string | null): Promise<Opportunity> {
  return request<Opportunity>(`/api/opportunities/${id}/owner`, {
    method: "PATCH",
    body: JSON.stringify({ owner_user_id }),
  });
}

/** Raises a quotation for the opportunity's customer; moves New/Qualified deals to Proposal. */
export function quoteOpportunity(
  id: string,
  body: { lines: QuotationLineInput[]; discount_pct: number },
): Promise<CreateQuotationResult> {
  return request<CreateQuotationResult>(`/api/opportunities/${id}/quotations`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- CRM: Activities ----------------------------------------------------------

export type ActivityType = "Call" | "WhatsApp" | "Meeting" | "Email" | "Task" | "Note";
export const ACTIVITY_TYPES: ActivityType[] = ["Call", "WhatsApp", "Meeting", "Email", "Task", "Note"];

export interface Activity {
  id: string;
  type: ActivityType;
  subject: string;
  notes: string;
  due_date: string | null;
  due_at: string | null;
  done: boolean;
  completed_at: string | null;
  is_overdue: boolean;
  lead_id: string | null;
  customer_id: string | null;
  opportunity_id: string | null;
  related_label: string;
  owner_id: string | null;
  owner_name: string | null;
  created_at: string;
}

export interface ActivityInput {
  type: ActivityType;
  subject: string;
  notes?: string;
  /** Due by the end of this day… */
  due_date?: string | null;
  /** …or at this exact time (ISO); wins over due_date. */
  due_at?: string | null;
  lead_id?: string | null;
  customer_id?: string | null;
  opportunity_id?: string | null;
  /** true logs something that already happened (e.g. a call just made). */
  done?: boolean;
}

export type ActivityShow = "open" | "overdue" | "done" | "all";

export interface ActivityQuery {
  show?: ActivityShow;
  owner?: string;
  lead_id?: string;
  customer_id?: string;
  opportunity_id?: string;
  limit?: number;
  offset?: number;
}

export function fetchActivities(params: ActivityQuery = {}): Promise<Page<Activity>> {
  return requestPage<Activity>("/api/activities", { ...params });
}

export function createActivity(body: ActivityInput): Promise<Activity> {
  return request<Activity>("/api/activities", { method: "POST", body: JSON.stringify(body) });
}

export function updateActivity(
  id: string,
  body: Partial<{ subject: string; notes: string; due_date: string | null; done: boolean }>,
): Promise<Activity> {
  return request<Activity>(`/api/activities/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

// --- CSV import -----------------------------------------------------------------

export type ImportKind = "leads" | "customers";

export interface ImportResult {
  kind: ImportKind;
  /** canonical column -> the header it was read from */
  columns: Record<string, string>;
  total: number;
  ok: number;
  duplicates: number;
  errors: number;
  created: number;
  committed: boolean;
  rows: { line: number; status: "ok" | "duplicate" | "error"; messages: string[]; values: Record<string, string> }[];
}

/** Dry run by default; commit=true creates the valid rows. */
export function importCsv(kind: ImportKind, csv: string, commit = false): Promise<ImportResult> {
  return request<ImportResult>(`/api/imports/${kind}${commit ? "?commit=true" : ""}`, {
    method: "POST",
    body: JSON.stringify({ csv }),
  });
}

// --- CRM: settings and summary ----------------------------------------------

/** Days a deal may sit untouched in each open stage before it's flagged; 0 = never. */
export interface StaleLimits {
  New: number;
  Qualified: number;
  Proposal: number;
  Negotiation: number;
}

export function fetchStaleLimits(): Promise<StaleLimits> {
  return request<StaleLimits>("/api/crm/settings");
}

export function saveStaleLimits(body: StaleLimits): Promise<StaleLimits> {
  return request<StaleLimits>("/api/crm/settings", { method: "PUT", body: JSON.stringify(body) });
}

export interface CrmSummary {
  open_deals: number;
  open_value: number;
  weighted_value: number;
  by_stage: { stage: OpportunityStage; count: number; value: number; weighted: number }[];
  stale_deals: number;
  stale_value: number;
  won_deals: number;
  won_value: number;
  lost_deals: number;
  won_this_month_value: number;
  /** Deals closed in the last `closed_days` days. */
  closed_days: number;
  recent_won: number;
  recent_won_value: number;
  recent_lost: number;
  recent_lost_value: number;
  lost_reasons: { reason: string; count: number }[];
  recently_closed: Opportunity[];
  unassigned: number;
  open_followups: number;
  overdue_followups: number;
  /** The five most overdue follow-ups, for the bell and dashboard. */
  overdue_items: Activity[];
}

/** owner narrows the deal figures ("me", "unassigned" or a user id). */
export function fetchCrmSummary(params: { owner?: string; closed_days?: number } = {}): Promise<CrmSummary> {
  return request<CrmSummary>(`/api/crm/summary${query(params)}`);
}

// --- CRM: lead rotation ------------------------------------------------------

/** Who new leads go to in turn. */
export interface Rotation {
  enabled: boolean;
  /** In rotation order. */
  user_ids: string[];
  next_user_id: string | null;
  next_user_name: string | null;
}

export function fetchRotation(): Promise<Rotation> {
  return request<Rotation>("/api/crm/rotation");
}

export function saveRotation(body: { enabled: boolean; user_ids: string[] }): Promise<Rotation> {
  return request<Rotation>("/api/crm/rotation", { method: "PUT", body: JSON.stringify(body) });
}

// --- CRM: sales targets -------------------------------------------------------

export interface TargetRow {
  user_id: string;
  name: string;
  active: boolean;
  target: number;
  /** Value of deals this person moved to Won during the month. */
  won_value: number;
  won_count: number;
  /** Their open deals expected to close this month, value × probability. */
  forecast: number;
  pct: number | null;
}

export interface TargetReport {
  month: string;
  rows: TargetRow[];
  team_target: number;
  team_won: number;
  team_pct: number | null;
  /** Won by deals nobody owns — counted in the team total only. */
  unowned_won_value: number;
  unowned_won_count: number;
}

/** month: "YYYY-MM"; this month when omitted. */
export function fetchTargets(month?: string): Promise<TargetReport> {
  return request<TargetReport>(`/api/crm/targets${query({ month })}`);
}

/** An amount of 0 removes that person's target. */
export function saveTargets(month: string, targets: { user_id: string; amount: number }[]): Promise<TargetReport> {
  return request<TargetReport>("/api/crm/targets", { method: "PUT", body: JSON.stringify({ month, targets }) });
}

// --- CRM: tags and custom fields ---------------------------------------------

export type RecordType = "lead" | "opportunity" | "customer";
export type CustomFieldType = "text" | "number" | "date" | "select" | "checkbox";
export type CustomValue = string | number | boolean | null;
export type CustomValues = Record<string, CustomValue>;

export interface CustomField {
  id: string;
  record_type: RecordType;
  /** Values are stored under this; it never changes. */
  key: string;
  label: string;
  field_type: CustomFieldType;
  /** Choices, for "select". */
  options: string[];
  position: number;
  /** Archived fields are hidden from forms; their saved values are kept. */
  active: boolean;
}

export function fetchCustomFields(recordType?: RecordType, includeArchived = false): Promise<CustomField[]> {
  return request<CustomField[]>(`/api/crm/fields${query({ record_type: recordType, include_archived: includeArchived || undefined })}`);
}

export function createCustomField(body: {
  record_type: RecordType;
  label: string;
  field_type: CustomFieldType;
  options?: string[];
}): Promise<CustomField> {
  return request<CustomField>("/api/crm/fields", { method: "POST", body: JSON.stringify(body) });
}

export function updateCustomField(
  id: string,
  body: Partial<{ label: string; options: string[]; position: number; active: boolean }>,
): Promise<CustomField> {
  return request<CustomField>(`/api/crm/fields/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function fetchTags(recordType: RecordType): Promise<{ tag: string; count: number }[]> {
  return request<{ tag: string; count: number }[]>(`/api/crm/tags${query({ record_type: recordType })}`);
}

// --- CRM: attachments ----------------------------------------------------------

export interface Attachment {
  id: string;
  record_type: RecordType;
  record_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by_name: string | null;
  created_at: string;
}

export const ATTACHMENT_MAX_MB = 10;

export function fetchAttachments(recordType: RecordType, recordId: string): Promise<Attachment[]> {
  return request<Attachment[]>(`/api/attachments${query({ record_type: recordType, record_id: recordId })}`);
}

export function uploadAttachment(recordType: RecordType, recordId: string, file: File): Promise<Attachment> {
  const body = new FormData();
  body.set("record_type", recordType);
  body.set("record_id", recordId);
  body.set("file", file);
  return request<Attachment>("/api/attachments", { method: "POST", body });
}

export function deleteAttachment(id: string): Promise<void> {
  return request<void>(`/api/attachments/${id}`, { method: "DELETE" });
}

/** Downloads with the session token (a plain link can't send it) and saves under the original name. */
export async function downloadAttachment(attachment: Attachment): Promise<void> {
  const res = await send(`/api/attachments/${attachment.id}/download`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: attachment.filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- CRM: web enquiry form ------------------------------------------------------

export interface WebForm {
  enabled: boolean;
  /** Secret part of the public link; null until first turned on. */
  key: string | null;
  /** Lead source recorded on enquiries. */
  source: string;
  thank_you: string;
}

export function webFormUrl(key: string): string {
  return `${API_BASE}/api/public/enquiry/${key}`;
}

export function fetchWebForm(): Promise<WebForm> {
  return request<WebForm>("/api/crm/web-form");
}

export function saveWebForm(body: Partial<{ enabled: boolean; source: string; thank_you: string }>): Promise<WebForm> {
  return request<WebForm>("/api/crm/web-form", { method: "PUT", body: JSON.stringify(body) });
}

export function newWebFormKey(): Promise<WebForm> {
  return request<WebForm>("/api/crm/web-form/new-key", { method: "POST" });
}

// --- Notifications ----------------------------------------------------------------

export interface AppNotification {
  id: string;
  kind: "lead_assigned" | "deal_assigned" | "followup_assigned" | "followup_overdue" | "web_enquiry" | "import" | string;
  title: string;
  body: string;
  /** A path in this app, e.g. /crm?opp=… */
  link: string;
  read_at: string | null;
  created_at: string;
}

export function fetchNotifications(): Promise<{ unread: number; items: AppNotification[] }> {
  return request<{ unread: number; items: AppNotification[] }>("/api/notifications");
}

/** Omit ids to mark everything read. */
export function markNotificationsRead(ids?: string[]): Promise<{ marked: number }> {
  return request<{ marked: number }>("/api/notifications/read", { method: "POST", body: JSON.stringify({ ids }) });
}

export interface NotificationPreferences {
  email: string;
  notify_email: boolean;
  /** Whether the server can send email at all. */
  email_enabled: boolean;
}

export function fetchNotificationPreferences(): Promise<NotificationPreferences> {
  return request<NotificationPreferences>("/api/notifications/preferences");
}

export function saveNotificationPreferences(body: { email?: string; notify_email?: boolean }): Promise<NotificationPreferences> {
  return request<NotificationPreferences>("/api/notifications/preferences", { method: "PUT", body: JSON.stringify(body) });
}

// --- Delete and merge -------------------------------------------------------------

export function deleteLead(id: string): Promise<void> {
  return request<void>(`/api/leads/${id}`, { method: "DELETE" });
}

/** Folds lead `removeId` into `keepId`, then removes it. */
export function mergeLeads(keepId: string, removeId: string): Promise<Lead> {
  return request<Lead>(`/api/leads/${keepId}/merge`, { method: "POST", body: JSON.stringify({ remove_id: removeId }) });
}

export function fetchLeadDuplicates(): Promise<{ reason: string; leads: Lead[] }[]> {
  return request<{ reason: string; leads: Lead[] }[]>("/api/leads/duplicates");
}

export function deleteOpportunity(id: string): Promise<void> {
  return request<void>(`/api/opportunities/${id}`, { method: "DELETE" });
}

export function deleteContact(id: string): Promise<void> {
  return request<void>(`/api/contacts/${id}`, { method: "DELETE" });
}

export function deleteCustomer(id: string): Promise<void> {
  return request<void>(`/api/customers/${id}`, { method: "DELETE" });
}

/** Moves everything of customer `removeId` onto `keepId`, then removes it. */
export function mergeCustomers(keepId: string, removeId: string): Promise<Customer> {
  return request<Customer>(`/api/customers/${keepId}/merge`, { method: "POST", body: JSON.stringify({ remove_id: removeId }) });
}

export function fetchCustomerDuplicates(): Promise<{ reason: string; customers: Customer[] }[]> {
  return request<{ reason: string; customers: Customer[] }[]>("/api/customers/duplicates");
}

// --- Customer page -----------------------------------------------------------------

export interface CustomerOverview {
  customer: Customer;
  open_deals: number;
  open_value: number;
  won_deals: number;
  won_value: number;
  lost_deals: number;
  contacts: number;
  /** null without sales.quotation.read */
  quotations: number | null;
  quoted_value: number | null;
}

export function fetchCustomerOverview(id: string): Promise<CustomerOverview> {
  return request<CustomerOverview>(`/api/customers/${id}/overview`);
}

export function fetchCustomerTimeline(id: string): Promise<TimelineEntry[]> {
  return request<TimelineEntry[]>(`/api/customers/${id}/timeline`);
}

// --- Export ----------------------------------------------------------------------

export type ExportKind = "leads" | "opportunities" | "customers" | "contacts" | "activities";

/** Downloads a list as CSV with the given filters (same as the list's query parameters). */
export async function downloadExport(kind: ExportKind, filters: Params = {}): Promise<number> {
  const res = await send(`/api/exports/${kind}.csv${query(filters)}`);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `${kind}.csv`;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return Number(res.headers.get("X-Row-Count") ?? 0);
}

// --- Bulk actions ------------------------------------------------------------------

export interface BulkResult {
  matched: number;
  done: number;
  skipped: { id: string; label: string; reason: string }[];
}

/** ids, or filters for "everything matching" (the list's own filter params). */
export function bulkAction(
  list: "leads" | "opportunities" | "customers",
  body: { action: string; ids?: string[]; filters?: Params; value?: string | null; lost_reason?: string },
): Promise<BulkResult> {
  return request<BulkResult>(`/api/${list}/bulk`, { method: "POST", body: JSON.stringify(body) });
}

// --- Saved views ------------------------------------------------------------------

export type ViewPage = "leads" | "opportunities" | "customers" | "contacts" | "activities";
export type ViewFilters = Record<string, string | boolean | number | null>;

export interface SavedView {
  id: string;
  page: ViewPage;
  name: string;
  filters: ViewFilters;
  shared: boolean;
  /** Saved by me (so I can change or delete it). */
  mine: boolean;
  owner_name: string | null;
  created_at: string;
}

export function fetchViews(page: ViewPage): Promise<SavedView[]> {
  return request<SavedView[]>(`/api/views${query({ page })}`);
}

export function createView(body: { page: ViewPage; name: string; filters: ViewFilters; shared: boolean }): Promise<SavedView> {
  return request<SavedView>("/api/views", { method: "POST", body: JSON.stringify(body) });
}

export function updateView(id: string, body: Partial<{ name: string; filters: ViewFilters; shared: boolean }>): Promise<SavedView> {
  return request<SavedView>(`/api/views/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteView(id: string): Promise<void> {
  return request<void>(`/api/views/${id}`, { method: "DELETE" });
}
