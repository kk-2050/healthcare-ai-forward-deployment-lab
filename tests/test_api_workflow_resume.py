# File Name: test_api_workflow_resume.py
# Purpose: Tests the POST /workflows/{trace_id}/resume FastAPI endpoint using an in-memory SQLite test double, an offline FHIRStyleClient, and a mocked AI provider only.
# Creation Date: 2026-09-29
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary added in Task 24B-4C: they
# confirm the endpoint validates requests the same way
# ResumeWorkflowRequest/resume_workflow() already do, reuses the
# existing resume_workflow() service without duplicating its business
# logic, and never calls a real SQL Server, a real FHIR-style service,
# or a real AI provider. TestClient talks to the FastAPI app in-process
# -- no server is started and no real network traffic leaves the test
# process.
#
# All four API-layer dependencies this endpoint needs
# (get_session_factory, get_workflow_repository,
# get_human_review_repository, get_case_repository) are overridden via
# app.dependency_overrides to point at an isolated in-memory SQLite
# engine, exactly mirroring tests/test_api_human_review_decisions.py.
# Two more dependencies are also overridden here for the first time:
# get_fhir_client (an offline FHIRStyleClient backed by
# httpx.MockTransport -- never a live network call) and get_ai_provider
# (a MockAIAnalysisProvider -- never a live Azure OpenAI call). One
# test deliberately does NOT override get_fhir_client, to prove the
# fail-closed default actually fails closed over real HTTP.
#
# These tests do not re-prove resume_workflow()'s own business rules
# (eligibility, case-identity, atomic claim, continuation) -- that is
# already covered by tests/test_workflow_resume_service.py and
# tests/test_workflow_continuation.py. This file only proves the HTTP
# transport layer: request/response shape, dependency wiring, and
# exception-to-HTTP-status mapping.

from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.workflow.orchestrator as orchestrator_module
from src.ai.mock_provider import MockAIAnalysisProvider
from src.api.app import app
from src.api.dependencies import (
    get_ai_provider,
    get_case_repository,
    get_fhir_client,
    get_human_review_repository,
    get_session_factory,
    get_workflow_repository,
)
from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import AuditEventORM, HumanReviewORM, PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import AuditRepository, PersistenceError, deterministic_human_review_event_id
from src.integrations.fhir_client import FHIRStyleClient

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-API-RESUME-001"


