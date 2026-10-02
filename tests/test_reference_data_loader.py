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
    # Task 23 (migrations/versions/f2fb22e3a41e_create_human_review_persistence_tables.py).
    # The real migration's control-column set is the full nine standard
    # fields; this test double intentionally mirrors only the five that
    # _load_raw_table() actually reads/writes, exactly like every other
    # table above -- not an oversight, see src/db/reference_data.py's
    # TABLE ACCESS STRATEGY note.
    "human_review_statuses": """
        CREATE TABLE human_review_statuses (
            review_status_code TEXT PRIMARY KEY, review_status_name TEXT NOT NULL,
            description TEXT, is_terminal INTEGER NOT NULL, is_active INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
            is_deleted INTEGER NOT NULL
        )
    """,
    "human_review_outcomes": """
        CREATE TABLE human_review_outcomes (
            review_outcome_code TEXT PRIMARY KEY, review_outcome_name TEXT NOT NULL,
            description TEXT, returns_to_workflow INTEGER NOT NULL,
            closes_case INTEGER NOT NULL, is_active INTEGER NOT NULL,
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
    assert any(
        entry.startswith("human_review_statuses:") for entry in report.inserted
    )
    assert any(
        entry.startswith("human_review_outcomes:") for entry in report.inserted
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
    """Verify all 9 approved Phase 1 step_codes are loaded -- not just
    the 5 exercised by the AI-not-needed happy path (Step 23C-5C added
    REQUEST_MISSING_INFORMATION, the 9th)."""
    session_factory = make_session_factory()
    session = session_factory()
    load_reference_data(session)

    step_codes = set(resolve_step_code_to_workflow_step_id(session).keys())

    assert step_codes == {
        "CASE_VALIDATION",
        "FHIR_RETRIEVAL",
        "EVIDENCE_CONSISTENCY",
        "COMPLETENESS_CHECK",
        "REQUEST_MISSING_INFORMATION",
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
# TASK 23 CANONICAL CATALOG TESTS
# =====================================================================
def test_task_23_catalog_semantics_are_exact():
    """Verify the approved Task 23 canonical additions -- PENDING_RESUME,
    HUMAN_REVIEW_SERVICE, HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION,
    and the human_review_statuses/human_review_outcomes rows -- are
    loaded with their exact approved flags, not merely present."""
    session_factory = make_session_factory()
    session = session_factory()
    load_reference_data(session)

    pending_resume = (
        session.execute(
            text(
                "SELECT is_terminal, requires_human_review, sort_order "
                "FROM workflow_statuses WHERE workflow_status_code = 'PENDING_RESUME'"
            )
        )
        .mappings()
        .first()
    )
    assert pending_resume is not None
    assert bool(pending_resume["is_terminal"]) is False
    assert bool(pending_resume["requires_human_review"]) is False
    assert pending_resume["sort_order"] == 25

    human_review_service = (
        session.execute(
            text(
                "SELECT source_component_code FROM source_components "
                "WHERE source_component_code = 'HUMAN_REVIEW_SERVICE'"
            )
        )
        .mappings()
        .first()
    )
    assert human_review_service is not None

    unresolved_missing_info = (
        session.execute(
            text(
                "SELECT reason_type_code FROM reasons "
                "WHERE reason_code = 'HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION'"
            )
        )
        .mappings()
        .first()
    )
    assert unresolved_missing_info is not None
    assert unresolved_missing_info["reason_type_code"] == "HUMAN_REVIEW"

    status_terminality = {
        row["review_status_code"]: bool(row["is_terminal"])
        for row in session.execute(
            text("SELECT review_status_code, is_terminal FROM human_review_statuses")
        ).mappings()
    }
    assert status_terminality == {
        "REQUESTED": False,
        "IN_PROGRESS": False,
        "COMPLETED": True,
        "CANCELLED": True,
    }

    outcome_flags = {
        row["review_outcome_code"]: (
            bool(row["returns_to_workflow"]),
            bool(row["closes_case"]),
        )
        for row in session.execute(
            text(
                "SELECT review_outcome_code, returns_to_workflow, closes_case "
                "FROM human_review_outcomes"
            )
        ).mappings()
    }
    assert outcome_flags == {
        "CONTINUE_WORKFLOW": (True, False),
        "REQUEST_MORE_INFORMATION": (False, False),
        "ESCALATE": (False, False),
        "CLOSE_CASE": (False, True),
    }


def test_workflow_resumed_now_loaded_and_persistence_error_still_not_loaded():
    """Verify WORKFLOW_RESUMED (Step 24B-4A -- added for same-run/
    same-trace resume continuation) IS now present in the loader's
    catalog data, with the correct category, and that PERSISTENCE_ERROR
    (documented-only, still not needed by any implemented code path)
    remains absent -- checked against the real data structures, not
    source text, so an unrelated comment or docstring mention can never
    cause a false pass/failure."""
    import src.db.reference_data as reference_data_module

    event_type_rows = {
        row["event_type_code"]: row
        for row in reference_data_module._TABLE_ROWS["event_types"]
    }
    failure_category_codes = {
        row["failure_category_code"]
        for row in reference_data_module._TABLE_ROWS["failure_categories"]
    }

    assert "WORKFLOW_RESUMED" in event_type_rows
    assert event_type_rows["WORKFLOW_RESUMED"]["event_category_code"] == "WORKFLOW"
    assert "PERSISTENCE_ERROR" not in failure_category_codes


# =====================================================================
# CASE_CLOSE REASON DOMAIN (Step 23C-2C1)
# Purpose:
# Verifies the six approved CASE_CLOSE_* reason rows are correctly
# defined in the loader and load offline exactly as documented in
# docs/database/reference_data.md Section 16 -- OFFLINE ONLY. These
# rows have NOT been loaded into the real SQL Server database by this
# step; that remains a separate, later, explicitly-approved step.
# =====================================================================
_EXPECTED_CASE_CLOSE_ROWS = {
    "CASE_CLOSE_COMPLETED": "Normal case processing completed",
    "CASE_CLOSE_REQUEST_WITHDRAWN": "Request withdrawn",
    "CASE_CLOSE_DUPLICATE": "Duplicate case closed",
    "CASE_CLOSE_SUPERSEDED": "Superseded by another case",
    "CASE_CLOSE_ADMINISTRATIVE": "Administrative close",
    "CASE_CLOSE_OTHER": "Other; explanatory text required",
}


def test_all_six_case_close_rows_present_in_loader_definition():
    """Verify all six approved CASE_CLOSE_* codes -- and only those six
    -- exist in the loader's reasons definition, checked against the
    actual data structure, not source text."""
    import src.db.reference_data as reference_data_module

    case_close_codes = {
        row["reason_code"]
        for row in reference_data_module._TABLE_ROWS["reasons"]
        if row["reason_type_code"] == "CASE_CLOSE"
    }

    assert case_close_codes == set(_EXPECTED_CASE_CLOSE_ROWS.keys())


def test_case_close_row_semantics_match_documentation():
    """Verify each CASE_CLOSE_* row's reason_type_code/description
    exactly match docs/database/reference_data.md Section 16, and that
    CASE_CLOSE_OTHER is the only one with requires_text=True."""
    import src.db.reference_data as reference_data_module

    rows_by_code = {
        row["reason_code"]: row
        for row in reference_data_module._TABLE_ROWS["reasons"]
        if row["reason_type_code"] == "CASE_CLOSE"
    }

    for code, expected_description in _EXPECTED_CASE_CLOSE_ROWS.items():
        row = rows_by_code[code]
        assert row["reason_type_code"] == "CASE_CLOSE"
        assert row["description"] == expected_description
        assert row["is_active"] is True
        expected_requires_text = code == "CASE_CLOSE_OTHER"
        assert row["requires_text"] is expected_requires_text


def test_reasons_count_becomes_14():
    """Verify the reasons table's loader definition now contains
    exactly 14 rows: the original 7 (EVIDENCE_MISMATCH x3 +
    HUMAN_REVIEW x4), the Task 23B HUMAN_REVIEW_UNRESOLVED_MISSING_
    INFORMATION addition, and the six new CASE_CLOSE_* rows."""
    import src.db.reference_data as reference_data_module

    assert len(reference_data_module._TABLE_ROWS["reasons"]) == 14


def test_total_canonical_row_count_becomes_97_offline():
    """Verify the loader's complete offline catalog (all raw tables +
    workflow_definitions + workflow_definition_steps) now totals 97
    rows -- the 96 from Step 23C-5C plus the one new WORKFLOW_RESUMED
    event_types row (Step 24B-4A)."""
    import src.db.reference_data as reference_data_module

    raw_table_total = sum(
        len(rows) for rows in reference_data_module._TABLE_ROWS.values()
    )
    total = (
        raw_table_total
        + 1  # workflow_definitions
        + len(reference_data_module._WORKFLOW_DEFINITION_STEPS)
    )
    assert total == 97


def test_event_types_becomes_16():
    """Verify event_types grew from 15 to 16 with exactly one new
    WORKFLOW_RESUMED row, category WORKFLOW (Step 24B-4A)."""
    import src.db.reference_data as reference_data_module

    event_types = reference_data_module._TABLE_ROWS["event_types"]
    assert len(event_types) == 16

    by_code = {row["event_type_code"]: row for row in event_types}
    assert by_code["WORKFLOW_RESUMED"]["event_category_code"] == "WORKFLOW"


def test_workflow_definition_steps_becomes_9():
    """Verify workflow_definition_steps grew from 8 to 9 with exactly
    one new REQUEST_MISSING_INFORMATION row, and no existing step was
    renumbered or rewritten (Step 23C-5C)."""
    import src.db.reference_data as reference_data_module

    steps = reference_data_module._WORKFLOW_DEFINITION_STEPS
    assert len(steps) == 9

    by_code = {step["step_code"]: step for step in steps}
    assert by_code["REQUEST_MISSING_INFORMATION"]["step_order"] == 45
    assert by_code["REQUEST_MISSING_INFORMATION"]["is_optional"] is True

    # Every pre-existing step's step_order is exactly what it was before
    # this step's insertion -- proving no renumbering occurred.
    assert by_code["CASE_VALIDATION"]["step_order"] == 10
    assert by_code["FHIR_RETRIEVAL"]["step_order"] == 20
    assert by_code["EVIDENCE_CONSISTENCY"]["step_order"] == 30
    assert by_code["COMPLETENESS_CHECK"]["step_order"] == 40
    assert by_code["AI_ROUTING"]["step_order"] == 50
    assert by_code["AI_ANALYSIS"]["step_order"] == 60
    assert by_code["HUMAN_REVIEW"]["step_order"] == 70
    assert by_code["COMPLETE"]["step_order"] == 80


def test_loaded_table_count_remains_14():
    """Verify no new table was introduced -- CASE_CLOSE rows extend the
    existing reasons table only."""
    import src.db.reference_data as reference_data_module

    # 10 raw tables + human_review_statuses + human_review_outcomes
    # (Step 23B) + workflow_definitions + workflow_definition_steps.
    assert len(reference_data_module._TABLE_ROWS) == 12
    total_tables = len(reference_data_module._TABLE_ROWS) + 2
    assert total_tables == 14


def test_first_offline_load_inserts_full_catalog_including_case_close():
    """Verify a first load against an empty database inserts all six
    CASE_CLOSE_* rows along with everything else."""
    session = make_session_factory()()

    report = load_reference_data(session)

    inserted_case_close = {
        entry.split(":", 1)[1]
        for entry in report.inserted
        if entry.startswith("reasons:") and "CASE_CLOSE" in entry
    }
    assert inserted_case_close == set(_EXPECTED_CASE_CLOSE_ROWS.keys())


def test_first_offline_load_inserts_new_missing_information_step_exactly_once():
    """Verify a first load inserts the new REQUEST_MISSING_INFORMATION
    workflow_definition_steps row exactly once, alongside the existing 8
    (Step 23C-5C)."""
    session = make_session_factory()()

    report = load_reference_data(session)

    inserted_steps = [
        entry
        for entry in report.inserted
        if entry.startswith("workflow_definition_steps:")
    ]
    assert len(inserted_steps) == 9


def test_first_offline_load_inserts_workflow_resumed_exactly_once():
    """Verify a first load inserts the new WORKFLOW_RESUMED event_types
    row exactly once (Step 24B-4A)."""
    session = make_session_factory()()

    report = load_reference_data(session)

    inserted_workflow_resumed = [
        entry for entry in report.inserted if entry == "event_types:WORKFLOW_RESUMED"
    ]
    assert len(inserted_workflow_resumed) == 1


def test_second_offline_load_is_idempotent_at_97_rows():
    """Verify a repeat load against the same database inserts nothing
    and reports all 97 rows as already_present."""
    session_factory = make_session_factory()
    load_reference_data(session_factory())

    second_report = load_reference_data(session_factory())

    assert second_report.inserted == []
    assert len(second_report.already_present) == 97


def test_case_close_semantic_conflict_raises_and_rolls_back():
    """Verify a pre-existing CASE_CLOSE_OTHER row whose semantic fields
    disagree with the expected definition raises
    ReferenceDataConflictError and rolls back the whole load -- never a
    silent overwrite, and unrelated rows (e.g. reasons already loaded
    before CASE_CLOSE in table order) are not left partially inserted."""
    session_factory = make_session_factory()
    session = session_factory()
    now = datetime.now(timezone.utc)
    session.execute(
        text(
            "INSERT INTO reasons "
            "(reason_code, reason_type_code, reason_name, description, "
            "requires_text, is_active, created_at_utc, created_by, "
            "updated_at_utc, updated_by, is_deleted) "
            "VALUES ('CASE_CLOSE_OTHER', 'CASE_CLOSE', 'WRONG NAME', "
            "'wrong description', 0, 1, :now, 'X', :now, 'X', 0)"
        ),
        {"now": now},
    )
    session.commit()

    with pytest.raises(ReferenceDataConflictError):
        load_reference_data(session_factory())

    verify_session = session_factory()
    # No unrelated reference-data values changed: workflow_statuses
    # (loaded before reasons in table order) must remain empty since
    # the whole transaction rolled back.
    workflow_statuses_count = verify_session.execute(
        text("SELECT COUNT(*) FROM workflow_statuses")
    ).scalar()
    assert workflow_statuses_count == 0

    row = (
        verify_session.execute(
            text(
                "SELECT reason_name FROM reasons WHERE reason_code = 'CASE_CLOSE_OTHER'"
            )
        )
        .mappings()
        .first()
    )
    assert row["reason_name"] == "WRONG NAME"  # left exactly as it was


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
