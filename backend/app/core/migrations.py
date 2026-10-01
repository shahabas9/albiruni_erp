"""Bringing a database up to date: Alembic migrations, with a one-time
hand-over for databases created before migrations existed.

- Empty database: every migration runs from 0001 (the baseline).
- Database with app tables but no alembic_version (made by the old dev
  bootstrap): the frozen legacy upgrade (dev_schema.ensure_dev_schema) brings
  it to the baseline, it's stamped 0001, then later migrations run.
- Otherwise: `alembic upgrade head`.

In production, run `alembic upgrade head` as a deploy step (AUTO_MIGRATE=0
turns off the startup run).
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine

BASELINE = "0001"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _config(connection) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    config.attributes["connection"] = connection
    return config


def upgrade_database() -> None:
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
    if "tenants" in tables and "alembic_version" not in tables:
        from app.core.dev_schema import ensure_dev_schema

        ensure_dev_schema()
        with engine.begin() as conn:
            command.stamp(_config(conn), BASELINE)
    with engine.begin() as conn:
        command.upgrade(_config(conn), "head")
