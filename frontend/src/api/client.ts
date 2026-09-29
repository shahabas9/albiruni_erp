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
      detail = body.detail ?? detail;
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

export interface Item {
  id: string;
  sku: string;
  name: string;
  uom: string;
  unit_price: number;
  stock_qty: number;
}

export function fetchItems(): Promise<Item[]> {
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

// --- CRM ----------------------------------------------------------------------

export const LEAD_STATUSES = ["New", "Contacted", "Qualified", "Disqualified", "Converted"] as const;
export const OPPORTUNITY_STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation", "Won", "Lost"] as const;
export const ACTIVITY_KINDS = ["Call", "Meeting", "Email", "Task"] as const;

export type LeadStatus = (typeof LEAD_STATUSES)[number];
export type OpportunityStage = (typeof OPPORTUNITY_STAGES)[number];
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export interface Assignee {
  id: string;
  display_name: string;
}

interface FollowUpSummary {
  owner_id: string | null;
  owner_name: string | null;
  open_activities: number;
  overdue_activities: number;
  next_due_at: string | null;
  created_at: string;
}

export interface Lead extends FollowUpSummary {
  id: string;
  name: string;
  organization: string;
  phone: string;
  email: string;
  source: string;
  status: LeadStatus;
  converted_opportunity_id: string | null;
}

export interface Opportunity extends FollowUpSummary {
  id: string;
  title: string;
  customer_name: string;
  lead_id: string | null;
  stage: OpportunityStage;
  expected_value: number;
  expected_close: string | null;
  quotations: Quotation[];
}

export interface Activity {
  id: string;
  kind: ActivityKind;
  subject: string;
  due_at: string;
  completed_at: string | null;
  is_overdue: boolean;
  lead_id: string | null;
  opportunity_id: string | null;
  related_name: string;
  owner_id: string | null;
  owner_name: string | null;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const crm = {
  assignees: () => request<Assignee[]>("/api/crm/assignees"),
  leads: () => request<Lead[]>("/api/crm/leads"),
  opportunities: () => request<Opportunity[]>("/api/crm/opportunities"),
  activities: () => request<Activity[]>("/api/crm/activities"),

  createLead: (body: { name: string; organization: string; phone: string; email: string; source: string; owner_id: string | null }) =>
    request<Lead>("/api/crm/leads", { method: "POST", ...json(body) }),
  assignLead: (id: string, owner_id: string | null) =>
    request<Lead>(`/api/crm/leads/${id}/owner`, { method: "PATCH", ...json({ owner_id }) }),
  setLeadStatus: (id: string, status: LeadStatus) =>
    request<Lead>(`/api/crm/leads/${id}/status`, { method: "PATCH", ...json({ status }) }),
  convertLead: (id: string, body: { title: string; expected_value: number; expected_close: string | null }) =>
    request<Opportunity>(`/api/crm/leads/${id}/convert`, { method: "POST", ...json(body) }),

  createOpportunity: (body: { title: string; customer_name: string; expected_value: number; expected_close: string | null; owner_id: string | null }) =>
    request<Opportunity>("/api/crm/opportunities", { method: "POST", ...json(body) }),
  assignOpportunity: (id: string, owner_id: string | null) =>
    request<Opportunity>(`/api/crm/opportunities/${id}/owner`, { method: "PATCH", ...json({ owner_id }) }),
  setStage: (id: string, stage: OpportunityStage) =>
    request<Opportunity>(`/api/crm/opportunities/${id}/stage`, { method: "PATCH", ...json({ stage }) }),
  quoteOpportunity: (id: string, body: { lines: QuotationLineInput[]; discount_pct: number }) =>
    request<CreateQuotationResult>(`/api/crm/opportunities/${id}/quotations`, { method: "POST", ...json(body) }),

  createActivity: (body: { kind: ActivityKind; subject: string; due_at: string; lead_id?: string; opportunity_id?: string }) =>
    request<Activity>("/api/crm/activities", { method: "POST", ...json(body) }),
  completeActivity: (id: string) => request<Activity>(`/api/crm/activities/${id}/complete`, { method: "POST" }),
};

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
