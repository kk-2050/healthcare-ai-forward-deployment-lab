# File Name: database.py
# Purpose: Defines and loads the validated Microsoft SQL Server connection configuration.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr

# =====================================================================
# DATABASE SETTINGS
# Purpose:
# Defines the one value this project needs to connect to Microsoft SQL
# Server: a raw ODBC connection string. Rejects a missing or blank
# value before any code tries to use it.
#
# Why:
# Keeping this a single opaque, injected string (rather than separate
# server/database/username/password fields) means this project never
# hard-codes a server name, database name, driver, or credential
# anywhere in source -- the operator's own ODBC connection string
# already carries whatever shape their environment needs (see
# src/db/engine.py for how it is used).
#
# Important Notes:
# - connection_string is a Pydantic SecretStr, so it is masked in
#   repr()/str() and only ever read back out with
#   `.get_secret_value()` -- and that should happen in exactly one
#   place: src/db/engine.py, when building the SQLAlchemy engine.
# - This class does not read environment variables itself; see
#   load_database_settings() below for that.
# =====================================================================


class DatabaseSettings(BaseModel):
    """Validated Microsoft SQL Server connection configuration."""

    model_config = ConfigDict(extra="forbid")

    connection_string: SecretStr = Field(min_length=1)


# =====================================================================
# ENVIRONMENT LOADER
# Purpose:
# Reads SQL_SERVER_CONNECTION_STRING from an environment-like mapping
# and validates it into DatabaseSettings.
#
# Why no automatic .env loading:
# Same policy as load_azure_openai_settings() (src/config/settings.py):
# this function reads from plain environment variables (or an injected
# mapping in tests) and never calls a .env-loading library itself, so
# it behaves the same in a local shell, CI/CD, a container, or a future
# secret manager. Loading a local .env file remains the caller's
# explicit responsibility.
#
# Important Notes:
# - Only SQL_SERVER_CONNECTION_STRING is read.
# - This function never creates a .env file and never prints the value
#   it reads.
# =====================================================================
def load_database_settings(
    env: Mapping[str, str] | None = None,
) -> DatabaseSettings:
    """
    Loads and validates database settings from an environment-like
    source.

    If `env` is not supplied, reads from the real process environment
    (os.environ). Tests should always supply an explicit `env` mapping
    instead, so tests stay isolated and repeatable.

    Raises a Pydantic ValidationError if the connection string is
    missing or blank.
    """
    source = os.environ if env is None else env

    return DatabaseSettings(
        connection_string=source.get("SQL_SERVER_CONNECTION_STRING", ""),
    )