# =====================================================================
# FIXTURES
# Kept local to this file, matching the existing convention in
# tests/test_api_human_review_decisions.py.
# =====================================================================
def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as every other offline test in this
    project)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def valid_fhir_bundle_json():
    """A minimal, fully valid synthetic FHIR-style Bundle whose facts
    agree with make_resume_fixture()'s default case."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-API-RESUME-001",
                    "status": "active",
                    "intent": "order",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": "SYN-LUMBAR-MRI",
                                "display": "Lumbar MRI (synthetic)",
                            }
                        ]
                    },
                    "reasonReference": [{"reference": "Condition/SYN-COND-API-RESUME-001"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-API-RESUME-001",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": "SYN-LOW-BACK-PAIN",
                                "display": "Low back pain (synthetic)",
                            }
                        ]
                    },
                }
            },
        ],
    }


def make_offline_fhir_client(status_code: int = 200, json_body=None) -> FHIRStyleClient:
    """Builds an FHIRStyleClient backed entirely by httpx.MockTransport
    -- no DNS lookup and no real network call is possible through this
    object, regardless of what base_url it is given."""
    body = valid_fhir_bundle_json() if json_body is None else json_body

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def make_offline_ai_provider(**kwargs) -> MockAIAnalysisProvider:
    if not kwargs:
        kwargs = {"response": {"completed_tasks": []}}
    return MockAIAnalysisProvider(**kwargs)


def make_resume_fixture(
    engine,
    *,
    trace_id: str,
    case_id: str,
    review_id: str,
    workflow_status_code: str = "PENDING_RESUME",
    next_action_code: str | None = "CONTINUE_PROCESSING",
    review_status_code: str = "COMPLETED",
    review_outcome_code: str | None = "CONTINUE_WORKFLOW",
    review_case_id: str | None = None,
    member_id: str = "SYN-MEMBER-001",
    provider_id: str = "SYN-PROVIDER-001",
    requested_service_code: str = "SYN-LUMBAR-MRI",
    requested_date: date = date(2026, 1, 15),
) -> None:
    """
    Inserts the minimum prior_authorization_cases/workflow_runs/
    human_reviews rows resume_workflow() needs to find an eligible run
    with a completed CONTINUE_WORKFLOW decision -- the exact durable
    state a real reviewer decision (POST /human-review/decisions) would
    have already left behind. Mirrors the raw-ORM-insert fixture
    pattern already used in tests/test_api_human_review_decisions.py
    and tests/test_workflow_resume_service.py.
    """
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=case_id,
                client_id="SYN-CLIENT-API-RESUME-001",
                case_status_code="OPEN",
                member_id=member_id,
                provider_id=provider_id,
                requested_service_code=requested_service_code,
                requested_date=requested_date,
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
                workflow_status_code=workflow_status_code,
                next_action_code=next_action_code,
                human_review_required=False,
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
                case_id=review_case_id or case_id,
                review_status_code=review_status_code,
                review_outcome_code=review_outcome_code,
                reason_code="HUMAN_REVIEW_FHIR_FAILURE",
                requested_at_utc=now,
                completed_at_utc=now if review_status_code == "COMPLETED" else None,
                reviewer_actor_type_code="HUMAN_REVIEWER" if review_status_code == "COMPLETED" else None,
                reviewer_reference="SYN-REVIEWER-API-RESUME-001" if review_status_code == "COMPLETED" else None,
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
    """
    Builds a fresh in-memory SQLite engine per test, overrides every
    dependency the resume endpoint needs (session factory, the three
    repositories, the FHIR client, and the AI provider) with offline
    test doubles, yields (TestClient, engine, fhir_client, ai_provider),
    and always clears the overrides afterward so tests never leak
    state into each other or accidentally point at a real engine,
    a real FHIR service, or a real AI provider.
    """
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    fhir_client = make_offline_fhir_client()
    ai_provider = make_offline_ai_provider()

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
    app.dependency_overrides[get_fhir_client] = lambda: fhir_client
    app.dependency_overrides[get_ai_provider] = lambda: ai_provider

    try:
        yield TestClient(app), engine, fhir_client, ai_provider
    finally:
        app.dependency_overrides.clear()


def valid_resume_payload(**overrides):
    data = {
        "case": {
            "case_id": "case_api_resume_001",
            "member_id": "SYN-MEMBER-001",
            "provider_id": "SYN-PROVIDER-001",
            "requested_service_code": "SYN-LUMBAR-MRI",
            "diagnosis_code": "SYN-LOW-BACK-PAIN",
            "requested_date": "2026-01-15",
        },
        "completeness_requirements": {
            "required_documentation": [],
            "clinical_notes_required": False,
        },
        "ai_processing_requirements": {"tasks": []},
    }
    data.update(overrides)
    return data


# =====================================================================
# SUCCESSFUL RESUME TESTS
# =====================================================================
def test_valid_resume_returns_200(client_with_engine):
    """
    Verifies that a fully eligible resume request completes and
    returns HTTP 200.

    This is the golden path: an already-completed CONTINUE_WORKFLOW
    decision, resumed through the HTTP endpoint with a working FHIR
    client and AI provider, must actually continue processing rather
    than failing or silently doing nothing.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_001",
        case_id="case_api_resume_001",
        review_id="review_api_resume_001",
    )

    response = client.post(
        "/workflows/trace_api_resume_001/resume",
        json=valid_resume_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_run"]["workflow_status_code"] == "COMPLETED"


def test_same_trace_id_is_preserved(client_with_engine):
    """
    Verifies the response's trace_id is exactly the trace_id from the
    URL path -- never a freshly generated one.

    This protects the SAME-RUN/SAME-TRACE contract: resuming must
    never look like starting a new workflow run.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_002",
        case_id="case_api_resume_002",
        review_id="review_api_resume_002",
    )

    response = client.post(
        "/workflows/trace_api_resume_002/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_002"}),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == "trace_api_resume_002"
    assert body["workflow_run"]["trace_id"] == "trace_api_resume_002"


def test_same_workflow_run_is_preserved_no_second_row(client_with_engine):
    """
    Verifies exactly one workflow_runs row exists for this trace_id
    before and after the resume call.

    This proves resume never inserts a second, competing row for the
    same trace_id -- it can only update the one row that already
    exists.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_003",
        case_id="case_api_resume_003",
        review_id="review_api_resume_003",
    )

    with sessionmaker(bind=engine)() as session:
        before_count = session.query(WorkflowRunORM).count()

    response = client.post(
        "/workflows/trace_api_resume_003/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_003"}),
    )

    with sessionmaker(bind=engine)() as session:
        after_count = session.query(WorkflowRunORM).count()

    assert response.status_code == 200
    assert before_count == after_count == 1


