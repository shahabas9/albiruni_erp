# Albiruni ERP — frontend

React + TypeScript + Vite. The "Ask ERP" experience: an Overview dashboard,
CRM & Sales (pipeline, leads, follow-ups, quotations), an AI audit trail,
and a docked voice-first Ask ERP copilot — wired to the FastAPI backend in
`../backend`.

```
src/
  api/client.ts       typed fetch client (auth token, all backend endpoints)
  auth/               AuthProvider — login/logout, session restore via /api/auth/me
  theme/              light/dark ThemeProvider (toggle lives in the user menu)
  i18n/                EN/ML string tables + LanguageProvider
  data/AppDataProvider.tsx   fetches quotations, CRM records and audit events (per permission)
  askerp/              AskErpContext (open/close/ask-from-anywhere) + the docked copilot panel
  crm/                 owner picker, overdue badge, modals, opportunity drawer (quote from a deal)
  layout/              Sidebar + TopBar (search/ask box, notifications, user menu)
  lib/                 INR/date formatting, useSpeech (browser speech-to-text)
  pages/                Login, Setup, Overview, Crm, Sales, AuditTrail,
                        Customers, Items, Leads, Contacts, Opportunities, Activities, Admin
```

## Run it

Needs the backend running first (see `../backend/README.md` — Postgres +
`uvicorn` + seed script).

```bash
npm install
npm run dev
```

Sign in with the seed user: `ahmed` / `ahmed123`.

`VITE_API_BASE` (see `.env.example`) points at the backend; defaults to
`http://localhost:8000`.

## What's real vs. scripted

- Overview KPIs and charts are computed from real quotations and
  opportunities. Revenue / gross profit / receivables from the design are
  **not** shown — there's no Finance module to source them from, so the
  cards show quoted value, open pipeline, won deals and pending approvals
  instead of invented numbers.
- Sidebar modules without a backend (Purchasing, Finance, HR,
  Reports, Settings) are listed but disabled with a "Soon" tag.
- Voice input uses the browser's Web Speech API (Chrome, Edge, Safari).
  Where it's unsupported the mic is disabled and typing still works.
- Login, session restore, the Sales table and the Audit Trail are all live
  API data — nothing left in local mock state.
- The Ask ERP panel's "Create quotation" flow calls the real
  `POST /api/ask` → preview → `POST /api/ask/confirm` round trip. The
  step-by-step tracker (Understand → Resolve → Authorize → Enrich →
  Validate → Preview) is a client-side reveal of a response the backend
  already computed — not a simulation of fake numbers.
- The other three mode chips (report / diagnose / teach-me) hit the same
  real endpoint, which only recognizes quotation requests today — so they
  correctly get back an honest "I can only help with quotations right now"
  instead of a scripted answer. That's the backend's actual state, not a
  frontend limitation.

The sidebar also retains the management pages for quotations, customers, items,
leads, contacts, opportunities, activities, and users/roles. Links respect their
existing permissions. These pages and the CRM workspace share backend records;
navigating between them refreshes the shared dashboard data.
