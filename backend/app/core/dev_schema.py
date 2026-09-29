"""Dev-only schema bootstrap. A real deployment manages schema via Alembic
migrations, never this."""

from sqlalchemy import text

import app.models  # noqa: F401 — populates Base.metadata
from app.core.database import Base, engine


def ensure_dev_schema() -> None:
    Base.metadata.create_all(bind=engine)
    # create_all() never alters an existing table, so a dev DB created before
    # the CRM module lacks this column.
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS opportunity_id UUID REFERENCES opportunities(id)")
        )
