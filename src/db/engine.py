# File Name: engine.py
# Purpose: Builds a SQLAlchemy engine for Microsoft SQL Server from a raw ODBC connection string, without connecting.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from src.config.database import DatabaseSettings

# =====================================================================
# SQL SERVER URL CONSTRUCTION
# Purpose:
# Turns an already-configured raw ODBC connection string into a
# SQLAlchemy URL for the mssql+pyodbc dialect.
#
# Why:
# SQLAlchemy's documented way to use an existing ODBC connection string
# (rather than reassembling one from separate server/database/username/
# password fields) is the `odbc_connect` query parameter. Using it here
# means this project never parses, stores, or reconstructs individual
# credential parts -- the operator's connection string is passed
# through exactly as configured.
#
# Important Notes:
# This function only builds a URL object; it performs no network
# activity and does not validate that the string is a working
# connection string.
# =====================================================================
def build_sql_server_url(raw_connection_string: str) -> URL:
    """
    Builds a SQLAlchemy URL for the mssql+pyodbc dialect from a raw
    ODBC connection string.
    """
    return URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": raw_connection_string},
    )


# =====================================================================
# ENGINE FACTORY
# Purpose:
# Builds a SQLAlchemy Engine for Microsoft SQL Server from validated
# DatabaseSettings.
#
# Why:
# This is the one place the connection string is ever read out of its
# SecretStr wrapper. Keeping that in a single, small function makes it
# easy to confirm the value is never logged, printed, or otherwise
# exposed anywhere else in the project.
#
# Important Notes:
# - Constructing the engine performs NO network connection and NO
#   validation against a real server -- SQLAlchemy engines connect
#   lazily, only when a session/connection is actually used (not done
#   anywhere in Task 18A).
# - SQL echo is always left at its default (disabled); this factory
#   never sets echo=True, so raw SQL statements and bound parameters
#   are never printed to logs.
# - This function never reads os.environ directly; all configuration
#   comes from the DatabaseSettings object it is given.
# - Callers should treat the returned engine as an opaque handle and
#   avoid printing it in a way that could expose the connection string
#   (e.g. via engine.url).
# =====================================================================
def create_sql_server_engine(settings: DatabaseSettings) -> Engine:
    """
    Creates a SQLAlchemy Engine configured for Microsoft SQL Server.

    Performs no network connection. The real connection string is read
    from settings.connection_string (a SecretStr) only here.
    """
    url = build_sql_server_url(settings.connection_string.get_secret_value())

    return create_engine(url)
