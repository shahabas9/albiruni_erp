import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  crm,
  fetchAuditEvents,
  fetchItems,
  fetchQuotations,
  type Activity,
  type Assignee,
  type AuditEvent,
  type Item,
  type Lead,
  type Opportunity,
  type Quotation,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";

interface AppDataContextValue {
  quotes: Quotation[];
  auditLog: AuditEvent[];
  leads: Lead[];
  opportunities: Opportunity[];
  activities: Activity[];
  assignees: Assignee[];
  items: Item[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AppDataContext = createContext<AppDataContextValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const [quotes, setQuotes] = useState<Quotation[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEvent[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const permissions = user?.permissions ?? [];
  const can = useCallback(
    (permission: string) => permissions.includes("*") || permissions.includes(permission),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [permissions.join("|")],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    // Only ask for what this role can read, and let each module fail on its
    // own — a missing permission on Audit shouldn't blank the CRM.
    const skip = <T,>(): Promise<T[]> => Promise.resolve([]);
    const [q, a, l, o, act, asg, it] = await Promise.allSettled([
      can("sales.quotation.read") ? fetchQuotations() : skip<Quotation>(),
      can("audit.read") ? fetchAuditEvents() : skip<AuditEvent>(),
      can("crm.read") ? crm.leads() : skip<Lead>(),
      can("crm.read") ? crm.opportunities() : skip<Opportunity>(),
      can("crm.read") ? crm.activities() : skip<Activity>(),
      can("crm.read") ? crm.assignees() : skip<Assignee>(),
      can("sales.quotation.read") ? fetchItems() : skip<Item>(),
    ]);
    if (q.status === "fulfilled") setQuotes(q.value);
    if (a.status === "fulfilled") setAuditLog(a.value);
    if (l.status === "fulfilled") setLeads(l.value);
    if (o.status === "fulfilled") setOpportunities(o.value);
    if (act.status === "fulfilled") setActivities(act.value);
    if (asg.status === "fulfilled") setAssignees(asg.value);
    if (it.status === "fulfilled") setItems(it.value);
    if ([q, a, l, o, act, asg, it].some((r) => r.status === "rejected")) {
      setError("Couldn't reach part of the Albiruni API — is the backend running?");
    }
    setLoading(false);
  }, [can]);

  useEffect(() => {
    if (status === "authenticated") refresh();
    if (status === "anonymous") {
      setQuotes([]);
      setAuditLog([]);
      setLeads([]);
      setOpportunities([]);
      setActivities([]);
      setAssignees([]);
      setItems([]);
    }
  }, [status, refresh]);

  return (
    <AppDataContext.Provider
      value={{ quotes, auditLog, leads, opportunities, activities, assignees, items, loading, error, refresh, can }}
    >
      {children}
    </AppDataContext.Provider>
  );
}

export function useAppData(): AppDataContextValue {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData must be used within an AppDataProvider");
  return ctx;
}
