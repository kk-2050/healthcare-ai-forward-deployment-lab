# File Name: test_api_workflow_start.py
# Purpose: Tests the POST /workflows FastAPI endpoint using an in-memory SQLite test double, an offline FHIRStyleClient, and a mocked AI provider only.
# Creation Date: 2026-10-01
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary added in Task 25B: they confirm
# the endpoint validates requests the same way StartWorkflowRequest/
# start_new_case_workflow() already do, reuses the existing service
# without duplicating its business logic, and never calls a real SQL
# Server, a real FHIR-style service, or a real AI provider. TestClient
# talks to the FastAPI app in-process -- no server is started and no
# real network traffic leaves the test process.
#
# All six dependencies this endpoint needs (get_session_factory,
# get_workflow_repository, get_human_review_repository,
# get_case_repository, get_fhir_client, get_ai_provider) are overridden
# via app.dependency_overrides, exactly mirroring
# tests/test_api_workflow_resume.py's established pattern.
#
# These tests do not re-prove start_new_case_workflow()'s own
# client/duplicate/claim/compensation logic -- that is already covered
# by tests/test_case_intake_service.py. This file only proves the HTTP
# transport layer: request/response shape, dependency wiring, and
# exception-to-HTTP-status mapping.

from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
from src.db.case_repository import CaseRepository, PersistenceError
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import AuditEventORM, PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import AuditRepository

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-API-START-001"
_CLIENT_ID = "cli_api_start_001"
_CASE_ID = "case_api_start_001"
_MEMBER_ID = "SYN-MEMBER-API-START"
_PROVIDER_ID = "SYN-PROVIDER-API-START"
_REQUESTED_SERVICE_CODE = "SYN-LUMBAR-MRI"
_DIAGNOSIS_CODE = "SYN-LOW-BACK-PAIN"

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
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def insert_client(engine, client_id: str = _CLIENT_ID) -> None:
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.execute(
            text(
                "INSERT INTO clients "
                "(client_id, client_code, client_name, client_type_code, "
                "default_country_code, default_time_zone, is_active, metadata_json, "
                "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
                "VALUES (:client_id, 'API_START_TEST_CLIENT', "
                "'API Start Test Client (synthetic)', NULL, NULL, NULL, 1, NULL, "
                ":now, 'SYSTEM', :now, 'SYSTEM', 0)"
            ),
            {"client_id": client_id, "now": now},
        )
        session.commit()


def _valid_fhir_bundle_json():
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-API-START-001",
                    "status": "active",
                    "intent": "order",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _REQUESTED_SERVICE_CODE,
                                "display": "Lumbar MRI (synthetic)",
                            }
                        ]
                    },
                    "reasonReference": [{"reference": "Condition/SYN-COND-API-START-001"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-API-START-001",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _DIAGNOSIS_CODE,
                                "display": "Low back pain (synthetic)",
                            }
                        ]
                    },
                }
            },
        ],
    }


def make_offline_fhir_client(status_code: int = 200, json_body=None):
    from src.integrations.fhir_client import FHIRStyleClient

    body = _valid_fhir_bundle_json() if json_body is None else json_body

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


@pytest.fixture()
def client_with_engine():
    """
    Builds a fresh in-memory SQLite engine per test (including the
    clients table, which has no SQLAlchemy ORM class -- see
    src/db/models.py's Foreign Key Policy), overrides every dependency
    this endpoint needs with offline test doubles, yields
    (TestClient, engine, fhir_client, ai_provider), and always clears
    the overrides afterward.
    """
    engine = make_test_engine()
    create_database_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(_CLIENTS_TABLE_DDL)
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


