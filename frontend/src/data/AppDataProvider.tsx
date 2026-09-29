import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, fetchAuditEvents, fetchQuotations, type AuditEvent, type Quotation } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

function describeError(err: unknown): string {
  // A 403 already carries a precise, honest message from the backend
  // ("Missing permission: X") — surface it as-is instead of masking it
  // behind a generic "can't reach the API" message.
  if (err instanceof ApiError) return err.message;
  return "Couldn't reach the Albiruni API — is the backend running?";
}

interface AppDataContextValue {
  quotes: Quotation[];
  auditLog: AuditEvent[];
  loading: boolean;
  quotesError: string | null;
  auditError: string | null;
  refresh: () => Promise<void>;
}

const AppDataContext = createContext<AppDataContextValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [quotes, setQuotes] = useState<Quotation[]>([]);
  const [auditLog, setAuditLog] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [quotesError, setQuotesError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    // Fetched independently (not Promise.all): lacking permission for one
    // — audit trail, say — must not blank out data the user can see, like
    // their own Sales quotations.
    const [quotesResult, auditResult] = await Promise.allSettled([fetchQuotations(), fetchAuditEvents()]);

    if (quotesResult.status === "fulfilled") {
      setQuotes(quotesResult.value);
      setQuotesError(null);
    } else {
      setQuotesError(describeError(quotesResult.reason));
    }

    if (auditResult.status === "fulfilled") {
      setAuditLog(auditResult.value);
      setAuditError(null);
    } else {
      setAuditError(describeError(auditResult.reason));
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    if (status === "authenticated") refresh();
    if (status === "anonymous") {
      setQuotes([]);
      setAuditLog([]);
      setQuotesError(null);
      setAuditError(null);
    }
  }, [status, refresh]);

  return (
    <AppDataContext.Provider value={{ quotes, auditLog, loading, quotesError, auditError, refresh }}>
      {children}
    </AppDataContext.Provider>
  );
}

export function useAppData(): AppDataContextValue {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData must be used within an AppDataProvider");
  return ctx;
}
