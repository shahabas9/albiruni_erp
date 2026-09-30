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
| "how am I doing against target", "is the team on track" | `crm.target_progress.v1` | L1 Read |
| "show VIP leads in Kannur", "deals tagged export", "customers tagged distributor", "any deals in negotiation" | `crm.find_leads.v1` / `crm.find_deals.v1` / `crm.find_customers.v1` | L1 Read |

"Show …" questions match the tags in use, the choices of dropdown custom
fields (e.g. City = Kannur), and stage or status words; "my" limits to your
own records. Answers follow record visibility like every other read.

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

**Customer page.** `GET /api/customers/{id}/overview` (open pipeline, won,
lost, contacts, quotations) and `GET /api/customers/{id}/timeline` (the
customer's history plus its deals' and source leads') back the web app's
customer page at `/customers/:id`, which also lists the customer's deals
(`/api/opportunities?customer_id=`), quotations
(`/api/sales/quotations?customer_id=`), contacts, account follow-ups and
files. Deal figures and history only include deals the caller may see.
Customer create/edit (including tags and custom fields) is now recorded in
history.

**Export.** `GET /api/exports/{leads|opportunities|customers|contacts|activities}.csv`
takes the same filters as the lists and applies the same record visibility;
it needs `crm.export` (seeded for Sales Manager, not granted to existing
roles) plus read permission on that list. Every export runs as the audited
tool `crm.export_records.v1`, so the AI audit trail records who exported
what, with which filters and how many rows. Files are UTF-8 with a BOM for
Excel, include tags and one column per custom field, and cells that a
spreadsheet would run as a formula are prefixed with `'`. At most 50,000
rows per export.

**Bulk actions.** `POST /api/leads/bulk`, `/api/opportunities/bulk` and
`/api/customers/bulk` take an `action`, a `value`, and either `ids` (up to
500) or `filters` (everything matching the list's filters, up to 2,000).
Leads: `assign`, `add_tag`, `remove_tag`, `status`, `delete`; deals:
`assign`, `add_tag`, `remove_tag`, `stage` (Lost needs `lost_reason`),
`delete`; customers: `add_tag`, `remove_tag`, `activate`, `deactivate`,
`delete`. Each needs the permission its single edit needs, and each record
goes through the same service call (rules, visibility, history); refused
records are skipped and listed with the reason. A bulk reassignment sends
the new owner one summary notification.

**Saved views.** `GET /api/views?page=`, `POST /api/views`,
`PATCH`/`DELETE /api/views/{id}` store named filter sets for the leads,
opportunities, customers, contacts and activities lists — private, or shared
with the company. Only the owner can change a view; the owner or a CRM admin
(`crm.settings.write`) can delete it. Views hold filters only, so record
visibility still applies to whoever opens one. The web app also remembers
each list's last filters in the browser; filters in a link take precedence.

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

## Sales cycle

Quotation → sales order → delivery → tax invoice → payment, with Indian GST
worked out the same way on every document (`app/domain/tax.py`, pure
functions with their own unit tests).

### GST

- **Prices exclude GST.** A document's discount comes off each line first,
  then tax is added per line and rounded to the paisa; the grand total is
  rounded to the rupee and the difference shown as round-off.
- **CGST + SGST or IGST** depends on the place of supply: the customer's GST
  state against the company's. A registered customer's state is the first two
  digits of their GSTIN and can't be set to anything else; an unregistered
  customer's state is picked by hand. A customer with no state is treated as
  a sale within your own state (over the counter), with a warning.
- **Company & GST** (`GET/PUT /api/sales/company`, needs `sales.settings.write`
  to change): legal name, GSTIN, state, address, bank details, invoice terms,
  default payment terms and whether deliveries may take stock below zero.
  `GET /api/sales/states` lists GST state codes.
- **Items** carry `kind` (goods move stock, services don't), an HSN/SAC code
  (4, 6 or 8 digits) and `gst_rate` (0, 0.25, 3, 5, 12, 18, 28 or 40). A
  quotation for an item with no rate warns and adds no tax for it.
- Quotations keep `total` as the value after discount and before GST (what the
  CRM counts as the deal's worth) and add `cgst`, `sgst`, `igst`, `round_off`
  and `grand_total`. Quotations made before GST existed keep a grand total
  equal to their old total.

### Quotations and sales orders

- A quotation moves Draft → Sent → Accepted, or to Rejected (with a reason,
  and it can be reopened). One over the discount limit starts as Pending
  approval; `POST /api/sales/quotations/{id}/approve` needs
  `sales.quotation.approve`. Other actions: `/send`, `/accept`, `/reject`,
  `/reopen`.
- `POST /api/sales/quotations/{id}/order` turns a quotation into a draft
  sales order with its lines, prices and discount (the quotation becomes
  Accepted; a quotation feeds one live order at a time). Orders can also be
  made directly (`POST /api/sales/orders`) and edited while they're drafts.
- Order numbers are `SO/26-27/00001`: per tenant, restarting each Indian
  financial year (April–March). The counter row is locked until commit, so
  numbers are never shared or skipped.
- Every order line needs an item with a GST rate — an order becomes an
  invoice. Prices, tax, names and addresses are copied onto the order, so
  later edits to an item or customer don't change it.
- **Confirming** (`/confirm`, audited tool `sales.confirm_order.v1`) locks
  the order. A discount over 2% or a price below list needs someone with
  `sales.quotation.approve` (an approved quotation carries its approval
  over). Going over the customer's credit limit — counting what confirmed
  orders will still bill — needs `sales.credit.override`. The linked CRM deal
  is marked Won.
- **Cancelling** (`/cancel`, audited, needs a reason) works only while
  nothing has been delivered or invoiced.
- Permissions: `sales.order.read`, `sales.order.write`,
  `sales.credit.override`. Roles that could create quotations get the order
  permissions once, on upgrade.

### Deliveries and stock

- **Stock is a ledger.** Every change is a `stock_movements` row (Opening,
  Delivery, Delivery cancelled, Adjustment, Return) with the balance after
  it; an item's `stock_qty` is their running total. `GET /api/items/{id}/stock`
  lists them. Items that had stock before the ledger get one Opening row on
  upgrade.
- **Stock counts** (`POST /api/items/{id}/adjust`, `inventory.stock.adjust`)
  set stock to a counted quantity with a reason. Changing `stock_qty` on the
  item form needs the same permission and is recorded the same way; new
  items' stock is their opening balance.
- **Delivery notes** (`POST /api/sales/orders/{id}/deliveries`, audited tool
  `sales.create_delivery.v1`, needs `sales.delivery.write`) deliver some or
  all of what's left on a confirmed order's goods lines, numbered
  `DN/26-27/00001`. They take the goods out of stock — refused if that would
  go below zero, unless Company & GST allows negative stock — and move the
  order to Partly delivered or Delivered. Services are never delivered, only
  invoiced.
- The order row, then the item rows in id order, are locked for the whole
  delivery, so two deliveries of the last few boxes can't both succeed.
- **Cancelling a delivery** (`/api/sales/deliveries/{id}/cancel`, audited,
  needs a reason) puts the stock back and reopens the order's quantities.

### Tax invoices

- `POST /api/sales/orders/{id}/invoices` makes a **draft** from a confirmed
  order: by default what's been delivered and not yet invoiced (before any
  delivery, everything not invoiced; services, everything not invoiced), or
  the quantities you pass. A draft has no number and can be deleted.
- **Issuing** (`/api/sales/invoices/{id}/issue`, audited tool
  `sales.issue_invoice.v1`, needs `sales.invoice.write`) numbers it
  `INV/26-27/00001` (at most 16 characters, restarting each financial
  year), copies the seller's and buyer's details onto it as they are that
  day, and locks it. It's refused until Company & GST has a legal name,
  GSTIN, state and address; for a future date; for a date before the last
  invoice issued this year (numbers must follow dates); and if another
  invoice has meanwhile taken the quantities (two drafts can't bill the same
  goods).
- Every issued invoice carries `amount_in_words`, an `hsn_summary`, `balance`
  (total − paid − credited) and a `payment_status`: Unpaid, Partly paid, Paid
  or Overdue (past due with something owed). `GET /api/sales/invoices` filters
  by `status` = Draft, Issued, unpaid, overdue or paid.
- The web app prints invoices at `/print/invoice/{id}` and delivery challans
  at `/print/delivery/{id}` (the browser's Print / Save as PDF). A4, black on
  white whatever the theme.
- Not included: e-invoicing (IRN and signed QR from the GST portal) and
  e-way bills. Both need a GST Suvidha Provider account; add them as tools
  that call the provider when a company is above the e-invoicing threshold.

### Credit notes

- `POST /api/sales/invoices/{id}/credit-notes` (audited tool
  `sales.create_credit_note.v1`, needs `sales.credit_note.write`) takes back
  part of an issued invoice, numbered `CN/26-27/00001` and issued at once:
  - **Return**: quantities come back at the invoice line's own net price and
    GST rate, and optionally go back into stock (a Return stock movement).
  - **Price correction**: an amount of taxable value off a line, with its GST;
    no stock moves.
- A line can't be credited beyond what's left of its quantity or value, and
  the last credit that clears an invoice matches its total exactly. The
  invoice's `amount_credited` rises, so the customer owes less; an invoice
  cleared by credit notes alone shows as Credited.
- Credit notes are refused after 30 November following the end of the
  invoice's financial year (the GST time limit), before the invoice date, or
  against a draft. They print at `/print/credit-note/{id}`, citing the
  original invoice's number and date.
- `sales.credit_note.write` is granted on upgrade to roles that can both
  approve discounts and write invoices.

### Payments received

- `POST /api/sales/payments` (audited tool `sales.record_payment.v1`, needs
  `sales.payment.write`) records a receipt, numbered `RCT/26-27/00001`, and
  applies it to the customer's issued invoices — oldest due first unless you
  pass `allocations` (`[]` keeps it all as an advance). Whatever isn't
  applied stays on the receipt as an **advance**;
  `/api/sales/payments/{id}/allocate` applies it to later invoices.
- Checks: an allocation can't exceed an invoice's balance or belong to
  another customer; no future dates; cheque, UPI and bank transfers need a
  reference; **cash of ₹2,00,000 or more is refused** (Income Tax Act,
  section 269ST).
- **Voiding** (`/void`, needs a reason — a bounced cheque) takes the receipt's
  allocations back off its invoices, so they're owed again.
- Invoices are locked in id order while allocations change, so two receipts
  can't both pay the last rupee of an invoice.
- The credit-limit check on confirming an order now counts unpaid invoices
  (less advances) as well as what confirmed orders will still bill.
- Receipts print at `/print/receipt/{id}`.

### Receivables

- `GET /api/sales/receivables` (needs `sales.invoice.read`): per customer,
  what's owed split by days past the due date — not yet due, 1–30, 31–60,
  61–90, 90+ — plus advances held and the net. Most overdue first; customers
  owing nothing and holding no advance are left out. `as_of` ages at another
  date.
- `GET /api/sales/receivables/{customer_id}/statement?date_from&date_to`
  (default: this financial year to date): the balance brought forward, then
  invoices (debit), credit notes and payments (credit) with a running
  balance. Voided payments are left out. Printable at
  `/print/statement/{customer_id}?from=&to=`.
- The customer page's overview adds an `account` block (owed, overdue,
  advance, net, open invoices, oldest due) for people with
  `sales.invoice.read`.

### Sales reports

- `GET /api/sales/reports/register?date_from&date_to` — issued invoices and
  credit notes (as negatives) in the period, with totals.
- `GET /api/sales/reports/gstr1?date_from&date_to` — GSTR-1 figures by
  section: **b2b** (registered buyers, per invoice and rate), **b2cl**
  (unregistered, other state, invoice over ₹1,00,000), **b2cs** (other
  unregistered sales totalled by place of supply and rate, their credit notes
  netted in), **cdnr** / **cdnur** (credit notes), **hsn** (split B2B/B2C,
  with UQC unit codes) and **docs** (number ranges used).
- `GET /api/sales/reports/{register|b2b|b2cl|b2cs|cdnr|cdnur|hsn|docs}.csv` —
  the same as CSV in the GST portal's column order, with a BOM for Excel and
  formula-injection protection. Every download goes through the audited
  tool `sales.export_report.v1`. Needs `sales.reports.read`.
- These are figures to file from, not a filing: an accountant should check
  them (and the GST portal's own validation) before uploading.
