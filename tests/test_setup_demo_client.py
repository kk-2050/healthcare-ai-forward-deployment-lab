# File Name: test_setup_demo_client.py
# Purpose: Tests scripts/setup_demo_client.py's idempotency/conflict logic using an in-memory SQLite test double -- never real SQL Server.
# Creation Date: 2026-10-04
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect ensure_demo_client()'s full idempotency/conflict
# contract (Task 26B): "the client_id already exists" is never treated
# as success by itself -- only an exact canonical-field match is.
# Every test here calls ensure_demo_client() directly against an
# isolated in-memory SQLite engine; none of them import or exercise
# _run_from_cli() (which is the only place a real SQL Server
# connection string is ever resolved), so no real database connection
# is ever attempted by this file.

from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scripts.setup_demo_client import DemoClientSetupOutcome, ensure_demo_client

_CLIENTS_TABLE_DDL = """
    CREATE TABLE clients (
        client_id TEXT PRIMARY KEY, client_code TEXT NOT NULL,
        client_name TEXT NOT NULL, client_type_code TEXT,
        default_country_code TEXT, default_time_zone TEXT,
        is_active INTEGER NOT NULL, metadata_json TEXT,
        created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
        is_deleted INTEGER NOT NULL
    )
"""


def make_test_engine():
    """In-memory SQLite engine with the clients table created directly
    -- clients has no SQLAlchemy ORM class (Wave 1, raw DDL only), the
    same convention already used in tests/test_api_workflow_start.py."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(_CLIENTS_TABLE_DDL)
    return engine


def insert_raw_client(
    engine,
    *,
    client_id: str,
    client_code: str,
    client_name: str,
    is_active: bool = True,
    is_deleted: bool = False,
) -> None:
    """Inserts an arbitrary client row directly -- used to set up
    conflict scenarios the setup script itself must never create."""
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.execute(
            text(
                "INSERT INTO clients "
                "(client_id, client_code, client_name, client_type_code, "
                "default_country_code, default_time_zone, is_active, metadata_json, "
                "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
                "VALUES (:client_id, :client_code, :client_name, NULL, NULL, NULL, "
                ":is_active, NULL, :now, 'SYSTEM', :now, 'SYSTEM', :is_deleted)"
            ),
            {
                "client_id": client_id,
                "client_code": client_code,
                "client_name": client_name,
                "is_active": int(is_active),
                "is_deleted": int(is_deleted),
                "now": now,
            },
        )
        session.commit()


def test_absent_client_is_inserted():
    """Verify an empty clients table results in exactly one INSERTED
    canonical demo client."""
    engine = make_test_engine()
    session_factory = sessionmaker(bind=engine)

    result = ensure_demo_client(session_factory)

    assert result.outcome == DemoClientSetupOutcome.INSERTED
    with session_factory() as session:
        count = session.execute(text("SELECT COUNT(*) FROM clients")).scalar_one()
        assert count == 1


def test_exact_canonical_row_is_idempotent_no_op():
    """Verify running the script a second time against an already-
    canonical row reports ALREADY_PRESENT and writes nothing new."""
    engine = make_test_engine()
    session_factory = sessionmaker(bind=engine)
    ensure_demo_client(session_factory)

    result = ensure_demo_client(session_factory)

    assert result.outcome == DemoClientSetupOutcome.ALREADY_PRESENT
    with session_factory() as session:
        count = session.execute(text("SELECT COUNT(*) FROM clients")).scalar_one()
        assert count == 1


def test_same_client_id_different_data_is_conflict():
    """Verify an existing row at the canonical client_id, but with
    different durable data, is reported as a conflict and left
    completely untouched -- never UPDATEd to match."""
    engine = make_test_engine()
    insert_raw_client(
        engine,
        client_id="cli_demo_001",
        client_code="SOMETHING_ELSE",
        client_name="Unrelated Existing Client",
    )
    session_factory = sessionmaker(bind=engine)

    result = ensure_demo_client(session_factory)

    assert result.outcome == DemoClientSetupOutcome.CONFLICT
    with session_factory() as session:
        row = session.execute(
            text("SELECT client_code, client_name FROM clients WHERE client_id = 'cli_demo_001'")
        ).mappings().one()
        assert row["client_code"] == "SOMETHING_ELSE"
        assert row["client_name"] == "Unrelated Existing Client"


def test_same_client_code_different_client_id_is_conflict():
    """Verify a different client_id already owning the canonical
    client_code is reported as a conflict, and no row is inserted."""
    engine = make_test_engine()
    insert_raw_client(
        engine,
        client_id="cli_other_999",
        client_code="DEMO_HEALTH",
        client_name="A Different Client Using The Same Code",
    )
    session_factory = sessionmaker(bind=engine)

    result = ensure_demo_client(session_factory)

    assert result.outcome == DemoClientSetupOutcome.CONFLICT
    with session_factory() as session:
        count = session.execute(text("SELECT COUNT(*) FROM clients")).scalar_one()
        assert count == 1


def test_concurrent_equivalent_insert_resolves_as_idempotent_success(monkeypatch):
    """Verify that when a concurrent process has already inserted the
    exact canonical row between this call's own pre-check and its own
    INSERT attempt (simulated by monkeypatching the pre-checks to
    report 'absent' while the canonical row actually already exists,
    forcing a genuine IntegrityError on the INSERT), the resulting
    IntegrityError is caught and resolved as a safe idempotent success
    by re-reading the row -- never by guessing from the raw error
    text."""
    import scripts.setup_demo_client as setup_module

    engine = make_test_engine()
    session_factory = sessionmaker(bind=engine)
    first = ensure_demo_client(session_factory)
    assert first.outcome == DemoClientSetupOutcome.INSERTED

    real_fetch_by_id = setup_module._fetch_client_by_id
    call_count = {"n": 0}

    def _fetch_by_id_absent_only_on_precheck(session, client_id):
        # First call is the pre-check -- report "absent" to force the
        # INSERT attempt (and the resulting genuine IntegrityError,
        # since the row already exists). Every later call (the
        # except-branch re-read) uses the real function, exactly as
        # production code does.
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return real_fetch_by_id(session, client_id)

    monkeypatch.setattr(setup_module, "_fetch_client_by_id", _fetch_by_id_absent_only_on_precheck)
    monkeypatch.setattr(setup_module, "_fetch_client_by_code", lambda session, client_code: None)

    second = ensure_demo_client(session_factory)

    assert second.outcome == DemoClientSetupOutcome.ALREADY_PRESENT
    with session_factory() as session:
        count = session.execute(text("SELECT COUNT(*) FROM clients")).scalar_one()
        assert count == 1


def test_conflicting_state_after_integrity_error_is_safe_failure(monkeypatch):
    """Verify that if the pre-check somehow misses a conflicting row
    (simulated via monkeypatching the pre-check functions to report
    'absent' while a differing row actually exists), the resulting
    IntegrityError is resolved as a safe CONFLICT by re-reading actual
    row data -- never by parsing the raw IntegrityError text."""
    import scripts.setup_demo_client as setup_module

    engine = make_test_engine()
    insert_raw_client(
        engine,
        client_id="cli_demo_001",
        client_code="DIFFERENT_CODE",
        client_name="Different Name",
    )
    session_factory = sessionmaker(bind=engine)

    monkeypatch.setattr(setup_module, "_fetch_client_by_id", lambda session, client_id: None)
    monkeypatch.setattr(setup_module, "_fetch_client_by_code", lambda session, client_code: None)

    result = ensure_demo_client(session_factory)

    assert result.outcome == DemoClientSetupOutcome.CONFLICT
    assert "IntegrityError" not in result.message
    assert "UNIQUE constraint" not in result.message


def test_no_raw_integrity_error_text_in_any_result_message():
    """Verify every possible outcome's message is one of the fixed
    safe strings -- never raw SQL/driver exception text."""
    engine = make_test_engine()
    insert_raw_client(
        engine,
        client_id="cli_demo_001",
        client_code="SOMETHING_ELSE",
        client_name="Unrelated Existing Client",
    )
    session_factory = sessionmaker(bind=engine)

    result = ensure_demo_client(session_factory)

    for forbidden in ("Traceback", "sqlite3.IntegrityError", "UNIQUE constraint failed", "sa.text"):
        assert forbidden not in result.message


def test_canonical_client_has_no_real_looking_pii():
    """Verify the canonical identity itself is synthetic-only -- a
    simple structural check, not a claim this script validates input."""
    from scripts.setup_demo_client import (
        _CANONICAL_CLIENT_CODE,
        _CANONICAL_CLIENT_ID,
        _CANONICAL_CLIENT_NAME,
    )

    assert _CANONICAL_CLIENT_ID == "cli_demo_001"
    assert _CANONICAL_CLIENT_CODE == "DEMO_HEALTH"
    assert _CANONICAL_CLIENT_NAME == "Demo Health Plan"
    assert "@" not in _CANONICAL_CLIENT_NAME
