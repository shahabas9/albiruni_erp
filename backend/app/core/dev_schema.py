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
            "users": {"active": "BOOLEAN NOT NULL DEFAULT TRUE"},
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
            "customers": {"gstin": "VARCHAR(15) NOT NULL DEFAULT ''"},
            "activities": {
                "notes": "TEXT NOT NULL DEFAULT ''",
                "due_date": "DATE", "due_at": "TIMESTAMPTZ",
                "done": "BOOLEAN NOT NULL DEFAULT FALSE", "completed_at": "TIMESTAMPTZ",
                "customer_id": "UUID REFERENCES customers(id)",
                "created_by": "UUID REFERENCES users(id)",
                "owner_id": "UUID REFERENCES users(id)",
            },
            "quotations": {"opportunity_id": "UUID REFERENCES opportunities(id)"},
        }
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