def test_response_case_id_comes_from_persisted_workflow_run(client_with_engine):
    """
    Verifies the response's case_id is read from the persisted
    workflow_run, not merely echoed back from the request body.

    This matters because the durable record, not the caller's input,
    is the response's source of truth -- even though both happen to
    agree in this test, the endpoint must not shortcut through the
    request to build the response.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_004",
        case_id="case_api_resume_004",
        review_id="review_api_resume_004",
    )

    response = client.post(
        "/workflows/trace_api_resume_004/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_004"}),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "case_api_resume_004"
    assert body["workflow_run"]["case_id"] == "case_api_resume_004"


def test_response_shape_excludes_final_state_and_raw_content(client_with_engine):
    """
    Verifies the response body has exactly the four documented fields
    -- trace_id, case_id, workflow_run, audit_events -- and nothing
    else.

    This is the direct proof that WorkflowRunResult.final_state (which
    would carry the re-supplied case, raw FHIR evidence, and raw AI
    output) never reaches the HTTP response, satisfying the project's
    data-minimization rule at the transport boundary.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_005",
        case_id="case_api_resume_005",
        review_id="review_api_resume_005",
    )

    response = client.post(
        "/workflows/trace_api_resume_005/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_005"}),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"trace_id", "case_id", "workflow_run", "audit_events"}
    assert "final_state" not in body
    # workflow_run/audit_events are already the canonical, deterministic
    # models -- confirm none of the obvious raw-content field names
    # leaked into them either.
    assert "evidence" not in body["workflow_run"]
    assert "fhir_integration_outcome" not in body["workflow_run"]
    assert "ai_analysis_outcome" not in body["workflow_run"]
    for event in body["audit_events"]:
        assert "evidence" not in event
        assert "ai_analysis_outcome" not in event


def test_workflow_resumed_event_matches_deterministic_id(client_with_engine):
    """
    Verifies exactly one WORKFLOW_RESUMED audit event is returned, with
    an event_id matching deterministic_human_review_event_id(review_id,
    "WORKFLOW_RESUMED").

    This confirms the HTTP layer surfaces the same WORKFLOW_RESUMED
    behavior already proven at the service layer
    (tests/test_workflow_continuation.py) -- the API does not alter or
    duplicate that behavior.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_006",
        case_id="case_api_resume_006",
        review_id="review_api_resume_006",
    )

    response = client.post(
        "/workflows/trace_api_resume_006/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_006"}),
    )

    assert response.status_code == 200
    events = response.json()["audit_events"]
    resumed_events = [e for e in events if e["event_type_code"] == "WORKFLOW_RESUMED"]
    assert len(resumed_events) == 1
    assert resumed_events[0]["event_id"] == deterministic_human_review_event_id(
        "review_api_resume_006", "WORKFLOW_RESUMED"
    )


def test_no_second_workflow_started_event(client_with_engine):
    """
    Verifies resuming never creates a WORKFLOW_STARTED audit event.

    WORKFLOW_STARTED belongs only to a run's original start
    (run_prior_authorization_workflow()) -- resume must never look like
    a second, brand-new run beginning.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_007",
        case_id="case_api_resume_007",
        review_id="review_api_resume_007",
    )

    client.post(
        "/workflows/trace_api_resume_007/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_007"}),
    )

    with sessionmaker(bind=engine)() as session:
        started_events = (
            session.query(AuditEventORM)
            .filter_by(trace_id="trace_api_resume_007", event_type_code="WORKFLOW_STARTED")
            .count()
        )
    assert started_events == 0


