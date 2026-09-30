"""Dev-only schema bootstrap, including upgrades from either CRM prototype.

Production deployments should express these upgrades as Alembic migrations.
"""

from sqlalchemy import inspect, text

import app.models  # noqa: F401 — populates Base.metadata
from app.core.database import Base, engine


LEGACY_CRM_PERMISSIONS = {
    "crm.read": ["crm.lead.read", "crm.opportunity.read", "crm.contact.read", "crm.activity.read"],
    "crm.write": [
        "crm.lead.write", "crm.lead.convert", "crm.opportunity.write", "crm.contact.write", "crm.activity.write",
    ],
    "crm.assign": ["crm.lead.assign", "crm.opportunity.assign"],
}


def ensure_dev_schema() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        def columns(table: str) -> set[str]:
            return {column["name"] for column in inspect(conn).get_columns(table)}

        # The workspace API uses aliases; retain the local CRUD column names.
        aliases = {
            "leads": {"organization": "company_name", "owner_id": "owner_user_id"},
            "opportunities": {
                "title": "name", "expected_value": "value",
                "expected_close": "expected_close_date", "owner_id": "owner_user_id",
            },
            "activities": {"kind": "type"},
        }
        for table, names in aliases.items():
            existing = columns(table)
            for old, new in names.items():
                if old in existing and new not in existing:
                    conn.execute(text(f'ALTER TABLE {table} RENAME COLUMN {old} TO {new}'))

        additions = {
            "users": {
                "active": "BOOLEAN NOT NULL DEFAULT TRUE",
                "email": "VARCHAR(160) NOT NULL DEFAULT ''",
                "notify_email": "BOOLEAN NOT NULL DEFAULT TRUE",
            },
            "leads": {
                "notes": "TEXT NOT NULL DEFAULT ''",
                "converted_customer_id": "UUID REFERENCES customers(id)",
                "converted_opportunity_id": "UUID REFERENCES opportunities(id)",
            },
            "opportunities": {
                "notes": "TEXT NOT NULL DEFAULT ''",
                "probability_pct": "INTEGER NOT NULL DEFAULT 50",
                "lead_id": "UUID REFERENCES leads(id)",
                "lost_reason": "VARCHAR(200) NOT NULL DEFAULT ''",
                # No default here: existing rows must be backfilled from created_at, not "now".
                "stage_changed_at": "TIMESTAMPTZ",
            },
            "customers": {
                "gstin": "VARCHAR(15) NOT NULL DEFAULT ''",
                "billing_address": "TEXT NOT NULL DEFAULT ''",
                "shipping_address": "TEXT NOT NULL DEFAULT ''",
                "state_code": "VARCHAR(2) NOT NULL DEFAULT ''",
                "payment_terms_days": "INTEGER",
            },
            "companies": {
                "legal_name": "VARCHAR(160) NOT NULL DEFAULT ''",
                "gstin": "VARCHAR(15) NOT NULL DEFAULT ''",
                "state_code": "VARCHAR(2) NOT NULL DEFAULT ''",
                "address": "TEXT NOT NULL DEFAULT ''",
                "phone": "VARCHAR(40) NOT NULL DEFAULT ''",
                "email": "VARCHAR(160) NOT NULL DEFAULT ''",
                "bank_details": "TEXT NOT NULL DEFAULT ''",
                "invoice_terms": "TEXT NOT NULL DEFAULT ''",
                "payment_terms_days": "INTEGER NOT NULL DEFAULT 30",
                "allow_negative_stock": "BOOLEAN NOT NULL DEFAULT FALSE",
            },
            "items": {
                "kind": "VARCHAR(10) NOT NULL DEFAULT 'goods'",
                "hsn_code": "VARCHAR(8) NOT NULL DEFAULT ''",
                "gst_rate": "NUMERIC(5, 2)",
            },
            "invoice_lines": {"credited_value": "NUMERIC(14, 2) NOT NULL DEFAULT 0"},
            "quotation_lines": {
                "hsn_code": "VARCHAR(8) NOT NULL DEFAULT ''",
                "gst_rate": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
                "taxable_value": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
                "tax_amount": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
            },
            "activities": {
                "notes": "TEXT NOT NULL DEFAULT ''",
                "due_date": "DATE", "due_at": "TIMESTAMPTZ",
                "done": "BOOLEAN NOT NULL DEFAULT FALSE", "completed_at": "TIMESTAMPTZ",
                "customer_id": "UUID REFERENCES customers(id)",
                "created_by": "UUID REFERENCES users(id)",
                "owner_id": "UUID REFERENCES users(id)",
                "overdue_notified_at": "TIMESTAMPTZ",
            },
            "quotations": {
                "opportunity_id": "UUID REFERENCES opportunities(id)",
                "place_of_supply": "VARCHAR(2) NOT NULL DEFAULT ''",
                "cgst": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
                "sgst": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
                "igst": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
                "round_off": "NUMERIC(6, 2) NOT NULL DEFAULT 0",
                "grand_total": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
                "status_note": "VARCHAR(200) NOT NULL DEFAULT ''",
                "approved_by": "UUID REFERENCES users(id)",
            },
            "crm_settings": {
                "lead_rotation": "JSONB NOT NULL DEFAULT '{}'::jsonb",
                "web_form": "JSONB NOT NULL DEFAULT '{}'::jsonb",
            },
        }
        for table in ("leads", "opportunities", "customers"):
            additions.setdefault(table, {}).update(
                {"tags": "VARCHAR(40)[] NOT NULL DEFAULT '{}'", "custom": "JSONB NOT NULL DEFAULT '{}'::jsonb"}
            )
        before_activity = columns("activities")
        for table, definitions in additions.items():
            existing = columns(table)
            for name, definition in definitions.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))

        # Existing notes/tasks may have no due date; existing remote activities
        # have no recorded creator. Neither case should require fabricated data.
        conn.execute(text("ALTER TABLE activities ALTER COLUMN due_at DROP NOT NULL"))
        conn.execute(text("ALTER TABLE activities ALTER COLUMN created_by DROP NOT NULL"))
        conn.execute(text("ALTER TABLE opportunities ALTER COLUMN name TYPE VARCHAR(200)"))
        if "due_at" not in before_activity:
            conn.execute(text("UPDATE activities SET due_at = due_date::timestamp AT TIME ZONE 'UTC'"))
        if "due_date" not in before_activity:
            conn.execute(text("UPDATE activities SET due_date = (due_at AT TIME ZONE 'UTC')::date"))
        if "done" not in before_activity:
            conn.execute(text("UPDATE activities SET done = completed_at IS NOT NULL"))
        if "completed_at" not in before_activity:
            conn.execute(text("UPDATE activities SET completed_at = created_at WHERE done"))

        # Tag filters use array containment; GIN keeps them fast.
        for table in ("leads", "opportunities", "customers"):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_tags ON {table} USING gin (tags)"))

        # Quotation numbers are unique per tenant, not across the database.
        conn.execute(text("ALTER TABLE quotations DROP CONSTRAINT IF EXISTS quotations_number_key"))
        has_tenant_unique = conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_quotations_tenant_number'"
        )).first()
        if not has_tenant_unique:
            conn.execute(text(
                "ALTER TABLE quotations ADD CONSTRAINT uq_quotations_tenant_number UNIQUE (tenant_id, number)"
            ))

        # Deals that predate stage tracking: the best known stage date is creation.
        conn.execute(text("UPDATE opportunities SET stage_changed_at = created_at WHERE stage_changed_at IS NULL"))
        conn.execute(text("ALTER TABLE opportunities ALTER COLUMN stage_changed_at SET DEFAULT now()"))
        conn.execute(text("UPDATE opportunities SET stage = 'New' WHERE stage = 'Prospecting'"))
        conn.execute(text("UPDATE opportunities SET stage = 'Qualified' WHERE stage = 'Qualification'"))
        conn.execute(text("UPDATE leads SET status = 'Lost' WHERE status = 'Disqualified'"))
        conn.execute(text("""
            UPDATE leads SET converted_customer_id = opportunities.customer_id
            FROM opportunities WHERE leads.converted_opportunity_id = opportunities.id
            AND leads.converted_customer_id IS NULL
        """))

        # One CRM permission set: expand the retired coarse crm.read / crm.write /
        # crm.assign grants into their per-record equivalents, then drop them.
        for coarse, fine in LEGACY_CRM_PERMISSIONS.items():
            conn.execute(
                text("""
                    UPDATE roles SET permissions = ARRAY(
                        SELECT DISTINCT p FROM unnest(array_remove(permissions, :coarse) || CAST(:fine AS VARCHAR[])) AS p
                    )
                    WHERE :coarse = ANY(permissions)
                """),
                {"coarse": coarse, "fine": fine},
            )

        # One-off upgrades: each runs once per database, so an admin's later
        # change (e.g. taking "see all" away from a role) is never undone.
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS dev_upgrades (name VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
        ))

        def once(name: str) -> bool:
            return conn.execute(
                text("INSERT INTO dev_upgrades (name) VALUES (:n) ON CONFLICT DO NOTHING RETURNING name"), {"n": name}
            ).first() is not None

        if once("overdue-alerts-start-now"):
            # Don't alert everyone about follow-ups that went overdue before
            # notifications existed; only new ones from here on.
            conn.execute(text(
                "UPDATE activities SET overdue_notified_at = now() WHERE NOT done AND due_at < now()"
            ))

        if once("grant-crm-records-all"):
            # Record visibility arrived with crm.records.all; roles that could
            # read leads or deals before keep seeing everyone's.
            conn.execute(text("""
                UPDATE roles SET permissions = array_append(permissions, 'crm.records.all')
                WHERE ('crm.lead.read' = ANY(permissions) OR 'crm.opportunity.read' = ANY(permissions))
                  AND NOT 'crm.records.all' = ANY(permissions)
            """))

        if once("quotations-without-gst"):
            # Quotations from before GST was worked out carried no tax: what
            # the customer was quoted is the pre-tax total.
            conn.execute(text("UPDATE quotations SET grand_total = total WHERE grand_total = 0"))
            conn.execute(text("UPDATE quotation_lines SET taxable_value = line_total WHERE taxable_value = 0"))
        if once("customer-state-from-gstin"):
            conn.execute(text("UPDATE customers SET state_code = left(gstin, 2) WHERE gstin <> '' AND state_code = ''"))
        if once("grant-sales-orders"):
            # Sales orders arrived with their own permissions; whoever could
            # raise quotations can take orders.
            conn.execute(text("""
                UPDATE roles SET permissions = permissions || ARRAY['sales.order.read', 'sales.order.write']::VARCHAR[]
                WHERE 'sales.quotation.create' = ANY(permissions) AND NOT 'sales.order.write' = ANY(permissions)
            """))
        if once("opening-stock-movements"):
            # Stock from before the stock ledger becomes each item's opening balance.
            conn.execute(text("""
                INSERT INTO stock_movements (id, tenant_id, company_id, item_id, kind, qty, balance_after,
                                             ref_type, ref_number, note, created_at)
                SELECT gen_random_uuid(), tenant_id, company_id, id, 'Opening', stock_qty, stock_qty,
                       '', '', 'Stock before the ledger started', now()
                FROM items WHERE stock_qty <> 0 AND kind = 'goods'
                  AND NOT EXISTS (SELECT 1 FROM stock_movements m WHERE m.item_id = items.id)
            """))
        if once("grant-stock-adjust"):
            conn.execute(text("""
                UPDATE roles SET permissions = array_append(permissions, 'inventory.stock.adjust')
                WHERE 'inventory.item.write' = ANY(permissions) AND NOT 'inventory.stock.adjust' = ANY(permissions)
            """))
            conn.execute(text("""
                UPDATE roles SET permissions = array_append(permissions, 'sales.delivery.write')
                WHERE 'sales.order.write' = ANY(permissions) AND NOT 'sales.delivery.write' = ANY(permissions)
            """))
        if once("grant-invoices"):
            conn.execute(text("""
                UPDATE roles SET permissions = permissions || ARRAY['sales.invoice.read', 'sales.invoice.write']::VARCHAR[]
                WHERE 'sales.order.write' = ANY(permissions) AND NOT 'sales.invoice.write' = ANY(permissions)
            """))
        if once("grant-credit-notes"):
            conn.execute(text("""
                UPDATE roles SET permissions = array_append(permissions, 'sales.credit_note.write')
                WHERE 'sales.quotation.approve' = ANY(permissions) AND 'sales.invoice.write' = ANY(permissions)
                  AND NOT 'sales.credit_note.write' = ANY(permissions)
            """))
        if once("grant-payments"):
            conn.execute(text("""
                UPDATE roles SET permissions = permissions || ARRAY['sales.payment.read', 'sales.payment.write']::VARCHAR[]
                WHERE 'sales.invoice.write' = ANY(permissions) AND NOT 'sales.payment.write' = ANY(permissions)
            """))
