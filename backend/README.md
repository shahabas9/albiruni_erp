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

Quotation numbers are `QT-<year>-<n>`, counting from 1 per tenant each year
(`document_counters`, incremented with a row-locking upsert so concurrent
quotes never share a number) and unique per tenant.

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

- **A real LLM.** Understanding is deterministic on purpose, so the skeleton
  runs with no API key: `app/ai/crm_parser.py` classifies every request and
  `orchestrator.parse_quotation_request` extracts quotation lines. Swap them
  for a Claude tool-calling loop against `toolgateway.registry.list_tools()` —
  the tools, executor, audit trail and permission checks don't need to change.
- **Alembic migrations.** Schema is created via `Base.metadata.create_all()`
  at startup for dev convenience. Add real migrations before this touches a
  shared environment.
- **CRM writes go through plain routes, not the tool gateway.** They're
  permission-checked and every change lands in the record's history (see
  "Record history" below), but only Ask ERP actions and quotations write
  `AuditEvent`s. `POST /api/opportunities/{id}/quotations` runs the same
  audited `sales.create_quotation_draft.v1` tool as every other quotation,
  with the opportunity linked via `quotations.opportunity_id`.
- **More domains.** Only Sales/Quotations and CRM exist. Inventory, Finance etc.
  follow the same three-file pattern: a model, a domain service, a tool.

## Frontend

`../frontend` is wired to this API (see its README): real login, real
quotations/audit data, and the Ask ERP panel calling `/api/ask` +
`/api/ask/confirm` for real.

## Ask ERP: CRM commands

