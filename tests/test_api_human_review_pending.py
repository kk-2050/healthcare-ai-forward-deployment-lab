# File Name: test_api_human_review_pending.py
# Purpose: Tests the read-only GET /human-review/pending/{trace_id} FastAPI endpoint using an in-memory SQLite test double.
# Creation Date: 2026-10-04
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary added in Task 26B: a read-only
# lookup of the pending Human Review (if any) for an existing trace_id,
# reusing HumanReviewRepository.get_pending_review_by_trace_id()
# unchanged -- that method already excludes COMPLETED/CANCELLED
# reviews and already resolves deterministically if more than one row
# matches. TestClient talks to the FastAPI app in-process -- no server
# is started and no real network traffic leaves the test process.

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.dependencies import get_human_review_repository, get_session_factory
from src.db.base import create_database_schema
from src.db.human_review_repository import HumanReviewRepository, PersistenceError
from src.db.models import HumanReviewORM, PriorAuthorizationCaseORM, WorkflowRunORM

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-API-PENDING-001"


def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as every other offline API test)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_fixture(
    engine,
    *,
    review_id: str,
    trace_id: str,
    case_id: str,
    review_status_code: str = "REQUESTED",
    review_outcome_code: str | None = None,
) -> None:
    """Inserts the minimum prior_authorization_cases/workflow_runs/
    human_reviews rows needed to exercise the pending-review lookup.
    Mirrors the raw-ORM-insert fixture pattern already used in
    tests/test_api_human_review_decisions.py."""
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=case_id,
                client_id="SYN-CLIENT-API-PENDING-001",
                case_status_code="HUMAN_REVIEW_REQUIRED",
                member_id="SYN-MEMBER-001",
                provider_id="SYN-PROVIDER-001",
                requested_service_code="SYN-LUMBAR-MRI",
                requested_date=date(2026, 1, 15),
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.add(
            WorkflowRunORM(
                trace_id=trace_id,
                case_id=case_id,
                workflow_definition_id=_WORKFLOW_DEFINITION_ID,
                workflow_status_code="HUMAN_REVIEW_REQUIRED",
                next_action_code="ROUTE_HUMAN_REVIEW",
                human_review_required=True,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.add(
            HumanReviewORM(
                review_id=review_id,
                trace_id=trace_id,
                case_id=case_id,
                review_status_code=review_status_code,
                review_outcome_code=review_outcome_code,
                reason_code="HUMAN_REVIEW_FHIR_FAILURE",
                requested_at_utc=now,
                completed_at_utc=now if review_status_code == "COMPLETED" else None,
                reviewer_actor_type_code="HUMAN_REVIEWER" if review_status_code == "COMPLETED" else None,
                reviewer_reference="SYN-REVIEWER-PENDING-001" if review_status_code == "COMPLETED" else None,
                source_component_code="HUMAN_REVIEW_SERVICE",
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
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
    app.dependency_overrides[get_human_review_repository] = lambda: HumanReviewRepository(
        session_factory=session_factory
    )

    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()


def test_requested_pending_review_returns_200(client_with_engine):
    """Verify a REQUESTED review is reported as pending."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_pending_001", trace_id="trace_pending_001", case_id="case_pending_001")

    response = client.get("/human-review/pending/trace_pending_001")

    assert response.status_code == 200
    body = response.json()
    assert body["review_id"] == "review_pending_001"
    assert body["review_status_code"] == "REQUESTED"


def test_in_progress_pending_review_returns_200(client_with_engine):
    """Verify an IN_PROGRESS review is also reported as pending --
    get_pending_review_by_trace_id() treats REQUESTED and IN_PROGRESS
    both as pending, per its own existing contract."""
    client, engine = client_with_engine
    make_fixture(
        engine,
        review_id="review_pending_002",
        trace_id="trace_pending_002",
        case_id="case_pending_002",
        review_status_code="IN_PROGRESS",
    )

    response = client.get("/human-review/pending/trace_pending_002")

    assert response.status_code == 200
    assert response.json()["review_status_code"] == "IN_PROGRESS"


def test_no_review_at_all_returns_404(client_with_engine):
    """Verify a trace_id with no human_reviews row at all returns the
    fixed, safe 404 message."""
    client, _engine = client_with_engine

    response = client.get("/human-review/pending/trace_does_not_exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "No pending Human Review found for this trace_id."}


def test_completed_review_alone_returns_404(client_with_engine):
    """Verify a review that has already been decided (COMPLETED) is
    never reported as pending."""
    client, engine = client_with_engine
    make_fixture(
        engine,
        review_id="review_pending_003",
        trace_id="trace_pending_003",
        case_id="case_pending_003",
        review_status_code="COMPLETED",
        review_outcome_code="CONTINUE_WORKFLOW",
    )

    response = client.get("/human-review/pending/trace_pending_003")

    assert response.status_code == 404
    assert response.json() == {"detail": "No pending Human Review found for this trace_id."}


def test_cancelled_review_alone_returns_404(client_with_engine):
    """Verify a CANCELLED review is never reported as pending."""
    client, engine = client_with_engine
    make_fixture(
        engine,
        review_id="review_pending_004",
        trace_id="trace_pending_004",
        case_id="case_pending_004",
        review_status_code="CANCELLED",
    )

    response = client.get("/human-review/pending/trace_pending_004")

    assert response.status_code == 404
    assert response.json() == {"detail": "No pending Human Review found for this trace_id."}


def test_persistence_failure_returns_fixed_500(client_with_engine):
    """Verify a repository failure returns a fixed, safe 500 -- never
    raw exception text."""
    client, engine = client_with_engine
    session_factory = sessionmaker(bind=engine)

    class _FailingRepository(HumanReviewRepository):
        def get_pending_review_by_trace_id(self, trace_id):
            raise PersistenceError("synthetic simulated persistence failure")

    app.dependency_overrides[get_human_review_repository] = lambda: _FailingRepository(
        session_factory=session_factory
    )

    response = client.get("/human-review/pending/trace_pending_005")

    assert response.status_code == 500
    assert response.json() == {"detail": "The pending Human Review could not be retrieved."}
    assert "synthetic simulated persistence failure" not in response.text


def test_response_matches_human_review_record_shape(client_with_engine):
    """Verify the response body is exactly the HumanReviewRecord shape
    -- no extra or missing top-level field."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_pending_006", trace_id="trace_pending_006", case_id="case_pending_006")

    response = client.get("/human-review/pending/trace_pending_006")

    expected_keys = {
        "review_id", "trace_id", "case_id", "review_status_code",
        "review_outcome_code", "reason_code", "assigned_department_id",
        "assigned_location_id", "requested_at_utc", "started_at_utc",
        "completed_at_utc", "reviewer_actor_type_code", "reviewer_reference",
        "review_note_text", "source_component_code", "metadata_json",
        "created_at_utc", "created_by", "updated_at_utc", "updated_by",
        "is_deleted", "deleted_at_utc", "deleted_by", "delete_reason_code",
        "delete_reason_text",
    }
    assert set(response.json().keys()) == expected_keys


def test_get_does_not_mutate_review_state(client_with_engine):
    """Verify calling the GET endpoint twice leaves the stored
    human_reviews row completely unchanged -- a read must never write."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_pending_007", trace_id="trace_pending_007", case_id="case_pending_007")

    first = client.get("/human-review/pending/trace_pending_007").json()
    second = client.get("/human-review/pending/trace_pending_007").json()

    assert first == second
    with sessionmaker(bind=engine)() as session:
        row = session.get(HumanReviewORM, "review_pending_007")
        assert row.review_status_code == "REQUESTED"
