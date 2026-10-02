# File Name: test_api_human_review_decisions.py
# Purpose: Tests the POST /human-review/decisions FastAPI endpoint using an in-memory SQLite test double and the in-process TestClient only.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary added in Task 23C-7A: they
# confirm the endpoint validates requests the same way
# HumanReviewDecisionRequest/resume_after_human_review() already do,
# reuses the existing service without duplicating its business logic,
# and never calls a real SQL Server. TestClient talks to the FastAPI app
# in-process -- no server is started and no real network traffic leaves
# the test process. src/api/dependencies.py's get_session_factory is
# overridden (via app.dependency_overrides, FastAPI's own supported
# mechanism) to point at an isolated in-memory SQLite engine for the
# whole file, exactly mirroring the offline-SQLite-test-double
# convention already used throughout this project (e.g.
# tests/test_workflow_orchestrator.py) -- never a live SQL Server
# connection.

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import app
from src.api.dependencies import (
    get_case_repository,
    get_human_review_repository,
    get_session_factory,
    get_workflow_repository,
)
from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository, PersistenceError
from src.db.models import HumanReviewORM, PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import AuditRepository

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-API-001"


def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as tests/test_workflow_orchestrator.py)."""
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
    reason_code: str = "HUMAN_REVIEW_FHIR_FAILURE",
    review_status_code: str = "REQUESTED",
    review_outcome_code: str | None = None,
) -> None:
    """Inserts the minimum prior_authorization_cases/workflow_runs/
    human_reviews rows resume_after_human_review() needs to find an
    existing pending (or already-decided, for conflict tests) review.
    Mirrors the raw-ORM-insert fixture pattern already used in
    tests/test_workflow_orchestrator.py's Stage 1/Human Review tests."""
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=case_id,
                client_id="SYN-CLIENT-API-001",
                case_status_code="OPEN",
                member_id="SYN-MEMBER-001",
                provider_id="SYN-PROVIDER-001",
                requested_service_code="SYN-LUMBAR-MRI",
                requested_date=datetime(2026, 1, 15).date(),
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
                reason_code=reason_code,
                requested_at_utc=now,
                completed_at_utc=now if review_status_code == "COMPLETED" else None,
                reviewer_actor_type_code="HUMAN_REVIEWER" if review_status_code == "COMPLETED" else None,
                reviewer_reference="SYN-REVIEWER-EXISTING-001" if review_status_code == "COMPLETED" else None,
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
    """Builds a fresh in-memory SQLite engine per test, overrides all
    four API-layer database dependencies to use it, yields (TestClient,
    engine), and always clears the overrides afterward so tests never
    leak state into each other or accidentally point at a real engine."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)

    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_workflow_repository] = lambda: AuditRepository(
        session_factory=session_factory
    )
    app.dependency_overrides[get_human_review_repository] = lambda: HumanReviewRepository(
        session_factory=session_factory
    )
    app.dependency_overrides[get_case_repository] = lambda: CaseRepository(
        session_factory=session_factory
    )

    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()


def valid_decision_payload(**overrides):
    data = {
        "review_id": "review_api_001",
        "review_outcome_code": "CONTINUE_WORKFLOW",
        "reviewer_actor_type_code": "HUMAN_REVIEWER",
        "reviewer_reference": "SYN-REVIEWER-API-001",
        "decision_at_utc": "2026-01-15T12:00:00Z",
    }
    data.update(overrides)
    return data


# =====================================================================
# VALID DECISION TESTS -- ALL FOUR APPROVED OUTCOMES
# =====================================================================
def test_continue_workflow_decision_reaches_service(client_with_engine):
    """Verify a valid CONTINUE_WORKFLOW decision reaches
    resume_after_human_review() and returns the approved PENDING_RESUME/
    CONTINUE_PROCESSING state with completed_at_utc null -- never true
    resumption, never WORKFLOW_RESUMED."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_001", trace_id="trace_api_001", case_id="case_api_001")

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_001"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["review_status_code"] == "COMPLETED"
    assert body["review"]["review_outcome_code"] == "CONTINUE_WORKFLOW"
    assert body["workflow_run"]["workflow_status_code"] == "PENDING_RESUME"
    assert body["workflow_run"]["next_action_code"] == "CONTINUE_PROCESSING"
    assert body["workflow_run"]["completed_at_utc"] is None
    event_types = {e["event_type_code"] for e in body["audit_events"]}
    assert "WORKFLOW_RESUMED" not in event_types
    assert "WORKFLOW_COMPLETED" not in event_types
    assert "HUMAN_REVIEW_COMPLETED" in event_types


def test_request_more_information_decision_reaches_service(client_with_engine):
    """Verify a valid REQUEST_MORE_INFORMATION decision reaches the
    service and persists case_status_code=PENDING_INFORMATION."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_002", trace_id="trace_api_002", case_id="case_api_002")
    case_repository = CaseRepository(session_factory=sessionmaker(bind=engine))

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(
            review_id="review_api_002", review_outcome_code="REQUEST_MORE_INFORMATION"
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_run"]["workflow_status_code"] == "COMPLETED"
    assert body["workflow_run"]["next_action_code"] == "REQUEST_MISSING_INFORMATION"
    assert case_repository.get_case_status_code("case_api_002") == "PENDING_INFORMATION"


def test_escalate_decision_reaches_service(client_with_engine):
    """Verify a valid ESCALATE decision reaches the service and
    persists case_status_code=HUMAN_REVIEW_REQUIRED."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_003", trace_id="trace_api_003", case_id="case_api_003")
    case_repository = CaseRepository(session_factory=sessionmaker(bind=engine))

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_003", review_outcome_code="ESCALATE"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_run"]["next_action_code"] == "ROUTE_HUMAN_REVIEW"
    assert case_repository.get_case_status_code("case_api_003") == "HUMAN_REVIEW_REQUIRED"


