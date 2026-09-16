# File Name: test_audit_repository.py
# Purpose: Tests the prototype schema creation and AuditRepository behavior using an in-memory SQLite test double.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the Task 18A persistence foundation: the ORM
# schema (src/db/base.py, src/db/models.py) and AuditRepository
# (src/db/repository.py). Every test runs against an in-memory SQLite
# engine -- a TEST DOUBLE only. SQLite is NOT the Phase 1
# production/prototype database; it is used here only to test
# repository behavior without requiring a live SQL Server connection.
# Task 18B performs the real local Microsoft SQL Server integration
# test.

import inspect
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db import repository as repository_module
from src.db.base import create_database_schema
from src.db.models import WorkflowRunORM
from src.db.repository import AuditRepository, PersistenceError
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot


def make_test_engine():
    """
    Builds an in-memory SQLite engine for offline repository tests.

    StaticPool keeps one shared connection alive for the whole engine,
    so the in-memory database persists across the multiple sessions a
    repository call opens. Without it, SQLite would otherwise hand out
    a fresh, empty in-memory database per connection, making the
    repository unusable across separate calls.
    """
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_repository(engine=None) -> AuditRepository:
    """Builds an AuditRepository backed by a freshly schema'd in-memory engine."""
    if engine is None:
        engine = make_test_engine()
    create_database_schema(engine)
    return AuditRepository(session_factory=sessionmaker(bind=engine))


def make_snapshot(**overrides) -> WorkflowRunSnapshot:
    """A minimal, fully valid synthetic WorkflowRunSnapshot."""
    data = {
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "workflow_status": "COMPLETE",
        "human_review_required": False,
        "failure_category": None,
        "created_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "updated_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return WorkflowRunSnapshot(**data)


def make_event(**overrides) -> AuditEvent:
    """A minimal, fully valid synthetic AuditEvent."""
    data = {
        "event_id": "SYN-EVENT-001",
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "event_type": "workflow_completed",
        "event_category": AuditEventCategory.WORKFLOW,
        "workflow_status": "COMPLETE",
        "processing_step": "workflow_completed",
        "failure_category": None,
        "occurred_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return AuditEvent(**data)


# =====================================================================
# SCHEMA TESTS
# =====================================================================
def test_schema_creates_workflow_runs_table():
    """Verify create_database_schema() creates the workflow_runs
    table -- the repository has nothing to read/write without it."""
    # TEST-014M
    engine = make_test_engine()
    create_database_schema(engine)

    assert "workflow_runs" in sa_inspect(engine).get_table_names()


def test_schema_creates_audit_events_table():
    """Verify create_database_schema() creates the audit_events
    table."""
    # TEST-014N
    engine = make_test_engine()
    create_database_schema(engine)

    assert "audit_events" in sa_inspect(engine).get_table_names()


# =====================================================================
# WORKFLOW RUN PERSISTENCE TESTS
# =====================================================================
def test_workflow_run_can_be_saved():
    """Verify a new workflow run snapshot can be saved without
    error."""
    # TEST-014O
    repository = make_repository()

    repository.save_workflow_run(make_snapshot())


def test_workflow_run_can_be_retrieved_by_trace_id():
    """Verify a saved workflow run can be retrieved by its trace_id,
    with every field intact."""
    # TEST-014P
    repository = make_repository()
    snapshot = make_snapshot()

    repository.save_workflow_run(snapshot)
    retrieved = repository.get_workflow_run("SYN-TRACE-001")

    assert retrieved is not None
    assert retrieved.trace_id == snapshot.trace_id
    assert retrieved.case_id == snapshot.case_id
    assert retrieved.workflow_status == snapshot.workflow_status
    assert retrieved.human_review_required == snapshot.human_review_required


def test_saving_same_trace_id_updates_instead_of_duplicating():
    """Verify saving a second snapshot for the same trace_id updates
    the existing row instead of creating a duplicate -- workflow_runs
    holds current state, one row per trace_id."""
    # TEST-014Q
    engine = make_test_engine()
    repository = make_repository(engine)

    repository.save_workflow_run(make_snapshot(workflow_status="PROCESSING"))
    repository.save_workflow_run(make_snapshot(workflow_status="COMPLETE"))

    retrieved = repository.get_workflow_run("SYN-TRACE-001")
    assert retrieved.workflow_status == "COMPLETE"

    with sessionmaker(bind=engine)() as session:
        row_count = session.query(WorkflowRunORM).count()
    assert row_count == 1


def test_missing_workflow_run_returns_none():
    """Verify retrieving a trace_id that was never saved returns None,
    not an exception or a fabricated result."""
    repository = make_repository()

    assert repository.get_workflow_run("SYN-TRACE-DOES-NOT-EXIST") is None


# =====================================================================
# AUDIT EVENT TESTS
# =====================================================================
def test_audit_event_can_be_appended():
    """Verify a single audit event can be appended without error."""
    # TEST-014R
    repository = make_repository()

    repository.append_audit_event(make_event())


def test_multiple_audit_events_are_retained():
    """Verify appending several audit events for the same trace_id
    retains all of them, not just the most recent one."""
    # TEST-014S
    repository = make_repository()

    repository.append_audit_event(make_event(event_id="SYN-EVENT-001"))
    repository.append_audit_event(make_event(event_id="SYN-EVENT-002"))
    repository.append_audit_event(make_event(event_id="SYN-EVENT-003"))

    events = repository.list_audit_events("SYN-TRACE-001")
    assert len(events) == 3


def test_audit_events_are_returned_in_chronological_order():
    """Verify list_audit_events() returns events ordered by
    occurred_at_utc, regardless of the order they were appended in."""
    # TEST-014T
    repository = make_repository()

    later = make_event(
        event_id="SYN-EVENT-LATER",
        occurred_at_utc=datetime(2026, 1, 15, 12, 5, 0, tzinfo=timezone.utc),
    )
    earlier = make_event(
        event_id="SYN-EVENT-EARLIER",
        occurred_at_utc=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )

    repository.append_audit_event(later)
    repository.append_audit_event(earlier)

    events = repository.list_audit_events("SYN-TRACE-001")
    assert [event.event_id for event in events] == [
        "SYN-EVENT-EARLIER",
        "SYN-EVENT-LATER",
    ]


def test_audit_events_are_isolated_by_trace_id():
    """Verify list_audit_events() for one trace_id never returns
    another trace's events."""
    # TEST-014U
    repository = make_repository()

    repository.append_audit_event(
        make_event(event_id="SYN-EVENT-A", trace_id="SYN-TRACE-A")
    )
    repository.append_audit_event(
        make_event(event_id="SYN-EVENT-B", trace_id="SYN-TRACE-B")
    )

    events_a = repository.list_audit_events("SYN-TRACE-A")
    assert [event.event_id for event in events_a] == ["SYN-EVENT-A"]


def test_duplicate_event_id_fails_deterministically():
    """Verify appending a second event with an already-used event_id
    fails with PersistenceError instead of silently overwriting the
    first event."""
    # TEST-014V
    repository = make_repository()

    repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))

    with pytest.raises(PersistenceError):
        repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))


