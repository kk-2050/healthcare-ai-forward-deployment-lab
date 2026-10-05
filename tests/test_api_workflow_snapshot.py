# File Name: test_api_workflow_snapshot.py
# Purpose: Tests the read-only GET /workflows/{trace_id} FastAPI endpoint using an in-memory SQLite test double.
# Creation Date: 2026-10-04
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary added in Task 26B: a read-only
# lookup of an existing workflow run's durable workflow_run/
# audit_events state, reusing AuditRepository.get_workflow_run()/
# list_audit_events() unchanged. TestClient talks to the FastAPI app
# in-process -- no server is started and no real network traffic leaves
# the test process; get_session_factory is overridden to point at an
# isolated in-memory SQLite engine, exactly mirroring the convention
# already used throughout this project's other API test files.
#
# This endpoint has no FHIR/AI dependency at all, so no FHIR client or
# AI provider override is needed here.

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.dependencies import get_session_factory, get_workflow_repository
from src.db.base import create_database_schema
from src.db.models import AuditEventORM, WorkflowRunORM
from src.db.repository import AuditRepository, PersistenceError

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-API-SNAPSHOT-001"


def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as every other offline API test)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def insert_workflow_run_and_events(
    engine,
    *,
    trace_id: str,
    case_id: str,
) -> None:
    """Inserts one workflow_runs row and two audit_events rows directly
    -- the exact durable state a real completed run would have left
    behind. Mirrors the raw-ORM-insert fixture pattern already used in
    tests/test_api_workflow_resume.py."""
    now = datetime.now(timezone.utc)
    later = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            WorkflowRunORM(
                trace_id=trace_id,
                case_id=case_id,
                workflow_definition_id=_WORKFLOW_DEFINITION_ID,
                workflow_status_code="COMPLETED",
                next_action_code="COMPLETE_WORKFLOW",
                human_review_required=False,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=now,
                completed_at_utc=later,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=later,
                updated_by="SYSTEM",
            )
        )
        session.add(
            AuditEventORM(
                event_id="evt-snapshot-001",
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="WORKFLOW_STARTED",
                event_category_code="WORKFLOW",
                source_component_code="LANGGRAPH",
                actor_type_code="SYSTEM",
                result_code="SUCCESS",
                occurred_at_utc=now,
                schema_version="1",
                created_at_utc=now,
                created_by="SYSTEM",
            )
        )
        session.add(
            AuditEventORM(
                event_id="evt-snapshot-002",
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="WORKFLOW_COMPLETED",
                event_category_code="WORKFLOW",
                workflow_status_code="COMPLETED",
                source_component_code="LANGGRAPH",
                actor_type_code="SYSTEM",
                result_code="SUCCESS",
                occurred_at_utc=later,
                schema_version="1",
                created_at_utc=later,
                created_by="SYSTEM",
            )
        )
        session.commit()


@pytest.fixture()
def client_with_engine():
    """Builds a fresh in-memory SQLite engine per test, overrides only
    the one dependency this read-only endpoint needs, yields
    (TestClient, engine), and always clears overrides afterward."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)

    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_workflow_repository] = lambda: AuditRepository(
        session_factory=session_factory
    )

    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()


def test_existing_trace_returns_200(client_with_engine):
    """Verify an existing trace_id returns 200 with the expected
    top-level shape."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_001", case_id="case_snap_001")

    response = client.get("/workflows/trace_snap_001")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"trace_id", "case_id", "workflow_run", "audit_events"}


def test_correct_case_id_and_trace_id_returned(client_with_engine):
    """Verify the response's trace_id/case_id match the stored row,
    not merely echoed from the URL blindly."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_002", case_id="case_snap_002")

    response = client.get("/workflows/trace_snap_002")

    body = response.json()
    assert body["trace_id"] == "trace_snap_002"
    assert body["case_id"] == "case_snap_002"


def test_workflow_run_snapshot_fields_returned(client_with_engine):
    """Verify the workflow_run snapshot carries the real persisted
    status/next_action_code, not a fabricated or default value."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_003", case_id="case_snap_003")

    response = client.get("/workflows/trace_snap_003")

    workflow_run = response.json()["workflow_run"]
    assert workflow_run["workflow_status_code"] == "COMPLETED"
    assert workflow_run["next_action_code"] == "COMPLETE_WORKFLOW"
    assert workflow_run["completed_at_utc"] is not None


def test_audit_events_returned_in_deterministic_order(client_with_engine):
    """Verify audit_events are returned in the same deterministic
    chronological order list_audit_events() already guarantees
    (occurred_at_utc, then event_id) -- never an arbitrary order."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_004", case_id="case_snap_004")

    response = client.get("/workflows/trace_snap_004")

    event_types = [e["event_type_code"] for e in response.json()["audit_events"]]
    assert event_types == ["WORKFLOW_STARTED", "WORKFLOW_COMPLETED"]


def test_unknown_trace_returns_404(client_with_engine):
    """Verify a trace_id with no workflow_runs row returns a fixed,
    safe 404 -- never a fabricated or empty-looking success."""
    client, _engine = client_with_engine

    response = client.get("/workflows/trace_does_not_exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "No workflow run was found for this trace_id."}


def test_persistence_failure_returns_fixed_500(client_with_engine):
    """Verify a repository failure returns a fixed, safe 500 -- never
    raw exception text."""
    client, engine = client_with_engine
    session_factory = sessionmaker(bind=engine)

    class _FailingRepository(AuditRepository):
        def get_workflow_run(self, trace_id, *, session=None):
            raise PersistenceError("synthetic simulated persistence failure")

    app.dependency_overrides[get_workflow_repository] = lambda: _FailingRepository(
        session_factory=session_factory
    )

    response = client.get("/workflows/trace_snap_005")

    assert response.status_code == 500
    assert response.json() == {"detail": "The workflow snapshot could not be retrieved."}
    assert "synthetic simulated persistence failure" not in response.text


def test_response_excludes_final_state_and_raw_content(client_with_engine):
    """Verify the response never includes final_state or any raw
    FHIR/LLM content -- only the canonical workflow_run/audit_events
    shape."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_006", case_id="case_snap_006")

    response = client.get("/workflows/trace_snap_006")

    body = response.json()
    assert "final_state" not in body
    assert "evidence" not in body["workflow_run"]
    for event in body["audit_events"]:
        assert "evidence" not in event


def test_get_does_not_mutate_workflow_run_or_audit_events(client_with_engine):
    """Verify calling the GET endpoint twice leaves the stored
    workflow_runs/audit_events rows completely unchanged -- a read
    must never write."""
    client, engine = client_with_engine
    insert_workflow_run_and_events(engine, trace_id="trace_snap_007", case_id="case_snap_007")

    first = client.get("/workflows/trace_snap_007").json()
    second = client.get("/workflows/trace_snap_007").json()

    assert first == second
    with sessionmaker(bind=engine)() as session:
        assert session.query(WorkflowRunORM).filter_by(trace_id="trace_snap_007").count() == 1
        assert session.query(AuditEventORM).filter_by(trace_id="trace_snap_007").count() == 2
