import { useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Sidebar } from "./layout/Sidebar";
import { TopBar } from "./layout/TopBar";
import { Overview } from "./pages/Overview";
import { Sales } from "./pages/Sales";
import { Crm } from "./pages/Crm";
import { AuditTrail } from "./pages/AuditTrail";
import { Customers } from "./pages/Customers";
import { Items } from "./pages/Items";
import { Leads } from "./pages/Leads";
import { Contacts } from "./pages/Contacts";
import { Opportunities } from "./pages/Opportunities";
import { Activities } from "./pages/Activities";
import { CrmSettings } from "./pages/CrmSettings";
import { Targets } from "./pages/Targets";
import { CustomerPage } from "./pages/CustomerPage";
import { SalesSettings } from "./pages/SalesSettings";
import { Orders } from "./pages/Orders";
import { OrderEditor } from "./pages/OrderEditor";
import { OrderPage } from "./pages/OrderPage";
import { Deliveries } from "./pages/Deliveries";
import { Invoices } from "./pages/Invoices";
import { InvoicePage } from "./pages/InvoicePage";
import { PrintDocument } from "./pages/PrintDocument";
import { CreditNotes } from "./pages/CreditNotes";
import { Payments } from "./pages/Payments";
import { Receivables } from "./pages/Receivables";
import { StatementPage } from "./pages/StatementPage";
import { SalesReports } from "./pages/SalesReports";
import { QuickSale } from "./pages/QuickSale";
import { Admin } from "./pages/Admin";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { AskErpPanel } from "./askerp/AskErpPanel";
import { OpportunityDrawerHost } from "./crm/drawerHost";
import { useAskErp } from "./askerp/AskErpContext";
import { useAppData } from "./data/AppDataProvider";
import { useAuth } from "./auth/AuthProvider";

export default function App() {
  const { status } = useAuth();
  const { refresh } = useAppData();
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  useEffect(() => {
    // CRUD pages load their own data; refresh shared KPIs when navigating
    // back to the pipeline or overview after editing those records.
    if (previousPath.current !== pathname && status === "authenticated") void refresh();
    previousPath.current = pathname;
  }, [pathname, status, refresh]);
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

  // Printable documents open in their own tab, without the app around them.
  if (pathname.startsWith("/print/")) {
    return (
      <Routes>
        <Route path="/print/invoice/:id" element={<PrintDocument kind="invoice" />} />
        <Route path="/print/delivery/:id" element={<PrintDocument kind="delivery" />} />
        <Route path="/print/credit-note/:id" element={<PrintDocument kind="credit-note" />} />
        <Route path="/print/receipt/:id" element={<PrintDocument kind="receipt" />} />
        <Route path="/print/statement/:id" element={<PrintDocument kind="statement" />} />
      </Routes>
    );
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
            <Route path="/sales" element={<div className="management-page"><Sales /></div>} />
            <Route path="/customers" element={<div className="management-page"><Customers /></div>} />
            <Route path="/customers/:id" element={<div className="management-page"><CustomerPage /></div>} />
            <Route path="/sales/orders" element={<div className="management-page"><Orders /></div>} />
            <Route path="/sales/orders/new" element={<div className="management-page"><OrderEditor /></div>} />
            <Route path="/sales/orders/:id" element={<div className="management-page"><OrderPage /></div>} />
            <Route path="/sales/orders/:id/edit" element={<div className="management-page"><OrderEditor /></div>} />
            <Route path="/sales/deliveries" element={<div className="management-page"><Deliveries /></div>} />
            <Route path="/sales/invoices" element={<div className="management-page"><Invoices /></div>} />
            <Route path="/sales/invoices/:id" element={<div className="management-page"><InvoicePage /></div>} />
            <Route path="/sales/credit-notes" element={<div className="management-page"><CreditNotes /></div>} />
            <Route path="/sales/payments" element={<div className="management-page"><Payments /></div>} />
            <Route path="/sales/receivables" element={<div className="management-page"><Receivables /></div>} />
            <Route path="/sales/receivables/:customerId" element={<div className="management-page"><StatementPage /></div>} />
            <Route path="/sales/quick-sale" element={<div className="management-page"><QuickSale /></div>} />
            <Route path="/sales/reports" element={<div className="management-page"><SalesReports /></div>} />
            <Route path="/sales/settings" element={<div className="management-page"><SalesSettings /></div>} />
            <Route path="/items" element={<div className="management-page"><Items /></div>} />
            <Route path="/leads" element={<div className="management-page"><Leads /></div>} />
            <Route path="/contacts" element={<div className="management-page"><Contacts /></div>} />
            <Route path="/opportunities" element={<div className="management-page"><Opportunities /></div>} />
            <Route path="/activities" element={<div className="management-page"><Activities /></div>} />
            <Route path="/crm/targets" element={<div className="management-page"><Targets /></div>} />
            <Route path="/crm/settings" element={<div className="management-page"><CrmSettings /></div>} />
            <Route path="/admin" element={<div className="management-page"><Admin /></div>} />
            <Route path="/audit" element={<div className="management-page"><AuditTrail /></div>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <footer className="app-foot">
          <span>Live data from your Albiruni workspace</span>
          <span>ALBIRUNI ERP | Smarter business. Higher possibilities.</span>
        </footer>
      </div>
      <OpportunityDrawerHost />
      <AskErpPanel />
    </div>
  );
}
