# File Name: test_reference_data_loader.py
# Purpose: Tests the stable Phase 1 reference/configuration loader using isolated SQLite test storage.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect src/db/reference_data.py: idempotent insert,
# conflict detection/rollback, and the complete 8-step workflow
# definition. Ten of the twelve tables this loader writes have no
# SQLAlchemy ORM class (see src/db/models.py's Foreign Key Policy) --
# only raw Alembic DDL against real SQL Server. To test the loader's
# raw-SQL logic offline, this file creates minimal SQLite-only tables
# mirroring the real Wave 1 columns (generic types, not
# mssql.NVARCHAR/DATETIME2 -- the same reason a SQLite migration dry
# run is not applicable for the actual Alembic revisions, see Task 21B/
# 22's SQLite dialect-incompatibility notes). This is a TEST DOUBLE
# only; real SQL Server compatibility is confirmed separately, only
# when the loader is actually run against a live database.

import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Python 3.12+ deprecated sqlite3's default datetime adapter (used
# implicitly whenever a raw datetime.datetime is bound as a query
# parameter). This is a SQLite-test-fixture-only concern -- real SQL
# Server via pyodbc has no such adapter and is unaffected -- so the
# fix is registered only here, not in src/db/reference_data.py, per
# the official replacement recipe from the sqlite3 docs.
sqlite3.register_adapter(datetime, lambda value: value.isoformat())

from src.db.base import Base, create_database_schema
from src.db.reference_data import (
    ReferenceDataConflictError,
    load_reference_data,
    resolve_step_code_to_workflow_step_id,
    workflow_definition_id,
)

