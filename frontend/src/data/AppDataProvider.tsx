import { createContext, useContext, useState, type ReactNode } from "react";

export type ActionLevel = "L1 Read" | "L2 Prepare" | "L3 Execute";
export type QuoteStatus = "Draft" | "Pending approval" | "Sent";

export interface Quotation {
  id: string;
  customer: string;
  items: string;
  value: string;
  status: QuoteStatus;
  risk: ActionLevel;
  updated: string;
  isNew?: boolean;
}

export interface AuditEntry {
  id: string;
  time: string;
  actor: string;
  intent: string;
  risk: ActionLevel;
  tool: string;
  result: string;
  context: string;
  corr: string;
}

const initialQuotes: Quotation[] = [
  {
    id: "QT-2026-00187",
    customer: "Coastal Traders",
    items: "3 lines",
    value: "₹1,84,200",
    status: "Sent",
    risk: "L2 Prepare",
    updated: "2 days ago",
  },
  {
    id: "QT-2026-00189",
    customer: "Malabar Hardware",
    items: "7 lines",
    value: "₹6,42,000",
    status: "Pending approval",
    risk: "L3 Execute",
    updated: "Yesterday",
  },
  {
    id: "QT-2026-00190",
    customer: "Al Faisal Trading",
    items: "2 lines",
    value: "₹58,400",
    status: "Draft",
    risk: "L2 Prepare",
    updated: "Yesterday",
  },
  {
    id: "QT-2026-00191",
    customer: "Rahman Traders",
    items: "1 line",
    value: "₹31,500",
    status: "Sent",
    risk: "L2 Prepare",
    updated: "Today, 07:52",
  },
  {
    id: "QT-2026-00192",
    customer: "Coastal Traders",
    items: "4 lines",
    value: "₹2,10,800",
    status: "Draft",
    risk: "L2 Prepare",
    updated: "Today, 09:10",
  },
];

const initialAudit: AuditEntry[] = [
  {
    id: "AE-88213",
    time: "Today 07:52",
    actor: "user_ahmed",
    intent: "sales.create_quotation",
    risk: "L2 Prepare",
    tool: "sales.create_quotation_draft.v1",
    result: "QT-2026-00191 · Draft created",
    context: "Sales / Quotation / new · locale ml-IN",
    corr: "corr_6f81a2",
  },
  {
    id: "AE-88190",
    time: "Yesterday 16:04",
    actor: "user_fathima",
    intent: "procurement.create_po",
    risk: "L3 Execute",
    tool: "procurement.post_purchase_order.v1",
    result: "PO-2026-00512 · Released",
    context: "Procurement / PO / release · locale en-IN",
    corr: "corr_5c02e9",
  },
  {
    id: "AE-88176",
    time: "Yesterday 11:21",
    actor: "user_ahmed",
    intent: "finance.explain_variance",
    risk: "L1 Read",
    tool: "finance.get_variance_explanation",
    result: "Answer returned · no data changed",
    context: "Finance / P&L / Sep 2026 · locale en-IN",
    corr: "corr_4b91f0",
  },
];

interface AppDataContextValue {
  quotes: Quotation[];
  auditLog: AuditEntry[];
  addQuote: (q: Quotation) => void;
  addAuditEntry: (a: AuditEntry) => void;
}

const AppDataContext = createContext<AppDataContextValue | null>(null);

let quoteCounter = 193;
export function nextQuoteId() {
  return `QT-2026-00${quoteCounter++}`;
}

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [quotes, setQuotes] = useState<Quotation[]>(initialQuotes);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>(initialAudit);

  const addQuote = (q: Quotation) => setQuotes((prev) => [q, ...prev]);
  const addAuditEntry = (a: AuditEntry) => setAuditLog((prev) => [a, ...prev]);

  return (
    <AppDataContext.Provider value={{ quotes, auditLog, addQuote, addAuditEntry }}>
      {children}
    </AppDataContext.Provider>
  );
}

export function useAppData(): AppDataContextValue {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData must be used within an AppDataProvider");
  return ctx;
}
