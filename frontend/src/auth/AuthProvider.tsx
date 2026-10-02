import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  ApiError,
  fetchMe,
  fetchSetupStatus,
  login as apiLogin,
  bootstrap as apiBootstrap,
  setToken,
  getToken,
  type AuthUser,
  type BootstrapRequest,
} from "../api/client";
import { setMoneyCurrency } from "../lib/format";

type AuthStatus = "checking" | "authenticated" | "anonymous" | "needs_setup";

interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  login: (username: string, password: string) => Promise<void>;
  completeSetup: (body: BootstrapRequest) => Promise<void>;
  logout: () => void;
  error: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const applyUser = (next: AuthUser | null) => {
    setMoneyCurrency(next?.currency);
    setUser(next);
  };
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function bootstrapSession() {
      const token = getToken();
      if (token) {
        try {
          const me = await fetchMe();
          applyUser(me);
          setStatus("authenticated");
          return;
        } catch {
          setToken(null);
        }
      }
      try {
        const setup = await fetchSetupStatus();
        setStatus(setup.needs_setup ? "needs_setup" : "anonymous");
      } catch {
        // API unreachable — fall back to the login screen rather than a blank page.
        setStatus("anonymous");
      }
    }
    bootstrapSession();
  }, []);

  const login = async (username: string, password: string) => {
    setError(null);
    try {
      const res = await apiLogin(username, password);
      setToken(res.access_token);
      applyUser(res.user);
      setStatus("authenticated");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not reach the API.";
      setError(message);
      throw err;
    }
  };

  const completeSetup = async (body: BootstrapRequest) => {
    setError(null);
    try {
      const res = await apiBootstrap(body);
      setToken(res.access_token);
      applyUser(res.user);
      setStatus("authenticated");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not reach the API.";
      setError(message);
      throw err;
    }
  };

  const logout = () => {
    setToken(null);
    applyUser(null);
    setStatus("anonymous");
  };

  return (
    <AuthContext.Provider value={{ user, status, login, completeSetup, logout, error }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
