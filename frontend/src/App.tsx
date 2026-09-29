import { Route, Routes } from "react-router-dom";
import { TopBar } from "./layout/TopBar";
import { Dashboard } from "./pages/Dashboard";
import { Sales } from "./pages/Sales";
import { AuditTrail } from "./pages/AuditTrail";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { AskErpPanel } from "./askerp/AskErpPanel";
import { useAuth } from "./auth/AuthProvider";

export default function App() {
  const { status } = useAuth();

  if (status === "checking") {
    return (
      <div className="login-shell">
        <p style={{ color: "var(--ink-dim)", fontSize: 13 }}>Loading…</p>
      </div>
    );
  }

  if (status === "needs_setup") {
    return <Setup />;
  }

  if (status === "anonymous") {
    return <Login />;
  }

  return (
    <div className="shell">
      <TopBar />
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/sales" element={<Sales />} />
          <Route path="/audit" element={<AuditTrail />} />
        </Routes>
      </main>
      <AskErpPanel />
    </div>
  );
}
