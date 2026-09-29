import { Route, Routes } from "react-router-dom";
import { TopBar } from "./layout/TopBar";
import { Dashboard } from "./pages/Dashboard";
import { Sales } from "./pages/Sales";
import { AuditTrail } from "./pages/AuditTrail";
import { AskErpPanel } from "./askerp/AskErpPanel";

export default function App() {
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
