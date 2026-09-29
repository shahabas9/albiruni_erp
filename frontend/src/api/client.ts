const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
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

type Params = Record<string, string | number | boolean | null | undefined>;

function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

async function requestPage<T>(path: string, params: Params): Promise<Page<T>> {
  const res = await send(`${path}${query(params)}`);
  const rows = (await res.json()) as T[];
  return { rows, total: Number(res.headers.get("X-Total-Count") ?? rows.length) };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await send(path, options);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function send(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof URLSearchParams)) {
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
}

export interface Quotation {
  id: string;
  number: string;
  customer_name: string;
  opportunity_id: string | null;
  opportunity_title: string | null;
  subtotal: number;
  discount_pct: number;
  total: number;
  status: "Draft" | "Pending approval" | "Sent";
  created_at: string;
  lines: QuotationLine[];
}

export function fetchQuotations(): Promise<Quotation[]> {
  return request<Quotation[]>("/api/sales/quotations");
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
  | { type: "preview"; preview_token: string; correlation_id: string; tool_name: string; risk_level: string; customer: string; lines: QuotationLine[]; subtotal: number; discount_pct: number; discount_amount: number; total: number; requires_approval: boolean; warnings: string[] }
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
}

export interface CustomerInput {
  name: string;
  credit_limit: number;
  gstin?: string;
  /** Create even though a customer with this name or GSTIN exists. */
  allow_duplicate?: boolean;
}

export interface CustomerQuery {
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
}

export function fetchAdminUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>("/api/admin/users");
}

export function createAdminUser(body: {
  username: string;
  display_name: string;
  password: string;
  role_id: string;
}): Promise<AdminUser> {
  return request<AdminUser>("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
}

export function updateAdminUser(
  id: string,
  body: Partial<{ display_name: string; role_id: string; password: string; active: boolean }>,
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
}

/** owner: "me", "unassigned" or a user id. status: a status or "open". */
export interface LeadQuery {
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
  source: "app" | "ask_erp" | "import";
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
}

/** stage: a stage, "open" or "closed". closed_since: open deals plus those closed since (YYYY-MM-DD). */
export interface OpportunityQuery {
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