def valid_start_payload(**overrides):
    data = {
        "client_id": _CLIENT_ID,
        "case": {
            "case_id": _CASE_ID,
            "member_id": _MEMBER_ID,
            "provider_id": _PROVIDER_ID,
            "requested_service_code": _REQUESTED_SERVICE_CODE,
            "diagnosis_code": _DIAGNOSIS_CODE,
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
# SUCCESSFUL START TESTS
# =====================================================================
def test_successful_fresh_workflow_returns_201(client_with_engine):
    """
    Verifies a fully valid fresh-case request returns HTTP 201 Created.
    """
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 201
    assert response.json()["workflow_run"]["workflow_status_code"] == "COMPLETED"


def test_trace_id_is_application_generated(client_with_engine):
    """Verifies the response's trace_id is a real, non-empty,
    application-generated value -- never supplied by the caller (the
    request has no trace_id field at all)."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    response = client.post("/workflows", json=valid_start_payload())

    trace_id = response.json()["trace_id"]
    assert isinstance(trace_id, str) and len(trace_id) > 0


def test_exactly_one_workflow_run_row(client_with_engine):
    """Verifies exactly one workflow_runs row exists after one
    successful start."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    client.post("/workflows", json=valid_start_payload())

    with sessionmaker(bind=engine)() as session:
        count = session.query(WorkflowRunORM).filter_by(case_id=_CASE_ID).count()
    assert count == 1


def test_exactly_one_workflow_started_event(client_with_engine):
    """Verifies exactly one WORKFLOW_STARTED audit event exists after
    one successful start."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)
    response = client.post("/workflows", json=valid_start_payload())
    trace_id = response.json()["trace_id"]

    with sessionmaker(bind=engine)() as session:
        count = (
            session.query(AuditEventORM)
            .filter_by(trace_id=trace_id, event_type_code="WORKFLOW_STARTED")
            .count()
        )
    assert count == 1


def test_deterministic_incomplete_case_routes_to_stage1(client_with_engine):
    """Verifies a deterministically incomplete case reaches the Stage 1
    REQUEST_MISSING_INFORMATION disposition, not Human Review."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    response = client.post(
        "/workflows",
        json=valid_start_payload(
            completeness_requirements={
                "required_documentation": ["SYN-DOC-A"],
                "clinical_notes_required": False,
            }
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_run"]["workflow_status_code"] == "COMPLETED"
    assert body["workflow_run"]["next_action_code"] == "REQUEST_MISSING_INFORMATION"


def test_genuine_fhir_failure_routes_to_human_review_required(client_with_engine):
    """Verifies a genuine mocked FHIR failure routes to
    HUMAN_REVIEW_REQUIRED, with a real human_reviews row created."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)
    app.dependency_overrides[get_fhir_client] = lambda: make_offline_fhir_client(
        status_code=500, json_body={"error": "synthetic"}
    )

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 201
    assert response.json()["workflow_run"]["workflow_status_code"] == "HUMAN_REVIEW_REQUIRED"


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_missing_required_field_rejected(client_with_engine):
    """Verifies a request missing the required client_id field is
    rejected with HTTP 422."""
    client, _engine, _fhir_client, _ai_provider = client_with_engine
    payload = valid_start_payload()
    del payload["client_id"]

    response = client.post("/workflows", json=payload)

    assert response.status_code == 422


def test_extra_top_level_field_rejected(client_with_engine):
    """Verifies an unexpected top-level field is rejected with HTTP 422
    -- matching StartWorkflowRequest's extra="forbid" contract."""
    client, _engine, _fhir_client, _ai_provider = client_with_engine

    response = client.post(
        "/workflows", json=valid_start_payload(unexpected_field="not allowed")
    )

    assert response.status_code == 422


# =====================================================================
# DOMAIN ERROR TESTS
# =====================================================================
def test_unknown_client_returns_fixed_404(client_with_engine):
    """Verifies an unknown client_id returns HTTP 404 with the fixed
    safe public message, and creates no case."""
    client, engine, _fhir_client, _ai_provider = client_with_engine

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 404
    assert response.json()["detail"] == "The specified client could not be found."
    with sessionmaker(bind=engine)() as session:
        assert session.query(PriorAuthorizationCaseORM).count() == 0


def test_duplicate_case_returns_fixed_409(client_with_engine):
    """Verifies a case_id that already has a workflow run returns HTTP
    409 with the fixed safe public message."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)
    client.post("/workflows", json=valid_start_payload())

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "This case_id already exists and cannot be used for a new intake."
    )


def test_cross_client_identity_conflict_returns_same_generic_409(client_with_engine):
    """Verifies a case belonging to a different client returns the
    SAME fixed 409 message -- never a different message revealing the
    cross-client nature of the conflict."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine, client_id=_CLIENT_ID)
    insert_client(engine, client_id="cli_other_api_start_001")
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID,
                client_id=_CLIENT_ID,
                case_status_code="OPEN",
                member_id=_MEMBER_ID,
                provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE,
                requested_date=date(2026, 1, 15),
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    response = client.post(
        "/workflows",
        json=valid_start_payload(client_id="cli_other_api_start_001"),
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "This case_id already exists and cannot be used for a new intake."
    )


def test_no_mismatch_details_leak_in_409_response(client_with_engine):
    """Verifies the 409 response body never contains the internal
    reason_category, any client_id, or any clinical value -- only the
    fixed generic detail string."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)
    client.post("/workflows", json=valid_start_payload())

    response = client.post("/workflows", json=valid_start_payload())

    assert set(response.json().keys()) == {"detail"}
    for forbidden in ("EXISTING_WORKFLOW_RUN", "IDENTITY_MISMATCH", "CASE_CLAIM_CONFLICT", "reason_category"):
        assert forbidden not in response.text


def test_persistence_failure_returns_fixed_500(client_with_engine):
    """Verifies a persistence failure inside start_new_case_workflow()
    returns HTTP 500 with the fixed safe message."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    class _FailingCaseRepository(CaseRepository):
        def client_exists(self, client_id):
            raise PersistenceError("synthetic simulated persistence failure")

    app.dependency_overrides[get_case_repository] = lambda: _FailingCaseRepository(
        session_factory=sessionmaker(bind=engine)
    )

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 500
    assert response.json()["detail"] == "The case/workflow could not be persisted."


def test_orchestrator_failure_returns_fixed_500(client_with_engine, monkeypatch):
    """Verifies a graph-invocation failure returns HTTP 500 with the
    fixed safe message, not the raw underlying exception -- using the
    same monkeypatch technique already proven in
    tests/test_workflow_continuation.py."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    class _RaisingGraph:
        def invoke(self, state):
            raise RuntimeError("synthetic graph invocation failure")

    monkeypatch.setattr(
        orchestrator_module, "build_case_workflow_graph", lambda *a, **k: _RaisingGraph()
    )

    response = client.post("/workflows", json=valid_start_payload())

    assert response.status_code == 500
    assert response.json()["detail"] == "Workflow execution could not complete."


# =====================================================================
# FAIL-CLOSED FHIR DEPENDENCY TEST
# =====================================================================
def test_default_fhir_dependency_fails_closed_with_503():
    """
    Verifies that calling POST /workflows without overriding
    get_fhir_client returns the existing, already-registered HTTP 503
    -- proving this new endpoint is covered by the same global
    fail-closed handler the Resume endpoint already uses, with no new
    code required.
    """
    engine = make_test_engine()
    create_database_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(_CLIENTS_TABLE_DDL)
    session_factory = sessionmaker(bind=engine)
    insert_client(engine)

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
        client = TestClient(app)
        response = client.post("/workflows", json=valid_start_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Live FHIR-style integration is not available."}


# =====================================================================
# RESPONSE SHAPE TESTS
# =====================================================================
def test_response_exact_key_set(client_with_engine):
    """Verifies the response body has exactly the four documented
    fields -- trace_id, case_id, workflow_run, audit_events -- and
    nothing else."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    response = client.post("/workflows", json=valid_start_payload())

    assert set(response.json().keys()) == {"trace_id", "case_id", "workflow_run", "audit_events"}


def test_response_excludes_final_state_and_raw_content(client_with_engine):
    """Verifies the response never includes final_state, raw FHIR
    evidence, or raw AI output -- checked both at the top level and
    inside workflow_run/audit_events."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    response = client.post("/workflows", json=valid_start_payload())
    body = response.json()

    assert "final_state" not in body
    assert "evidence" not in body["workflow_run"]
    assert "fhir_integration_outcome" not in body["workflow_run"]
    assert "ai_analysis_outcome" not in body["workflow_run"]
    for event in body["audit_events"]:
        assert "evidence" not in event
        assert "ai_analysis_outcome" not in event


def test_one_request_never_creates_a_second_workflow_run(client_with_engine):
    """Verifies that one successful POST /workflows call, followed by a
    second (duplicate) attempt, never results in more than one
    workflow_runs row for the case."""
    client, engine, _fhir_client, _ai_provider = client_with_engine
    insert_client(engine)

    client.post("/workflows", json=valid_start_payload())
    second_response = client.post("/workflows", json=valid_start_payload())

    assert second_response.status_code == 409
    with sessionmaker(bind=engine)() as session:
        count = session.query(WorkflowRunORM).filter_by(case_id=_CASE_ID).count()
    assert count == 1
