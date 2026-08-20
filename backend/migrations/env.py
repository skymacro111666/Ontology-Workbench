"""Alembic migration environment; database URL injected from OW_DB_URL."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ontoworkbench.db.models import Base

# The Alembic Config object, providing access to values within the .ini file.
config = context.config

# Interpret the config file for Python logging unless suppressed.
if config.config_file_name is not None and not config.attributes.get("no_logger", False):
    fileConfig(config.config_file_name)

# Runtime URL injection: OW_DB_URL wins; a local sqlite file is the fallback
# so offline SQL generation (`alembic upgrade --sql`) works without setup.
db_url = os.getenv("OW_DB_URL", "")
if not db_url:
    db_url = "sqlite:///./ow.db"
config.set_main_option("sqlalchemy.url", db_url)

# Model metadata for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
