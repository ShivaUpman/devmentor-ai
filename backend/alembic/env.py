"""
alembic/env.py — Alembic migration environment

WHY is this file so important?
  Alembic needs to know:
    1. WHERE your database is (connection string)
    2. WHAT your schema looks like (your ORM models)

  Without importing your models here, Alembic can't detect
  changes and won't generate migrations automatically.

  The most common beginner mistake: forgetting to import a new model here,
  then wondering why Alembic doesn't create the table.

WHY Alembic over raw SQL?
  Imagine you're on a team of 5 engineers. Each of you changes the schema
  locally. Without migrations, there's no way to know which changes have
  been applied to production and which haven't. Alembic gives each change
  a unique hash (like a git commit) and tracks what's been applied.

Interview question: "How do you handle database schema changes in production?"
Answer: Migrations (Alembic, Flyway, Liquibase). Each migration is:
  - Versioned with a unique ID
  - Committed to git alongside the code that needs it
  - Applied via CI/CD before the new code deploys
  - Reversible (downgrade() function)
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── Add the app to the Python path ─────────────────────────────────────────────
# WHY? Alembic runs from the backend/ directory but needs to import app.models.
# Without this, "from app.models.user import User" fails with ModuleNotFoundError.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Import your models ─────────────────────────────────────────────────────────
# CRITICAL: every model module must be imported here.
# Alembic reads Base.metadata to know what tables exist.
# If a model isn't imported → Alembic doesn't know about it → no migration generated.
from app.db.session import Base  # noqa: E402
from app.models import user, session, submission  # noqa: E402, F401

# ── Alembic config ─────────────────────────────────────────────────────────────
config = context.config

# Read logging config from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell Alembic which metadata to compare against
target_metadata = Base.metadata

# ── Override DB URL from environment ───────────────────────────────────────────
# WHY? alembic.ini has a hardcoded sqlalchemy.url placeholder.
# In real deployments, the URL comes from an env var — not a committed file.
# This override reads the env var and uses it instead.
database_url = os.environ.get(
    "SYNC_DATABASE_URL",
    "postgresql://devmentor:devmentor@localhost:5432/devmentor",
)
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL script without a live DB connection.
    Useful for: reviewing what will change before applying,
    or applying to a DB you can't connect to directly (e.g., RDS in prod).
    Run: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Detect column type changes
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Online mode: apply migrations to a live database connection.
    Run: alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No connection pooling for migrations
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,       # Detect: String(100) → String(255)
            compare_server_default=True,  # Detect server_default changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
