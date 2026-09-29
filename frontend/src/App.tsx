import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./layout/Sidebar";
import { TopBar } from "./layout/TopBar";
import { Overview } from "./pages/Overview";
import { Crm } from "./pages/Crm";
import { AuditTrail } from "./pages/AuditTrail";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { AskErpPanel } from "./askerp/AskErpPanel";
import { useAskErp } from "./askerp/AskErpContext";
import { useAuth } from "./auth/AuthProvider";

export default function App() {
  const { status } = useAuth();
  const { isOpen } = useAskErp();
  const [navOpen, setNavOpen] = useState(false);

  if (status === "checking") {
    return (
      <div className="login-shell">
        <p style={{ color: "rgba(255,255,255,.7)", fontSize: 13 }}>Loading…</p>
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
    <div className={`app${isOpen ? " copilot-docked" : ""}`}>
      <Sidebar open={navOpen} onNavigate={() => setNavOpen(false)} />
      <div className="workspace">
        <TopBar onMenu={() => setNavOpen(true)} />
        <main className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/crm" element={<Crm />} />
            <Route path="/sales" element={<Navigate to="/crm?tab=quotations" replace />} />
            <Route path="/audit" element={<AuditTrail />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <footer className="app-foot">
          <span>Live data from your Albiruni workspace</span>
          <span>ALBIRUNI ERP | Smarter business. Higher possibilities.</span>
        </footer>
      </div>
      <AskErpPanel />
    </div>
  );
}