`POST /api/ask` (send the browser's IANA `timezone`) also understands CRM
requests. Reads answer straight away; writes return an `action_preview` that
only `POST /api/ask/confirm` executes. Every call goes through the tool
gateway (`toolgateway/tools_crm.py`), so it's permission-checked and audited.

| Say | Tool | Level |
| --- | --- | --- |
| "what's overdue today" / "… for the team" | `crm.list_due_followups.v1` | L1 Read |
| "which deals are going stale" | `crm.list_stale_deals.v1` | L1 Read |
| "how's the pipeline" | `crm.pipeline_summary.v1` | L1 Read |
| "log a call with Rahman — no answer", "met Al Faisal about Q4" | `crm.log_activity.v1` | L2 Prepare |
| "remind me to call Nisha tomorrow at 3pm", "follow up with Malabar on Friday" | `crm.schedule_followup.v1` | L2 Prepare |
| "move Al Faisal to negotiation", "mark Malabar lost — price too high" | `crm.move_opportunity_stage.v1` | L2 Prepare |

Names are resolved against the company's own leads, customers and deals
(`app/ai/crm_resolver.py`) by distinctive words, not a sentence template;
ties come back as a `clarify` with clickable options. Activity goes on the
customer's single open deal when there is one. Dates understand today /
tomorrow / weekdays / "next week" / "in 3 days" / "5 Oct" / dd/mm, in the
user's timezone; a date with no time means 10:00.

## CSV import

`POST /api/imports/{leads|customers}` with `{"csv": "..."}` validates every
row and reports `ok` / `duplicate` / `error` without writing; add
`?commit=true` to create the valid rows in one transaction. Headers are
matched loosely ("Mobile", "Business", "Party Name", "GSTIN/UIN" …), comma,
semicolon or tab separated, Excel's BOM tolerated; 2 MB / 2,000 rows max.
Leads are duplicates when their phone (last 10 digits) or email already
exists; customers when their name or GSTIN does. Needs `crm.lead.write` /
`sales.customer.write`; assigning leads to someone else needs
`crm.lead.assign`.

## CRM API

One API, one permission set. Each record type has its own routes and
`read` / `write` permissions; owners are changed through a separate
`/owner` route so reassigning can be granted on its own.

| Routes | Permissions |
| --- | --- |
| `/api/leads`, `PATCH /{id}/owner`, `POST /{id}/convert` | `crm.lead.read`, `crm.lead.write`, `crm.lead.assign`, `crm.lead.convert` |
| `/api/opportunities`, `PATCH /{id}/owner`, `POST /{id}/quotations` | `crm.opportunity.read`, `crm.opportunity.write`, `crm.opportunity.assign` (+ `sales.quotation.create` to quote) |
| `/api/activities` | `crm.activity.read`, `crm.activity.write` |
| `/api/contacts` | `crm.contact.read`, `crm.contact.write` |
| `/api/assignees`, `GET /api/crm/summary` | any of `crm.lead.read`, `crm.opportunity.read`, `crm.activity.read` |
| `GET /api/crm/settings` / `PUT` | `crm.opportunity.read` / `crm.settings.write` |

**Record visibility.** People whose role lacks `crm.records.all` see only
the leads and deals they own, and follow-ups they own or that sit on their
leads and deals — in every list, detail, history, file, summary, target
report, tag count and Ask ERP answer (others' records are a 404). A
duplicate warning still says a matching lead exists, without saying whose.
Customers and contacts stay shared. On upgrade, every existing role that
could read leads or deals is granted `crm.records.all` once (tracked in
`dev_upgrades`), so nothing changes until an admin takes it away.

**Notifications.** People are told (bell in the app, `GET /api/notifications`,
`POST /api/notifications/read`) when a lead, deal or follow-up is given to
them by someone else (including the rotation and conversions), when CSV
import gives them leads (one alert per import), when a web enquiry arrives
(its owner, or everyone who can assign leads when it's unassigned), and when
one of their follow-ups goes overdue (once per due time). Each user sets an
email and on/off at `/api/notifications/preferences`; with `SMTP_HOST`,
`SMTP_FROM` (and optionally `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`SMTP_STARTTLS`, `APP_URL` for links) notifications are emailed too, retried
up to 3 times. A background loop in the API (`NOTIFICATION_WORKER`,
`NOTIFICATION_INTERVAL_SECONDS`, default 60) raises overdue alerts and sends
email; it claims rows with `SKIP LOCKED`, so several processes can run it.
WhatsApp alerts need a WhatsApp Business provider and aren't built in.

**Delete and merge.** `DELETE /api/leads/{id}` (`crm.lead.delete`),
`/api/opportunities/{id}` (`crm.opportunity.delete`), `/api/contacts/{id}`
(`crm.contact.write`) and `/api/customers/{id}` (`sales.customer.delete`)
remove a record with its follow-ups and files — but never history others
depend on: converted leads, deals with quotations, and customers with deals,
quotations or converted leads are refused with what to do instead (mark
Lost, or merge). `POST /api/leads/{id}/merge` and
`POST /api/customers/{id}/merge` with `{"remove_id": …}` fold the second
record into the first: blank details filled, notes/tags/custom values
combined, and follow-ups, files, history (and for customers contacts, deals,
quotations and converted leads) moved over. `GET /api/leads/duplicates` and
`/api/customers/duplicates` list groups sharing a phone/email or a
name/GSTIN. Deletes and merges are recorded in history.

**Lists page on the server.** `GET /api/leads`, `/api/opportunities` and
`/api/activities` take `limit` (max 200), `offset` and filters, and return
the total matching count in `X-Total-Count`: leads `q` (every word must
appear in name, company, phone or email), `status` (a status or `open`),
`owner` (`me`, `unassigned` or a user id); opportunities `q`, `stage` (a
stage, `open` or `closed`), `owner`, `closed_since` (open deals plus those
closed since a date — the pipeline board) and `stale=true`; activities
`show` (`open`, `overdue`, `done`, `all`), `owner` and `lead_id` /
`customer_id` / `opportunity_id`. `GET /api/customers` (`q` on name or
GSTIN, `active`) and `GET /api/contacts` (`q`, `customer_id`) page the same
way. Without `limit` everything matching comes back. Stale deals are
filtered in SQL (`crm_service.stale_only`), so `stale=true` pages like any
other filter.

`GET /api/crm/summary` gives the dashboard, sidebar, bell and pipeline board
their numbers as aggregate queries — pipeline by stage (count, value,
weighted), stale deals, won/lost, deals closed in the last `closed_days`
(default 90) with lost reasons and the six most recent, unowned records,
overdue follow-ups plus the five most overdue — so no screen loads every
record. `owner` narrows the deal figures. The pipeline board shows the 30
newest deals per stage with the stage's totals and a link to the rest.

**Duplicates.** Creating a lead with the phone (last 10 digits) or email of
an existing lead, or a customer with an existing name or GSTIN, returns 409
with `detail: {message, duplicates: [{id, label, detail}]}`; send
`allow_duplicate: true` to create it anyway. CSV import uses the same rules
(`domain/duplicates.py`).

**Conversion never merges by name.** `POST /api/leads/{id}/convert` takes
`customer_id` to add the contact to an existing customer, or creates a new
one. `GET /api/leads/{id}/customer-matches` lists the customers the lead
might already be — same name, or a contact with its phone or email — so the
user picks.

**Lead rotation.** `GET/PUT /api/crm/rotation` (`crm.settings.write` to
change) holds an ordered list of people who get new leads in turn. It
applies to leads created with `assign_by_rotation: true`, CSV rows with a
blank Owner, and web enquiries; deactivated members are skipped. The next
person is chosen under a row lock, so leads arriving together go to
different people. The web app edits it under CRM → Settings.

**Sales targets.** `GET /api/crm/targets?month=YYYY-MM` lists each person's
monthly target against the value of deals they moved to Won that month
(by `stage_changed_at`, UTC), plus a forecast (their open deals expected to
close that month × probability). `PUT` sets targets (`crm.settings.write`;
an amount of 0 removes one). Shown under CRM → Targets and, for your own
target, on the dashboard.

**Tags and custom fields.** Leads, deals and customers carry `tags`
(lower-cased, trimmed, de-duplicated, at most 20 of 40 characters) and
`custom` values. Lists filter with `?tag=`; `GET /api/crm/tags?record_type=`
counts the tags in use. Custom fields are defined per company and record
type (`GET/POST /api/crm/fields`, `PATCH /api/crm/fields/{id}`;
`crm.settings.write` to change): text, number, date, dropdown (`select`,
with choices) or yes/no (`checkbox`). Values are validated against their
field; sending `null` or `""` clears one, and an update changes only the keys
sent. A field's key and type never change; archiving hides it from forms but
keeps saved values. Changes show in record history under the field's name.
CSV import reads a Tags column (separated by `,`, `;` or `|`).

**Attachments.** `GET /api/attachments?record_type=&record_id=`,
`POST /api/attachments` (multipart: `record_type`, `record_id`, `file`),
`GET /api/attachments/{id}/download` and `DELETE /api/attachments/{id}` put
files on leads, opportunities and customers. Reading needs the record's read
permission, adding or removing its write permission. Files are stored under
`ATTACHMENTS_DIR` (default `var/attachments`, one folder per tenant), at most
`ATTACHMENT_MAX_MB` (default 10) each and 50 per record; programs and scripts
are refused. Downloads are always served as attachments with `nosniff` and a
sandbox CSP, never rendered inline. Adding or removing a file on a lead or
deal shows in its history.

**Web enquiry form.** `GET/PUT /api/crm/web-form` and
`POST /api/crm/web-form/new-key` (`crm.settings.write`) switch on a public
form at `/api/public/enquiry/<secret key>`: a hosted page to link to or
embed in an iframe, and the same URL takes a JSON `POST` (`name`, `company`,
`phone`, `email`, `message`) from a site's own form. It needs no login and
only `/api/public/*` is open to any origin (`core/public_cors.py`); the rest
of the API keeps its CORS allow-list. Guards: the key must match an enabled
form (a new key kills the old link), a hidden honeypot field silently drops
bots, submissions are rate-limited per IP and per form (in-process), and
bodies are capped at 20 KB. An enquiry from a known phone or email is added
to that lead as a note (reopening it if Lost) instead of creating a
duplicate; new leads get the configured source and go to the lead rotation
when it's on. History shows these as "Web form".

**Record history.** Creating, editing, re-staging, reassigning or
converting a lead or deal, logging or completing a follow-up, and raising a
quotation each write a `crm_events` row in the same transaction: who, when,
what changed (`{field: [old, new]}`) and where (`app`, `ask_erp` or
`import`). `GET /api/leads/{id}/timeline` and
`GET /api/opportunities/{id}/timeline` return it newest first; a deal's
timeline includes the lead it came from (and vice versa) when the caller
can read both.

Leads and opportunities come back with their owner's name and open/overdue
follow-up counts; opportunities also carry their linked quotations, the
`stage_changed_at` date (the won/lost date once closed), and idle-deal fields
(`last_touch_at`, `idle_days`, `is_stale`). A deal is stale when nothing —
stage change, follow-up or quotation — has touched it for longer than its
stage allows. Each company sets those limits (`/api/crm/settings`, 0 turns a
stage's warning off); the defaults are New 7, Qualified 10, Proposal 14,
Negotiation 7 days (`STALE_AFTER_DAYS` in `domain/crm_service.py`). Moving a deal to Lost requires a
`lost_reason`; reopening it clears the reason. Customers take an optional
`gstin`, validated (format, state code and check character) and upper-cased. An
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