# Mirrors the real Wave 1 migration's column names/order exactly (see
# migrations/versions/c841e86a8516_create_wave_1_database_foundation.py) --
# only the SQL types are generic/SQLite-compatible, since
# src/db/reference_data.py's raw sa.text() statements reference columns
# by name, not by type.
_SQLITE_REFERENCE_TABLE_DDL = {
    "reasons": """
        CREATE TABLE reasons (
            reason_code TEXT PRIMARY KEY, reason_type_code TEXT NOT NULL,
            reason_name TEXT NOT NULL, description TEXT,
            requires_text INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "case_statuses": """
        CREATE TABLE case_statuses (
            case_status_code TEXT PRIMARY KEY, case_status_name TEXT NOT NULL,
            description TEXT, is_terminal INTEGER NOT NULL,
            sort_order INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "workflow_statuses": """
        CREATE TABLE workflow_statuses (
            workflow_status_code TEXT PRIMARY KEY, workflow_status_name TEXT NOT NULL,
            description TEXT, is_terminal INTEGER NOT NULL,
            requires_human_review INTEGER NOT NULL, sort_order INTEGER NOT NULL,
            is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "workflow_actions": """
        CREATE TABLE workflow_actions (
            workflow_action_code TEXT PRIMARY KEY, workflow_action_name TEXT NOT NULL,
            description TEXT, requires_human INTEGER NOT NULL,
            is_terminal INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "event_categories": """
        CREATE TABLE event_categories (
            event_category_code TEXT PRIMARY KEY, event_category_name TEXT NOT NULL,
            description TEXT, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "event_types": """
        CREATE TABLE event_types (
            event_type_code TEXT PRIMARY KEY, event_category_code TEXT NOT NULL,
            event_type_name TEXT NOT NULL, description TEXT,
            is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "actor_types": """
        CREATE TABLE actor_types (
            actor_type_code TEXT PRIMARY KEY, actor_type_name TEXT NOT NULL,
            description TEXT, is_human INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "source_components": """
        CREATE TABLE source_components (
            source_component_code TEXT PRIMARY KEY, component_name TEXT NOT NULL,
            component_type_code TEXT, description TEXT, version_label TEXT,
            is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "result_codes": """
        CREATE TABLE result_codes (
            result_code TEXT PRIMARY KEY, result_name TEXT NOT NULL,
            description TEXT, is_success INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "failure_categories": """
        CREATE TABLE failure_categories (
            failure_category_code TEXT PRIMARY KEY, failure_category_name TEXT NOT NULL,
            description TEXT, is_retryable INTEGER NOT NULL,
            requires_human_review_default INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
}


def make_session_factory():
    """Builds an in-memory SQLite engine with the full canonical
    Base.metadata (workflow_definitions/workflow_definition_steps, plus
    the other Wave 2 tables) AND the ten Wave-1-only reference tables
    that have no ORM class -- everything src/db/reference_data.py needs
    to run against, offline."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_schema(engine)
    with engine.begin() as connection:
        for ddl in _SQLITE_REFERENCE_TABLE_DDL.values():
            connection.execute(text(ddl))
    return sessionmaker(bind=engine)


# =====================================================================
# BASIC LOAD BEHAVIOR
# =====================================================================
def test_first_load_inserts_expected_rows():
    """Verify a first load against an empty database inserts rows into
    every stable table and reports nothing as already_present."""
    session = make_session_factory()()

    report = load_reference_data(session)

    assert report.inserted
    assert report.already_present == []
    assert any(entry.startswith("workflow_statuses:") for entry in report.inserted)
    assert any(entry.startswith("event_types:") for entry in report.inserted)
    assert any(
        entry.startswith("workflow_definition_steps:") for entry in report.inserted
    )


def test_second_load_is_idempotent():
    """Verify running the loader twice makes no changes the second
    time -- every row is reported already_present, nothing inserted."""
    session_factory = make_session_factory()
    load_reference_data(session_factory())

    second_report = load_reference_data(session_factory())

    assert second_report.inserted == []
    assert second_report.already_present


def test_matching_existing_row_is_accepted_without_error():
    """Verify a row that already exists and exactly matches its
    expected definition is accepted (no conflict), not silently
    skipped without verification."""
    session_factory = make_session_factory()
    first_report = load_reference_data(session_factory())

    second_report = load_reference_data(session_factory())

    assert set(first_report.inserted) == set(second_report.already_present)


# =====================================================================
# CONFLICT / ROLLBACK BEHAVIOR
# =====================================================================
def test_conflicting_existing_row_raises_and_does_not_overwrite():
    """Verify a pre-existing row whose semantic fields disagree with
    the expected Phase 1 definition raises ReferenceDataConflictError,
    and the conflicting row's data is left exactly as it was --
    never silently overwritten."""
    session_factory = make_session_factory()
    session = session_factory()
    now = datetime.now(timezone.utc)
    session.execute(
        text(
            "INSERT INTO workflow_statuses "
            "(workflow_status_code, workflow_status_name, description, "
            "is_terminal, requires_human_review, sort_order, is_active, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:code, :name, :description, :is_terminal, :requires_human_review, "
            ":sort_order, :is_active, :created_at_utc, :created_by, :updated_at_utc, "
            ":updated_by, :is_deleted)"
        ),
        {
            "code": "PROCESSING",
            "name": "WRONG NAME - CONFLICTING DEFINITION",
            "description": "conflicting",
            "is_terminal": 1,  # canonical definition says 0 (not terminal)
            "requires_human_review": 0,
            "sort_order": 999,
            "is_active": 1,
            "created_at_utc": now,
            "created_by": "SYNTHETIC-CONFLICT-TEST",
            "updated_at_utc": now,
            "updated_by": "SYNTHETIC-CONFLICT-TEST",
            "is_deleted": 0,
        },
    )
    session.commit()

    with pytest.raises(ReferenceDataConflictError):
        load_reference_data(session_factory())

    # The conflicting row must be left exactly as it was -- never
    # overwritten by the failed load attempt.
    verify_session = session_factory()
    row = (
        verify_session.execute(
            text(
                "SELECT workflow_status_name FROM workflow_statuses "
                "WHERE workflow_status_code = 'PROCESSING'"
            )
        )
        .mappings()
        .first()
    )
    assert row["workflow_status_name"] == "WRONG NAME - CONFLICTING DEFINITION"


def test_conflict_rolls_back_the_whole_transaction():
    """Verify a conflict discovered partway through the load rolls back
    EVERY row from that call, not just the conflicting one -- e.g. a
    table processed before the conflicting one must not be left
    partially inserted."""
    session_factory = make_session_factory()
    session = session_factory()
    now = datetime.now(timezone.utc)
    # reasons is loaded before workflow_statuses (see _TABLE_ROWS
    # insertion order); seed a conflict in workflow_statuses so that if
    # rollback failed, reasons rows would remain committed even though
    # the overall load failed.
    session.execute(
        text(
            "INSERT INTO workflow_statuses "
            "(workflow_status_code, workflow_status_name, description, "
            "is_terminal, requires_human_review, sort_order, is_active, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES ('PROCESSING', 'WRONG', NULL, 1, 0, 999, 1, "
            ":now, 'X', :now, 'X', 0)"
        ),
        {"now": now},
    )
    session.commit()

    with pytest.raises(ReferenceDataConflictError):
        load_reference_data(session_factory())

    verify_session = session_factory()
    reasons_count = verify_session.execute(text("SELECT COUNT(*) FROM reasons")).scalar()
    assert reasons_count == 0


# =====================================================================
# COMPLETE WORKFLOW DEFINITION TESTS
# =====================================================================
def test_complete_workflow_definition_contains_every_approved_step():
    """Verify all 8 approved Phase 1 step_codes are loaded -- not just
    the 5 exercised by the AI-not-needed happy path."""
    session_factory = make_session_factory()
    session = session_factory()
    load_reference_data(session)

    step_codes = set(resolve_step_code_to_workflow_step_id(session).keys())

    assert step_codes == {
        "CASE_VALIDATION",
        "FHIR_RETRIEVAL",
        "EVIDENCE_CONSISTENCY",
        "COMPLETENESS_CHECK",
        "AI_ROUTING",
        "AI_ANALYSIS",
        "HUMAN_REVIEW",
        "COMPLETE",
    }


def test_workflow_step_ids_are_deterministic_not_random():
    """Verify workflow_step_id values are stable, human-readable
    prototype identifiers, not random UUIDs -- required for idempotent
    reloads without a separate lookup table."""
    session_factory = make_session_factory()
    first_mapping = resolve_step_code_to_workflow_step_id(
        _loaded_session(session_factory)
    )
    second_mapping = resolve_step_code_to_workflow_step_id(
        _loaded_session(session_factory)
    )

    assert first_mapping == second_mapping
    for step_id in first_mapping.values():
        assert step_id.startswith("wfstep_")
        assert len(step_id) <= 64


def _loaded_session(session_factory):
    session = session_factory()
    load_reference_data(session)
    return session


def test_workflow_definition_id_is_deterministic():
    """Verify workflow_definition_id() returns a stable, human-readable
    value, not a random UUID."""
    value = workflow_definition_id()

    assert value == "wfdef_prior_authorization_1_0"
    assert len(value) <= 64


# =====================================================================
# DATA-CLASS SEPARATION TESTS
# =====================================================================
def test_synthetic_client_and_case_are_not_part_of_stable_catalog():
    """Verify the loader never touches clients/prior_authorization_cases
    -- those are synthetic integration-test business fixture data, kept
    in a separate, explicitly distinct fixture, never in this loader."""
    import inspect

    import src.db.reference_data as reference_data_module

    source = inspect.getsource(reference_data_module)

    assert "INSERT INTO clients" not in source
    assert "prior_authorization_cases" not in source
    assert "DEMO_HEALTH" not in source


def test_loader_contains_no_secrets_or_phi_assumptions():
    """Verify the loader module never references a connection string,
    credential, or real-looking identifier -- only synthetic/prototype
    configuration values."""
    import inspect

    import src.db.reference_data as reference_data_module

    source = inspect.getsource(reference_data_module)

    forbidden_terms = ["password", "SQL_SERVER_CONNECTION_STRING", "api_key", "secret"]
    lowered = source.lower()
    for term in forbidden_terms:
        assert term.lower() not in lowered or term == "SQL_SERVER_CONNECTION_STRING"
    # The one legitimate mention of SQL_SERVER_CONNECTION_STRING is
    # indirect, via load_database_settings() -- confirm the raw
    # environment variable name itself is never duplicated here.
    assert "SQL_SERVER_CONNECTION_STRING" not in source