def test_close_case_decision_reaches_service(client_with_engine):
    """Verify a valid CLOSE_CASE decision (with an approved reason)
    reaches the service and persists case_status_code=CLOSED."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_004", trace_id="trace_api_004", case_id="case_api_004")
    case_repository = CaseRepository(session_factory=sessionmaker(bind=engine))

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(
            review_id="review_api_004",
            review_outcome_code="CLOSE_CASE",
            close_reason_code="CASE_CLOSE_COMPLETED",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_run"]["next_action_code"] == "COMPLETE_WORKFLOW"
    assert case_repository.get_case_status_code("case_api_004") == "CLOSED"


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_invalid_outcome_rejected_by_schema(client_with_engine):
    """Verify an outcome outside the four approved values (including
    any clinical approve/deny-style value) is rejected with HTTP 422 by
    Pydantic, before the route body ever runs."""
    client, _engine = client_with_engine

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_outcome_code="APPROVE"),
    )

    assert response.status_code == 422


def test_missing_required_identifier_rejected(client_with_engine):
    """Verify a request missing review_id is rejected with HTTP 422."""
    client, _engine = client_with_engine
    payload = valid_decision_payload()
    del payload["review_id"]

    response = client.post("/human-review/decisions", json=payload)

    assert response.status_code == 422


def test_unknown_top_level_field_rejected(client_with_engine):
    """Verify an unexpected top-level field is rejected with HTTP 422 --
    the endpoint never silently ignores unknown fields."""
    client, _engine = client_with_engine

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(unexpected_field="not allowed"),
    )

    assert response.status_code == 422


# =====================================================================
# DOMAIN ERROR TESTS
# =====================================================================
def test_unknown_review_id_fails_safely_with_404(client_with_engine):
    """Verify a review_id that does not exist returns HTTP 404
    (ResumeError), not a false success."""
    client, _engine = client_with_engine

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_does_not_exist"),
    )

    assert response.status_code == 404


def test_close_case_without_reason_returns_422(client_with_engine):
    """Verify CLOSE_CASE without close_reason_code returns HTTP 422
    (InvalidCloseReasonError) -- the service's own deterministic
    validation, not duplicated in the API schema."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_005", trace_id="trace_api_005", case_id="case_api_005")

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_005", review_outcome_code="CLOSE_CASE"),
    )

    assert response.status_code == 422


def test_conflicting_decision_on_completed_review_returns_409(client_with_engine):
    """Verify submitting a DIFFERENT outcome for an already-COMPLETED
    review returns HTTP 409 (HumanReviewConflictError) -- a recorded
    human decision is never silently overwritten."""
    client, engine = client_with_engine
    make_fixture(
        engine,
        review_id="review_api_006",
        trace_id="trace_api_006",
        case_id="case_api_006",
        review_status_code="COMPLETED",
        review_outcome_code="CONTINUE_WORKFLOW",
    )

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_006", review_outcome_code="ESCALATE"),
    )

    assert response.status_code == 409


def test_persistence_failure_returns_500_not_success(client_with_engine):
    """Verify a persistence failure inside the service returns HTTP 500
    with the fixed safe message -- never a false 200 success."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_007", trace_id="trace_api_007", case_id="case_api_007")

    class _FailingHumanReviewRepository(HumanReviewRepository):
        def record_review_outcome(self, **kwargs):
            raise PersistenceError("synthetic simulated persistence failure")

    app.dependency_overrides[get_human_review_repository] = lambda: _FailingHumanReviewRepository(
        session_factory=sessionmaker(bind=engine)
    )

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_007"),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "The Human Review decision could not be persisted."


# =====================================================================
# IDENTITY / NO-NEW-RUN TESTS
# =====================================================================
def test_response_preserves_review_case_trace_association(client_with_engine):
    """Verify the response's review_id/case_id/trace_id exactly match
    the existing pending review -- no substitution."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_008", trace_id="trace_api_008", case_id="case_api_008")

    response = client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_008"),
    )

    body = response.json()
    assert body["review"]["review_id"] == "review_api_008"
    assert body["review"]["case_id"] == "case_api_008"
    assert body["review"]["trace_id"] == "trace_api_008"
    assert body["workflow_run"]["trace_id"] == "trace_api_008"


def test_no_new_workflow_run_or_trace_created(client_with_engine):
    """Verify exactly one workflow_runs row exists for this trace_id
    before and after the decision -- no new run, no new trace_id."""
    client, engine = client_with_engine
    make_fixture(engine, review_id="review_api_009", trace_id="trace_api_009", case_id="case_api_009")

    with sessionmaker(bind=engine)() as session:
        before_count = session.query(WorkflowRunORM).count()

    client.post(
        "/human-review/decisions",
        json=valid_decision_payload(review_id="review_api_009"),
    )

    with sessionmaker(bind=engine)() as session:
        after_count = session.query(WorkflowRunORM).count()
        run = session.get(WorkflowRunORM, "trace_api_009")

    assert before_count == after_count == 1
    assert run is not None