def test_no_new_trace_id_created(client_with_engine):
    """
    Verifies the only workflow_runs row for this case's trace_id, both
    before and after resume, is the SAME one -- resume never
    generates a fresh trace_id.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_008",
        case_id="case_api_resume_008",
        review_id="review_api_resume_008",
    )

    response = client.post(
        "/workflows/trace_api_resume_008/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_008"}),
    )

    with sessionmaker(bind=engine)() as session:
        run = session.get(WorkflowRunORM, "trace_api_resume_008")

    assert response.status_code == 200
    assert run is not None
    assert response.json()["trace_id"] == "trace_api_resume_008"


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_missing_required_field_rejected(client_with_engine):
    """Verifies a request missing the required case field is rejected
    with HTTP 422 by Pydantic, before the route body ever runs."""
    client, _engine, _fhir_client, _ai_provider = client_with_engine
    payload = valid_resume_payload()
    del payload["case"]

    response = client.post("/workflows/trace_does_not_matter/resume", json=payload)

    assert response.status_code == 422


def test_extra_top_level_field_rejected(client_with_engine):
    """Verifies an unexpected top-level field is rejected with HTTP 422
    -- the endpoint never silently ignores unknown fields, matching
    ResumeWorkflowRequest's extra="forbid" contract."""
    client, _engine, _fhir_client, _ai_provider = client_with_engine

    response = client.post(
        "/workflows/trace_does_not_matter/resume",
        json=valid_resume_payload(unexpected_field="not allowed"),
    )

    assert response.status_code == 422


# =====================================================================
# DOMAIN ERROR TESTS
# =====================================================================
def test_unknown_trace_id_returns_404(client_with_engine):
    """
    Verifies the endpoint returns HTTP 404 for a trace_id with no
    workflow_runs row at all.

    This prevents the API from reporting successful continuation when
    no existing workflow run can be found to resume.
    """
    client, _engine, _fhir_client, _ai_provider = client_with_engine

    response = client.post(
        "/workflows/trace_does_not_exist/resume",
        json=valid_resume_payload(),
    )

    assert response.status_code == 404


def test_ineligible_workflow_status_returns_409(client_with_engine):
    """
    Verifies a run that is not in PENDING_RESUME (e.g. still
    PROCESSING) returns HTTP 409, not a false success.

    This protects the resume eligibility contract: only a run that
    genuinely completed a CONTINUE_WORKFLOW decision may be resumed.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_009",
        case_id="case_api_resume_009",
        review_id="review_api_resume_009",
        workflow_status_code="PROCESSING",
        next_action_code=None,
    )

    response = client.post(
        "/workflows/trace_api_resume_009/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_009"}),
    )

    assert response.status_code == 409


def test_case_identity_mismatch_returns_409(client_with_engine):
    """
    Verifies a caller-supplied case that disagrees with the persisted
    case's durable identity fields (here, member_id) returns HTTP 409.

    This protects against resuming a run with a substituted, different
    member's data.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_010",
        case_id="case_api_resume_010",
        review_id="review_api_resume_010",
        member_id="SYN-MEMBER-001",
    )

    response = client.post(
        "/workflows/trace_api_resume_010/resume",
        json=valid_resume_payload(
            case={
                **valid_resume_payload()["case"],
                "case_id": "case_api_resume_010",
                "member_id": "SYN-MEMBER-DIFFERENT",
            }
        ),
    )

    assert response.status_code == 409


def test_resume_claim_conflict_returns_409(client_with_engine):
    """
    Verifies a genuine claim race (a concurrent request wins the
    atomic claim first) returns HTTP 409, not a silent retry or a
    false success.

    Simulated by wrapping the injected AuditRepository so it steals
    the claim for itself immediately before the real claim attempt --
    the same race-simulation technique already used in
    tests/test_workflow_resume_service.py, applied here at the HTTP
    layer.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_011",
        case_id="case_api_resume_011",
        review_id="review_api_resume_011",
    )
    session_factory = sessionmaker(bind=engine)

    class _StealingClaimRepository(AuditRepository):
        def claim_workflow_run_for_resume(self, trace_id, **kwargs):
            # A concurrent request "wins" the race by claiming first.
            super().claim_workflow_run_for_resume(
                trace_id,
                updated_at_utc=datetime.now(timezone.utc),
                updated_by="CONCURRENT_REQUEST",
            )
            return super().claim_workflow_run_for_resume(trace_id, **kwargs)

    app.dependency_overrides[get_workflow_repository] = lambda: _StealingClaimRepository(
        session_factory=session_factory
    )

    response = client.post(
        "/workflows/trace_api_resume_011/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_011"}),
    )

    assert response.status_code == 409


def test_audit_event_conflict_returns_409(client_with_engine):
    """
    Verifies a genuine audit-event identity conflict (a different
    event already exists under WORKFLOW_RESUMED's own deterministic
    event_id) returns HTTP 409, not a silent overwrite.

    Simulated by pre-inserting a semantically different audit_events
    row under the exact event_id this resume's WORKFLOW_RESUMED event
    would use -- this is the defense-in-depth collision case
    deterministic_human_review_event_id() exists to guard against.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_012",
        case_id="case_api_resume_012",
        review_id="review_api_resume_012",
    )
    conflicting_event_id = deterministic_human_review_event_id(
        "review_api_resume_012", "WORKFLOW_RESUMED"
    )
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            AuditEventORM(
                event_id=conflicting_event_id,
                trace_id="trace_api_resume_012",
                case_id="case_api_resume_012",
                event_type_code="WORKFLOW_RESUMED",
                event_category_code="WORKFLOW",
                source_component_code="LANGGRAPH",
                actor_type_code="SYSTEM",
                result_code="SUCCESS",
                # A different occurred_at_utc than this resume attempt
                # will use -- a genuine semantic conflict, not a replay.
                occurred_at_utc=now.replace(year=now.year - 1),
                schema_version="1",
                created_at_utc=now.replace(year=now.year - 1),
                created_by="SYSTEM",
            )
        )
        session.commit()

    response = client.post(
        "/workflows/trace_api_resume_012/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_012"}),
    )

    assert response.status_code == 409


