"""Alembic environment: migrates the database named by app settings."""

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — populates Base.metadata for autogenerate
from app.core.config import settings
from app.core.database import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Bookkeeping table of the old dev bootstrap; not part of the model.
    return not (type_ == "table" and name == "dev_upgrades")


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      include_object=include_object, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # handed in by app.core.migrations
        _run(connection)
        return
    engine = engine_from_config({"sqlalchemy.url": settings.database_url}, prefix="sqlalchemy.",
                                poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
