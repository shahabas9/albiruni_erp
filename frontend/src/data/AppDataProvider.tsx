import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { fetchAuditEvents, fetchQuotations, type AuditEvent, type Quotation } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

interface AppDataContextValue {
  quotes: Quotation[];
  auditLog: AuditEvent[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const AppDataContext = createContext<AppDataContextValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [quotes, setQuotes] = useState<Quotation[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [quotesRes, auditRes] = await Promise.all([fetchQuotations(), fetchAuditEvents()]);
      setQuotes(quotesRes);
      setAuditLog(auditRes);
    } catch {
      setError("Couldn't reach the Albiruni API — is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") refresh();
    if (status === "anonymous") {
      setQuotes([]);
      setAuditLog([]);
    }
  }, [status, refresh]);

  return (
    <AppDataContext.Provider value={{ quotes, auditLog, loading, error, refresh }}>
      {children}
    </AppDataContext.Provider>
  );
}

export function useAppData(): AppDataContextValue {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData must be used within an AppDataProvider");
  return ctx;
}
