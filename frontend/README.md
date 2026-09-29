# Albiruni ERP — frontend

React + TypeScript + Vite. The "Ask ERP" experience: a dashboard, a Sales
module, an AI audit trail, and a global command panel — wired to the
FastAPI backend in `../backend`.

```
src/
  api/client.ts       typed fetch client (auth token, all backend endpoints)
  auth/               AuthProvider — login/logout, session restore via /api/auth/me
  theme/              light/dark ThemeProvider + the day/night switch
  i18n/                EN/ML string tables + LanguageProvider
  data/AppDataProvider.tsx   fetches quotations + audit events from the API
  askerp/              AskErpContext (open/close/ask-from-anywhere) + the panel itself
  layout/TopBar.tsx
  pages/                Login, Dashboard, Sales, AuditTrail
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
