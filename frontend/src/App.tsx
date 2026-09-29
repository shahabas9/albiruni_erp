import { Route, Routes } from "react-router-dom";
import { TopBar } from "./layout/TopBar";
import { Dashboard } from "./pages/Dashboard";
import { Sales } from "./pages/Sales";
import { AuditTrail } from "./pages/AuditTrail";
import { Customers } from "./pages/Customers";
import { Items } from "./pages/Items";
import { Leads } from "./pages/Leads";
import { Contacts } from "./pages/Contacts";
import { Opportunities } from "./pages/Opportunities";
import { Activities } from "./pages/Activities";
import { Admin } from "./pages/Admin";
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
          <Route path="/customers" element={<Customers />} />
          <Route path="/items" element={<Items />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="/audit" element={<AuditTrail />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </main>
      <AskErpPanel />
    </div>
  );
}
