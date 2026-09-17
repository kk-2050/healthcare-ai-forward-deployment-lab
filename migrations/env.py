# File Name: env.py
# Purpose: Bridges Alembic to this project's existing SQLAlchemy metadata and secure database configuration.
# Creation Date: 2026-09-17
# Author: K.Kashiwagi

from logging.config import fileConfig

from dotenv import load_dotenv

from alembic import context

# =====================================================================
# PROJECT METADATA
# Purpose:
# Points Alembic at this project's existing SQLAlchemy declarative
# Base (src/db/base.py), the same Base every ORM table already
# registers against (src/db/models.py).
#
# Why:
# Task 19E establishes migration infrastructure only -- it does not
# invent a second, parallel schema description. target_metadata is
# Alembic's reference for what the code currently expects the schema
# to look like; it is used later for autogenerate comparisons, not by
# this task.
#
# Important Notes:
# - Importing src.db.models (even though nothing here calls it
#   directly) is required so WorkflowRunORM/AuditEventORM register
#   themselves onto Base.metadata before Alembic reads it -- the same
#   reason the Task 18B scripts and create_database_schema() import
#   src.db.models.
# =====================================================================
from src.db.base import Base  # noqa: E402
from src.db.models import AuditEventORM, WorkflowRunORM  # noqa: E402,F401

target_metadata = Base.metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# =====================================================================
# OFFLINE MODE
# Purpose:
# Alembic's "offline" mode emits raw SQL to stdout instead of
# connecting to a database (invoked with `alembic upgrade --sql`).
#
# Important Notes:
# - This project does not use offline/`--sql` mode. alembic.ini
#   intentionally leaves `sqlalchemy.url` unset (see alembic.ini),
#   so `config.get_main_option("sqlalchemy.url")` returns None here.
#   If offline mode is ever invoked, this will fail with a clear
#   configuration error rather than silently doing nothing -- that is
#   intentional; a real need for offline SQL generation should be a
#   deliberate future decision, not an accidental default.
# =====================================================================
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# =====================================================================
# ONLINE MODE
# Purpose:
# Builds the real SQL Server engine through this project's existing,
# approved configuration path -- never a second, parallel one.
#
# Why:
# The generated Alembic template normally builds its engine from the
# `sqlalchemy.url` value in alembic.ini. This project deliberately
# never puts a connection string there (see alembic.ini and
# docs/security.md). Instead this function reuses exactly the same
# path already used everywhere else in the project:
# load_database_settings() (src/config/database.py) reads
# SQL_SERVER_CONNECTION_STRING from the environment into a validated,
# SecretStr-wrapped DatabaseSettings object, and
# create_sql_server_engine() (src/db/engine.py) is the one place that
# ever reads the secret value back out to build the engine.
#
# Important Notes:
# - load_dotenv() here mirrors the same explicit "caller loads .env"
#   pattern already used by the Task 18B scripts and required by
#   src.config.database's own docstring -- this module never assumes
#   .env is already loaded into the process environment.
# - This function is only ever reached by Alembic commands that need
#   a live database connection (e.g. `upgrade`, `downgrade`,
#   `current`, `stamp`, `revision --autogenerate`). Task 19E does not
#   run any of those commands.
# =====================================================================
def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    load_dotenv()

    from src.config.database import load_database_settings
    from src.db.engine import create_sql_server_engine

    settings = load_database_settings()
    connectable = create_sql_server_engine(settings)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