def test_persistence_failure_returns_fixed_500(client_with_engine):
    """
    Verifies a persistence failure inside resume_workflow() (simulated
    on the case-identity read) returns HTTP 500 with the fixed safe
    message, never a false 200 success and never raw driver text.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_013",
        case_id="case_api_resume_013",
        review_id="review_api_resume_013",
    )

    class _FailingCaseRepository(CaseRepository):
        def get_case_identity(self, case_id):
            raise PersistenceError("synthetic simulated persistence failure")

    app.dependency_overrides[get_case_repository] = lambda: _FailingCaseRepository(
        session_factory=sessionmaker(bind=engine)
    )

    response = client.post(
        "/workflows/trace_api_resume_013/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_013"}),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "The workflow resume could not be persisted."


def test_orchestrator_failure_returns_fixed_500(client_with_engine, monkeypatch):
    """
    Verifies a graph-continuation failure (simulated by making the
    compiled graph's invoke() raise) returns HTTP 500 with the fixed
    safe message, not the raw underlying exception.

    Uses the same monkeypatch technique already proven in
    tests/test_workflow_continuation.py to exercise this failure path
    deterministically, without changing any production code.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_014",
        case_id="case_api_resume_014",
        review_id="review_api_resume_014",
    )

    class _RaisingGraph:
        def invoke(self, state):
            raise RuntimeError("synthetic graph invocation failure")

    monkeypatch.setattr(
        orchestrator_module, "build_case_workflow_graph", lambda *a, **k: _RaisingGraph()
    )

    response = client.post(
        "/workflows/trace_api_resume_014/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_014"}),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Workflow continuation could not complete."


# =====================================================================
# RESPONSE-SHAPING FAILURE TESTS
# Purpose:
# Protect the route's own post-continuation read
# (workflow_repository.get_workflow_run(), used to build the response)
# -- distinct from any failure inside resume_workflow() itself. This
# read is the 4th get_workflow_run() call in a successful resume (two
# inside validate_and_claim_resume(), one inside the continuation
# helper's defensive check, one here) -- confirmed directly from
# src/workflow/resume_service.py and src/workflow/orchestrator.py
# before writing these tests, not assumed.
# =====================================================================
class _CountingGetWorkflowRunRepository(AuditRepository):
    """Wraps a real AuditRepository, letting a test fail or nullify
    only one specific, numbered get_workflow_run() call -- every other
    call (and every other method) behaves exactly like the real
    repository."""

    def __init__(self, session_factory, *, fail_on_call=None, none_on_call=None):
        super().__init__(session_factory=session_factory)
        self._calls = 0
        self._fail_on_call = fail_on_call
        self._none_on_call = none_on_call

    def get_workflow_run(self, trace_id, *, session=None):
        self._calls += 1
        if self._fail_on_call is not None and self._calls == self._fail_on_call:
            raise PersistenceError("synthetic simulated response-shaping read failure")
        if self._none_on_call is not None and self._calls == self._none_on_call:
            return None
        return super().get_workflow_run(trace_id, session=session)


