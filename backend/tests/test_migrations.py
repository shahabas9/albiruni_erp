"""Migrations build exactly the schema the models describe.

Needs an empty disposable database of its own (it is dropped back to nothing):
  MIGRATION_TEST_DB=postgresql+psycopg://USER:PASS@localhost/EMPTY_DB \\
    .venv/bin/python -m unittest tests.test_migrations -v
"""
import os
import unittest

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.core.database import Base
from app.core.migrations import _config

URL = os.environ.get("MIGRATION_TEST_DB")


@unittest.skipUnless(URL, "requires an empty disposable PostgreSQL database (MIGRATION_TEST_DB)")
class MigrationTests(unittest.TestCase):
    def test_upgrade_matches_the_models_and_downgrade_undoes_it(self):
        engine = create_engine(URL)
        with engine.begin() as conn:
            command.upgrade(_config(conn), "head")
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        self.assertEqual(diffs, [])
        with engine.begin() as conn:
            command.downgrade(_config(conn), "base")
        with engine.connect() as conn:
            self.assertEqual(set(inspect(conn).get_table_names()) - {"alembic_version"}, set())
