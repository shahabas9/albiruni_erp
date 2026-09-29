# Albiruni ERP — backend skeleton

A walking skeleton of the layered architecture from the blueprint: **models
never touch data directly** — everything, human or AI, goes through the same
permissioned Tool Gateway, and every AI-initiated write is audited.

```
app/
  core/          config, DB session, JWT/password hashing, auth dependency (RequestContext)
  models/        SQLAlchemy models: Tenant, Company, Role, User, Customer, Item,
                 Lead, Contact, Opportunity, Activity (crm.py),
                 Quotation, QuotationLine, AuditEvent
  domain/        sales_service.py — deterministic business logic (pricing, discount
                 policy, stock check). No AI or HTTP concerns here.
  toolgateway/   registry.py (typed ToolDefinition contracts) + executor.py (the one
                 place that checks permissions and writes AuditEvent) + tools_sales.py
  ai/            orchestrator.py — naive regex intent/entity parser + the preview
                 cache. Stands in for a real LLM call; swap it out later without
                 touching anything downstream.
  api/           FastAPI routers: auth, sales, ask (Ask ERP), audit
  seed.py        dev fixture data
```

## The one idea that matters

`POST /api/ask` runs Understand → Resolve → Authorize → Enrich → Validate →
Preview and **never writes to the database**. It returns a `preview_token`
bound to the current user, tenant and computed totals, with a 10-minute
expiry. `POST /api/ask/confirm` is the only endpoint that can act on that
token — single use, and every field is re-validated against fresh data
before anything is persisted. The same `sales.create_quotation_draft.v1`
tool also backs the plain form endpoint (`POST /api/sales/quotations`) —
there is exactly one way to create a quotation, not an AI path and a
separate "real" path.

## Run it

```bash
# 1. Postgres (either works)
docker compose up -d              # if you have the compose plugin
docker run -d --name albiruni-postgres -e POSTGRES_USER=albiruni \
  -e POSTGRES_PASSWORD=albiruni -e POSTGRES_DB=albiruni_erp -p 5432:5432 postgres:16-alpine

# 2. Python deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Seed demo data (tenant_018 / company_kozhikode / user "ahmed", password "ahmed123")
#    Re-running on a DB seeded before CRM existed grants the CRM permissions
#    and adds demo leads/opportunities without touching anything else.
.venv/bin/python -m app.seed

# 4. Run
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## Try the full Appendix A flow

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -d "username=ahmed&password=ahmed123" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/api/ask -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Create a quotation for Rahman Traders: 50 boxes Product A and 20 boxes Product B. Give 3% discount."}'
# -> {"type": "preview", "preview_token": "...", "total": 32204.0, "requires_approval": true, ...}

curl -s -X POST http://localhost:8000/api/ask/confirm -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"preview_token": "<paste from above>"}'

curl -s http://localhost:8000/api/audit/events -H "Authorization: Bearer $TOKEN"
```

## What's deliberately not here yet

- **A real LLM.** `app/ai/orchestrator.py` is regex-based on purpose, so the
  skeleton runs with no API key. Swap `classify_intent` / `parse_quotation_request`
  for a Claude tool-calling loop against `toolgateway.registry.list_tools()` —
  the executor, audit trail and permission checks don't need to change.
- **Alembic migrations.** Schema is created via `Base.metadata.create_all()`
  at startup for dev convenience. Add real migrations before this touches a
  shared environment.
- **CRM writes aren't audited.** Leads, opportunities, owners and follow-ups
  are plain permission-checked routes (see "CRM API" below). The one CRM
  action that creates a financial document —
  `POST /api/opportunities/{id}/quotations` — runs the same audited
  `sales.create_quotation_draft.v1` tool as every other quotation, with
  the opportunity linked via `quotations.opportunity_id`.
- **More domains.** Only Sales/Quotations and CRM exist. Inventory, Finance etc.
  follow the same three-file pattern: a model, a domain service, a tool.

## Frontend

`../frontend` is wired to this API (see its README): real login, real
quotations/audit data, and the Ask ERP panel calling `/api/ask` +
`/api/ask/confirm` for real. Mode chips other than "Create quotation" still
just get the honest "I can only help with quotations right now" fallback,
because only that one tool exists so far.

## CRM API

One API, one permission set. Each record type has its own routes and
`read` / `write` permissions; owners are changed through a separate
`/owner` route so reassigning can be granted on its own.

| Routes | Permissions |
| --- | --- |
| `/api/leads`, `PATCH /{id}/owner`, `POST /{id}/convert` | `crm.lead.read`, `crm.lead.write`, `crm.lead.assign`, `crm.lead.convert` |
| `/api/opportunities`, `PATCH /{id}/owner`, `POST /{id}/quotations` | `crm.opportunity.read`, `crm.opportunity.write`, `crm.opportunity.assign` (+ `sales.quotation.create` to quote) |
| `/api/activities` (`?open_only=true`) | `crm.activity.read`, `crm.activity.write` |
| `/api/contacts` | `crm.contact.read`, `crm.contact.write` |
| `/api/assignees` | any of `crm.lead.read`, `crm.opportunity.read`, `crm.activity.read` |

Leads and opportunities come back with their owner's name and open/overdue
follow-up counts; opportunities also carry their linked quotations. An
activity is overdue once `due_at` passes while it's not done; a date-only
activity is due by the end of that day (UTC — the web app sends the end of
the user's local day instead).

The old workspace permissions `crm.read`, `crm.write` and `crm.assign` are
retired: dev startup expands them on existing roles into the per-record
permissions above and removes them.

Startup upgrades a development database from either CRM prototype, preserving
existing records and normalizing pipeline stages to New / Qualified / Proposal /
Negotiation / Won / Lost. Production deployments should use reviewed Alembic
migrations instead of this development bootstrap.

To run the CRM integration tests, supply an empty disposable PostgreSQL
**test database**, never your normal development database:

```bash
CRM_TEST_DB=1 DATABASE_URL=postgresql+psycopg://USER:PASS@localhost/TEST_DB \
  .venv/bin/python -m unittest discover -s tests -v
```
