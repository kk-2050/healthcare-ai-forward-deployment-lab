# File Name: test_workflow_orchestrator_integration.py
# Purpose: Opt-in real SQL Server integration test for the LangGraph-to-persistence orchestration boundary.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# Unlike every other test in this project, this file is NOT run by a
# plain `pytest` invocation -- it requires a real local SQL Server
# instance, already migrated to revision b9aba5b07ac8, with the stable
# Phase 1 reference catalog already loaded via
# `python -m src.db.reference_data` (see that module). It is skipped
# entirely unless the RUN_SQL_SERVER_INTEGRATION_TESTS environment
# variable is set to "1" -- ordinary `pytest` runs never touch real SQL
# Server, never require it, and never modify it.
#
# This test creates exactly one small, clearly-synthetic business
# fixture (one client, one case) -- kept entirely separate from the
# stable reference-data catalog (src/db/reference_data.py never creates
# a client or a case; see its own tests for that separation) -- and
# always cleans up everything it wrote, in FK-safe reverse dependency
# order, in a finally block, whether the test passes or fails.
#
# No real external FHIR service or Azure OpenAI is ever called here:
# the FHIR client is backed by httpx.MockTransport, and the AI-not-
# needed path means the AI provider is never invoked at all -- this
# test validates SQL persistence only, per Task 22's explicit scope.

import os
from datetime import date, datetime, timezone

import httpx
import pytest
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from src.config.database import load_database_settings
from src.db.engine import create_sql_server_engine
from src.db.repository import AuditRepository
from src.db.reference_data import (
    resolve_step_code_to_workflow_step_id,
    workflow_definition_id as get_workflow_definition_id,
)
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.workflow.orchestrator import run_prior_authorization_workflow

_ENV_FLAG = "RUN_SQL_SERVER_INTEGRATION_TESTS"
_ENV_PATH = None  # loaded via load_dotenv() with no explicit path, same as other scripts

pytestmark = pytest.mark.skipif(
    os.environ.get(_ENV_FLAG) != "1",
    reason=(
        f"Opt-in real SQL Server integration test -- set {_ENV_FLAG}=1 to run. "
        "Requires SQL Server already migrated to b9aba5b07ac8 with reference "
        "data already loaded via src/db/reference_data.py."
    ),
)

_SYNTHETIC_CLIENT_ID = "cli_integration_test_001"
_SYNTHETIC_CASE_ID = "case_integration_test_001"


def _make_session_factory():
    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    return sessionmaker(bind=engine), engine


def _insert_synthetic_client(session, now) -> None:
    """Raw SQL insert -- clients has no SQLAlchemy ORM class (Wave 1,
    raw DDL only; see src/db/models.py's Foreign Key Policy)."""
    session.execute(
        sa.text(
            "INSERT INTO clients "
            "(client_id, client_code, client_name, client_type_code, "
            "default_country_code, default_time_zone, is_active, metadata_json, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:client_id, :client_code, :client_name, NULL, NULL, NULL, 1, NULL, "
            ":now, 'SYSTEM', :now, 'SYSTEM', 0)"
        ),
        {
            "client_id": _SYNTHETIC_CLIENT_ID,
            "client_code": "INTEGRATION_TEST_CLIENT",
            "client_name": "Integration Test Client (synthetic)",
            "now": now,
        },
    )


def _insert_synthetic_case(session, now) -> None:
    """Raw SQL insert -- kept consistent with the raw-SQL client insert
    above rather than mixing ORM and raw SQL for two rows in the same
    fixture; prior_authorization_cases does have an ORM class
    (PriorAuthorizationCaseORM), but this fixture is deliberately
    self-contained and easy to read top-to-bottom."""
    session.execute(
        sa.text(
            "INSERT INTO prior_authorization_cases "
            "(case_id, client_id, department_id, location_id, case_status_code, "
            "member_id, provider_id, requested_service_code, requested_date, "
            "source_component_code, opened_at_utc, closed_at_utc, closed_by, "
            "close_reason_code, close_reason_text, clinical_notes_present, "
            "schema_version, metadata_json, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:case_id, :client_id, NULL, NULL, 'OPEN', "
            ":member_id, :provider_id, :requested_service_code, :requested_date, "
            "'FASTAPI', :now, NULL, NULL, NULL, NULL, 0, "
            "'1', NULL, :now, 'SYSTEM', :now, 'SYSTEM', 0)"
        ),
        {
            "case_id": _SYNTHETIC_CASE_ID,
            "client_id": _SYNTHETIC_CLIENT_ID,
            "member_id": "SYN-MEMBER-INTEGRATION-001",
            "provider_id": "SYN-PROVIDER-INTEGRATION-001",
            "requested_service_code": "SYN-LUMBAR-MRI",
            "requested_date": date(2026, 1, 15),
            "now": now,
        },
    )