# =====================================================================
# FAILURE / TRANSACTION TESTS
# =====================================================================
def test_failed_write_rolls_back_and_repository_still_usable():
    """Verify a failed write (duplicate event_id) rolls back cleanly,
    and the repository can still be used successfully afterward -- one
    failure must not corrupt the repository for later calls."""
    # TEST-014W
    repository = make_repository()
    repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))

    with pytest.raises(PersistenceError):
        repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))

    repository.append_audit_event(make_event(event_id="SYN-EVENT-AFTER-FAILURE"))
    events = repository.list_audit_events("SYN-TRACE-001")

    assert {event.event_id for event in events} == {
        "SYN-EVENT-DUP",
        "SYN-EVENT-AFTER-FAILURE",
    }


def test_repository_does_not_mutate_workflow_run_snapshot_input():
    """Verify saving a snapshot never modifies the caller's
    WorkflowRunSnapshot object."""
    # TEST-014X
    repository = make_repository()
    snapshot = make_snapshot()
    original_status = snapshot.workflow_status

    repository.save_workflow_run(snapshot)

    assert snapshot.workflow_status == original_status


def test_repository_does_not_mutate_audit_event_input():
    """Verify appending an event never modifies the caller's
    AuditEvent object."""
    # TEST-014Y
    repository = make_repository()
    event = make_event()
    original_event_type = event.event_type

    repository.append_audit_event(event)

    assert event.event_type == original_event_type


# =====================================================================
# SECURITY BOUNDARY TESTS
# =====================================================================
def test_audit_models_contain_no_raw_clinical_or_fhir_fields():
    """Verify neither persistence model exposes raw clinical text or
    FHIR payload fields -- the audit layer records workflow activity,
    not raw healthcare content."""
    # TEST-014Z
    forbidden_fields = {
        "clinical_notes",
        "fhir_payload",
        "ai_prompt",
        "ai_response",
        "patient_name",
        "date_of_birth",
        "address",
        "phone",
        "email",
        "member_id",
        "provider_id",
    }

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_audit_models_contain_no_secret_or_connection_fields():
    """Verify neither persistence model exposes an API key, secret, or
    connection-string field."""
    # TEST-014AA
    forbidden_fields = {"api_key", "connection_string", "password", "token"}

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_audit_models_contain_no_approval_denial_fields():
    """Verify neither persistence model exposes an approval, denial,
    or medical-necessity field -- the audit layer never makes or
    records a clinical decision."""
    # TEST-014AB
    forbidden_fields = {"approval", "denial", "medical_necessity"}

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_repository_uses_no_ai_dependency():
    """Verify src/db/repository.py imports nothing from src/ai/* and
    does not import an OpenAI/LLM library -- this repository is
    persistence-only and must never depend on AI."""
    # TEST-014AC
    import_lines = [
        line.strip()
        for line in inspect.getsource(repository_module).splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]

    assert not any("src.ai" in line for line in import_lines)
    assert not any("openai" in line.lower() for line in import_lines)


def test_repository_tests_require_no_live_sql_server(monkeypatch):
    """
    Verify these repository tests never attempt a real network
    connection -- SQLite in-memory is a TEST DOUBLE only; Task 18B
    performs the real local Microsoft SQL Server integration test.
    """
    # TEST-014AD
    import socket

    def _blocked_connect(self, *args, **kwargs):
        raise AssertionError("network connection attempted during repository test")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

    repository = make_repository()
    repository.save_workflow_run(make_snapshot())
    repository.append_audit_event(make_event())

    assert repository.get_workflow_run("SYN-TRACE-001") is not None