def test_response_shaping_read_failure_returns_fixed_500(client_with_engine):
    """
    Verifies that if resume_workflow() succeeds but the route's own
    response-shaping read afterward fails, the endpoint still returns
    HTTP 500 with the fixed safe message -- proving that failure is
    caught by the same safe error handling as any other persistence
    failure, never allowed to raise an unhandled exception past
    Pydantic response validation.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_015",
        case_id="case_api_resume_015",
        review_id="review_api_resume_015",
    )
    session_factory = sessionmaker(bind=engine)
    app.dependency_overrides[get_workflow_repository] = lambda: _CountingGetWorkflowRunRepository(
        session_factory, fail_on_call=4
    )

    response = client.post(
        "/workflows/trace_api_resume_015/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_015"}),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "The workflow resume could not be persisted."


def test_response_shaping_none_returns_fixed_500(client_with_engine):
    """
    Verifies that if the route's response-shaping read unexpectedly
    returns None (no defect elsewhere -- resume_workflow() already
    committed successfully), the endpoint returns a fixed, safe HTTP
    500 rather than letting None reach Pydantic response validation.

    This is a defensive-guard test: it does not simulate a realistic
    production scenario, only the route's own explicit safety check.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_016",
        case_id="case_api_resume_016",
        review_id="review_api_resume_016",
    )
    session_factory = sessionmaker(bind=engine)
    app.dependency_overrides[get_workflow_repository] = lambda: _CountingGetWorkflowRunRepository(
        session_factory, none_on_call=4
    )

    response = client.post(
        "/workflows/trace_api_resume_016/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_016"}),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "The workflow resume response could not be built."


# =====================================================================
# FAIL-CLOSED FHIR DEPENDENCY TESTS
# Purpose:
# Protect get_fhir_client()'s fail-closed default (src/api/
# dependencies.py) at the HTTP layer -- this is the one test file where
# get_fhir_client is deliberately left un-overridden, to prove the
# default itself, not an offline substitute for it.
# =====================================================================
@pytest.fixture()
def client_without_fhir_override():
    """
    Same as client_with_engine, except get_fhir_client is deliberately
    left at its real, fail-closed default -- every other dependency is
    still overridden with an offline double, so this test still makes
    no real SQL, LLM, or (successful) FHIR call.
    """
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
    app.dependency_overrides[get_ai_provider] = lambda: make_offline_ai_provider()
    # get_fhir_client is intentionally NOT overridden here.

    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()


def test_default_fhir_dependency_fails_closed_with_503(client_without_fhir_override):
    """
    Verifies that calling the resume endpoint without overriding
    get_fhir_client returns HTTP 503 with exactly the fixed safe
    message -- proving the fail-closed default actually blocks the
    request before resume_workflow() (and therefore any outbound FHIR
    call) is ever reached.
    """
    client, engine = client_without_fhir_override
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_017",
        case_id="case_api_resume_017",
        review_id="review_api_resume_017",
    )

    response = client.post(
        "/workflows/trace_api_resume_017/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_017"}),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Live FHIR-style integration is not available."}


def test_default_fhir_failure_exposes_no_configuration_or_exception_detail(
    client_without_fhir_override,
):
    """
    Verifies the 503 response body contains only the fixed detail
    string -- no base_url, no header, no environment variable name, and
    no raw exception text from FHIRIntegrationNotConfiguredError.
    """
    client, engine = client_without_fhir_override
    make_resume_fixture(
        engine,
        trace_id="trace_api_resume_018",
        case_id="case_api_resume_018",
        review_id="review_api_resume_018",
    )

    response = client.post(
        "/workflows/trace_api_resume_018/resume",
        json=valid_resume_payload(case={**valid_resume_payload()["case"], "case_id": "case_api_resume_018"}),
    )

    body = response.json()
    assert set(body.keys()) == {"detail"}
    assert body["detail"] == "Live FHIR-style integration is not available."
    for forbidden in ("base_url", "http", ".env", "AZURE_OPENAI", "SQL_SERVER", "Traceback"):
        assert forbidden not in response.text


# =====================================================================
# OFFLINE-ONLY WIRING PROOF
# =====================================================================
def test_dependency_overrides_use_offline_doubles_only(client_with_engine):
    """
    Verifies the FHIR and AI dependencies actually resolve to the
    offline test doubles this fixture installed, not to
    get_fhir_client()/get_ai_provider()'s own real implementations.

    This is the direct proof that the whole test file can run with no
    live SQL Server, no live FHIR-style service, and no live AI
    provider: every network-shaped dependency is confirmed to be the
    fake object this fixture built, before any test below relies on
    that being true.
    """
    _client, _engine, fhir_client, ai_provider = client_with_engine

    assert app.dependency_overrides[get_fhir_client]() is fhir_client
    assert app.dependency_overrides[get_ai_provider]() is ai_provider
    assert isinstance(ai_provider, MockAIAnalysisProvider)