def _cleanup_synthetic_rows(session, trace_id: str | None) -> None:
    """Deletes synthetic rows in FK-safe reverse dependency order:
    audit_events -> workflow_runs -> prior_authorization_cases ->
    client. Stable reference/config rows are never touched here."""
    if trace_id is not None:
        session.execute(
            sa.text("DELETE FROM audit_events WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        session.execute(
            sa.text("DELETE FROM workflow_runs WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
    session.execute(
        sa.text(
            "DELETE FROM prior_authorization_cases WHERE case_id = :case_id"
        ),
        {"case_id": _SYNTHETIC_CASE_ID},
    )
    session.execute(
        sa.text("DELETE FROM clients WHERE client_id = :client_id"),
        {"client_id": _SYNTHETIC_CLIENT_ID},
    )
    session.commit()


def make_fhir_client() -> FHIRStyleClient:
    """Mocked FHIR-style client -- httpx.MockTransport, never a real
    network call. Facts agree with the synthetic case below."""
    body = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-INTEGRATION-001",
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
                    "reasonReference": [
                        {"reference": "Condition/SYN-COND-INTEGRATION-001"}
                    ],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-INTEGRATION-001",
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

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


class _NeverCalledAIProvider:
    """Fails the test loudly if the AI provider is ever invoked -- the
    AI-not-needed path must never call it."""

    def analyze(self, request):
        raise AssertionError(
            "AI provider was called on the AI-not-needed integration test path"
        )


def test_ai_not_needed_path_persists_correctly_against_real_sql_server():
    """
    The exact first real SQL Server integration test (see Task 22's
    reference-data closure report): synthetic case, mocked FHIR
    success, AI not needed, normal completion. Verifies exactly one
    workflow_runs row (COMPLETED, COMPLETE_WORKFLOW, completed_at_utc
    populated, human_review_required=False), exactly six audit_events
    sharing one trace_id, workflow_step_id resolved through the stable
    step mapping, and no raw clinical/LLM payload persisted. Cleans up
    every synthetic row it wrote, in FK-safe order, even on failure.
    """
    session_factory, engine = _make_session_factory()
    session = session_factory()
    now = datetime.now(timezone.utc)
    trace_id: str | None = None

    try:
        # 1. Verify required stable reference rows exist -- fail with a
        # clear message rather than silently inventing them here.
        step_mapping = resolve_step_code_to_workflow_step_id(session)
        assert step_mapping, (
            "No workflow_definition_steps rows found. Run "
            "`python -m src.db.reference_data` (reviewed and approved) "
            "before running this integration test."
        )

        # 2. Insert the synthetic client/case fixture.
        _insert_synthetic_client(session, now)
        _insert_synthetic_case(session, now)
        session.commit()

        # 3/4. Mocked FHIR behavior; AI-not-needed path.
        repository = AuditRepository(session_factory=session_factory)
        result = run_prior_authorization_workflow(
            case=PriorAuthorizationCase(
                case_id=_SYNTHETIC_CASE_ID,
                member_id="SYN-MEMBER-INTEGRATION-001",
                provider_id="SYN-PROVIDER-INTEGRATION-001",
                requested_service_code="SYN-LUMBAR-MRI",
                diagnosis_code="SYN-LOW-BACK-PAIN",
                requested_date=date(2026, 1, 15),
            ),
            completeness_requirements=CompletenessRequirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=_NeverCalledAIProvider(),
            fhir_client=make_fhir_client(),
            repository=repository,
            workflow_definition_id=get_workflow_definition_id(),
            step_code_to_workflow_step_id=step_mapping,
        )
        trace_id = result.trace_id

        # 6-10. Verify workflow_runs.
        saved_run = repository.get_workflow_run(trace_id)
        assert saved_run is not None
        assert saved_run.workflow_status_code == "COMPLETED"
        assert saved_run.next_action_code == "COMPLETE_WORKFLOW"
        assert saved_run.completed_at_utc is not None
        assert saved_run.human_review_required is False

        # 11-12. Verify audit_events.
        events = repository.list_audit_events(trace_id)
        assert len(events) == 6
        assert {event.trace_id for event in events} == {trace_id}

        # 13. Verify workflow_step_id resolves through the stable
        # mapping (never a raw node/function name).
        completeness_event = next(
            e for e in events if e.event_type_code == "COMPLETENESS_CHECKED"
        )
        assert (
            completeness_event.workflow_step_id
            == step_mapping["COMPLETENESS_CHECK"]
        )

        # 14. Verify no raw clinical/LLM payload was persisted.
        assert all(event.metadata_json is None for event in events)

    finally:
        # 15. Clean up synthetic rows -- always, pass or fail.
        cleanup_session = session_factory()
        _cleanup_synthetic_rows(cleanup_session, trace_id)
        cleanup_session.close()
        session.close()
        engine.dispose()
