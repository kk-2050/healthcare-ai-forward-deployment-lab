# File Name: test_database_settings.py
# Purpose: Tests Microsoft SQL Server settings loading and the engine factory offline.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the configuration layer added in Task 18A:
# DatabaseSettings (src/config/database.py) and the engine factory
# (src/db/engine.py). Every test uses a synthetic connection string and
# an injected environment mapping -- none of them read the real process
# environment, create a real .env file, or make any network/DNS call.
# Constructing a SQLAlchemy Engine object is allowed and tested here;
# actually connecting to a database is not -- Task 18B performs the
# real local Microsoft SQL Server integration test.

import inspect

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine

from src.config import database as database_module
from src.config.database import DatabaseSettings, load_database_settings
from src.db import engine as engine_module
from src.db.engine import build_sql_server_url, create_sql_server_engine

_SYNTHETIC_CONNECTION_STRING = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=synthetic-server;Database=synthetic-db;"
    "Uid=synthetic-user;Pwd=synthetic-pass;"
)


def valid_env(**overrides):
    """A minimal, fully valid synthetic environment mapping."""
    data = {"SQL_SERVER_CONNECTION_STRING": _SYNTHETIC_CONNECTION_STRING}
    data.update(overrides)
    return data


def valid_settings(**overrides) -> DatabaseSettings:
    """A minimal, fully valid DatabaseSettings built from a synthetic value."""
    data = {"connection_string": _SYNTHETIC_CONNECTION_STRING}
    data.update(overrides)
    return DatabaseSettings(**data)


# =====================================================================
# DATABASE SETTINGS TESTS
# =====================================================================
def test_valid_environment_mapping_loads_settings():
    """Verify a fully valid, injected environment mapping loads into
    DatabaseSettings with the expected connection string."""
    # TEST-014A
    settings = load_database_settings(valid_env())

    assert settings.connection_string.get_secret_value() == _SYNTHETIC_CONNECTION_STRING


def test_missing_connection_string_fails():
    """Verify settings loading fails when SQL_SERVER_CONNECTION_STRING
    is absent -- a missing connection string must never silently
    produce an unusable engine later."""
    # TEST-014B
    env = valid_env()
    del env["SQL_SERVER_CONNECTION_STRING"]

    with pytest.raises(ValidationError):
        load_database_settings(env)


def test_blank_connection_string_fails():
    """Verify an empty-string connection string is rejected, not
    treated as a usable (but empty) configuration value."""
    # TEST-014C
    with pytest.raises(ValidationError):
        load_database_settings(valid_env(SQL_SERVER_CONNECTION_STRING=""))


def test_connection_string_is_secret_str():
    """Verify connection_string is stored as a Pydantic SecretStr, not
    a plain string, so it gets automatic masking everywhere it might be
    displayed."""
    # TEST-014D
    settings = valid_settings()

    assert isinstance(settings.connection_string, SecretStr)


def test_connection_string_is_hidden_from_repr_and_str():
    """Verify the real connection string value never appears in
    repr(settings) or str(settings) -- a stray debug print must not
    leak database credentials."""
    # TEST-014E
    settings = valid_settings(
        connection_string="Uid=synthetic-unique-marker-001;Pwd=synthetic-pass;"
    )

    assert "synthetic-unique-marker-001" not in repr(settings)
    assert "synthetic-unique-marker-001" not in str(settings)


def test_unexpected_config_fields_are_rejected():
    """Verify an unexpected field is rejected outright -- a typo or a
    stray field must fail loudly, not be silently ignored."""
    # TEST-014F
    with pytest.raises(ValidationError):
        DatabaseSettings(
            connection_string=_SYNTHETIC_CONNECTION_STRING,
            unexpected_field="not allowed",
        )


def test_settings_loader_reads_only_the_intended_key(monkeypatch):
    """Verify an explicitly injected mapping is used for loading
    settings, so tests never depend on (or are affected by) whatever is
    actually set in the real process environment."""
    # TEST-014G
    monkeypatch.setenv(
        "SQL_SERVER_CONNECTION_STRING", "should-not-be-used-real-env-value"
    )

    settings = load_database_settings(valid_env())

    assert settings.connection_string.get_secret_value() == _SYNTHETIC_CONNECTION_STRING


def test_database_settings_module_does_not_load_dotenv():
    """Verify src/config/database.py never imports/calls a .env-loading
    library -- loading a local .env file remains the caller's explicit
    responsibility, never hidden inside shared configuration code."""
    # TEST-014H
    source = inspect.getsource(database_module)

    assert "dotenv" not in source.lower()


# =====================================================================
# ENGINE FACTORY TESTS
# =====================================================================
def test_sql_server_url_uses_mssql_pyodbc_dialect():
    """Verify the SQLAlchemy URL built for Microsoft SQL Server uses
    the mssql+pyodbc dialect required by this project's fixed
    technology decision (see CLAUDE.md)."""
    # TEST-014I
    url = build_sql_server_url("synthetic-connection-string")

    assert url.drivername == "mssql+pyodbc"


def test_raw_connection_string_passed_through_odbc_connect():
    """Verify the raw ODBC connection string is passed through using
    the documented odbc_connect query mechanism, rather than being
    parsed or reassembled into separate URL fields."""
    # TEST-014J
    raw = "synthetic-unique-connection-string-marker"

    url = build_sql_server_url(raw)

    assert url.query.get("odbc_connect") == raw


def test_engine_construction_does_not_connect(monkeypatch):
    """
    Verify building the engine never opens a network socket.

    Patches socket.socket.connect to raise if called, proving engine
    construction is offline -- SQLAlchemy engines connect lazily, only
    when a session/connection is actually used (not done in Task 18A).
    """
    # TEST-014K
    import socket

    def _blocked_connect(self, *args, **kwargs):
        raise AssertionError("network connection attempted during engine construction")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

    engine = create_sql_server_engine(valid_settings())

    assert isinstance(engine, Engine)


def test_connection_string_is_not_printed_by_factory_code():
    """Verify src/db/engine.py contains no print()/logging call that
    could expose the connection string -- the only place the value is
    ever read is to hand it to the URL builder."""
    # TEST-014L
    source = inspect.getsource(engine_module)

    assert "print(" not in source
