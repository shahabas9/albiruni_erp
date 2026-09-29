const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const TOKEN_KEY = "albiruni-token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      // FastAPI validation errors arrive as a list of {loc, msg}; show their messages.
      detail = Array.isArray(body.detail)
        ? body.detail.map((d: { msg?: string }) => String(d.msg ?? "").replace(/^Value error, /, "")).join(" ")
        : (body.detail ?? detail);
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
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
  | { type: "message" | "clarify" | "denied" | "error"; message: string };

export function askErp(text: string): Promise<AskResponse> {
  return request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ text }) });
}

export interface ConfirmResponse {
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
}

export function fetchCustomers(): Promise<Customer[]> {
  return request<Customer[]>("/api/customers");
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
}

export function fetchLeads(): Promise<Lead[]> {
  return request<Lead[]>("/api/leads");
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

export function fetchContacts(): Promise<Contact[]> {
  return request<Contact[]>("/api/contacts");
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

export function fetchOpportunities(): Promise<Opportunity[]> {
  return request<Opportunity[]>("/api/opportunities");
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

export function fetchActivities(openOnly = false): Promise<Activity[]> {
  return request<Activity[]>(`/api/activities${openOnly ? "?open_only=true" : ""}`);
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
