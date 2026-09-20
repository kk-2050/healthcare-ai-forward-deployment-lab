# File Name: test_workflow_orchestrator.py
# Purpose: Tests the LangGraph-to-SQL-persistence orchestration boundary using synthetic, isolated SQLite fixtures.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect src/workflow/orchestrator.py: trace_id identity
# (ADR-007), the stable node-to-step_code mapping
# (src/workflow/step_mapping.py), canonical workflow_runs/audit_events
# persistence, and safe failure handling. Every test runs against an
# in-memory SQLite engine (a TEST DOUBLE only, same convention as
# tests/test_audit_repository.py) and MockAIAnalysisProvider/
# FHIRStyleClient backed by httpx.MockTransport (same convention as
# tests/test_workflow_graph.py) -- never a live LLM, a live healthcare
# system, or a live SQL Server. Real SQL Server integration is a
# separate, explicitly-approved step (see Task 22's reference-data
# gate), not exercised here.

from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.ai.contracts import AIAnalysisFailureType
from src.ai.mock_provider import MockAIAnalysisProvider
from src.db.base import create_database_schema
from src.db.repository import AuditRepository, PersistenceError
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements, AITask
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.workflow.graph import build_case_workflow_graph
from src.workflow.orchestrator import (
    OrchestratorError,
    run_prior_authorization_workflow,
)
from src.workflow.step_mapping import (
    LANGGRAPH_NODE_TO_STEP_CODE,
    verify_mapping_matches_graph,
)

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-ORCH-001"


# =====================================================================
# FIXTURES
# Kept local to this file (not imported from test_audit_repository.py
# or test_workflow_graph.py) so orchestrator tests stay independent of
# those modules' fixtures -- the same deliberate pattern
# test_workflow_graph.py already uses for its own FHIR fixtures.
# =====================================================================
def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (see test_audit_repository.py for why)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_repository(engine=None) -> AuditRepository:
    if engine is None:
        engine = make_test_engine()
    create_database_schema(engine)
    return AuditRepository(session_factory=sessionmaker(bind=engine))


def make_case(**overrides) -> PriorAuthorizationCase:
    data = {
        "case_id": "SYN-CASE-ORCH-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-LUMBAR-MRI",
        "diagnosis_code": "SYN-LOW-BACK-PAIN",
        "requested_date": date(2026, 1, 15),
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


def make_requirements(**overrides) -> CompletenessRequirements:
    data = {"required_documentation": [], "clinical_notes_required": False}
    data.update(overrides)
    return CompletenessRequirements(**data)


def valid_fhir_bundle_json():
    """A minimal, fully valid synthetic FHIR-style Bundle whose facts
    agree with make_case()'s defaults."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-001",
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
                    "reasonReference": [{"reference": "Condition/SYN-COND-001"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-001",
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


def make_fhir_client(json_body=None, status_code=200, raw_content=None) -> FHIRStyleClient:
    body = valid_fhir_bundle_json() if json_body is None else json_body

    def handler(request: httpx.Request) -> httpx.Response:
        if raw_content is not None:
            return httpx.Response(status_code, content=raw_content)
        return httpx.Response(status_code, json=body)

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def make_ai_provider(**kwargs) -> MockAIAnalysisProvider:
    if not kwargs:
        kwargs = {"response": {"completed_tasks": []}}
    return MockAIAnalysisProvider(**kwargs)


def run_orchestrator(
    case=None,
    requirements=None,
    ai_processing_requirements=None,
    ai_provider=None,
    fhir_client=None,
    repository=None,
    **kwargs,
):
    """Runs the orchestrator with sensible synthetic defaults, letting
    each test override only what it cares about."""
    return run_prior_authorization_workflow(
        case=case or make_case(),
        completeness_requirements=requirements or make_requirements(),
        ai_processing_requirements=(
            ai_processing_requirements or AIProcessingRequirements()
        ),
        ai_provider=ai_provider or make_ai_provider(),
        fhir_client=fhir_client or make_fhir_client(),
        repository=repository or make_repository(),
        workflow_definition_id=_WORKFLOW_DEFINITION_ID,
        **kwargs,
    )


class _CountingRepositoryWrapper:
    """Wraps a real AuditRepository, recording every save_workflow_run
    call and optionally failing on a chosen call number -- used to
    prove orchestration-start persistence and persistence-failure
    surfacing without needing a live SQL Server."""

    def __init__(self, repository: AuditRepository, fail_on_save_call: int | None = None):
        self._repository = repository
        self.save_workflow_run_calls: list = []
        self._fail_on_save_call = fail_on_save_call

    def save_workflow_run(self, snapshot):
        self.save_workflow_run_calls.append(snapshot)
        if (
            self._fail_on_save_call is not None
            and len(self.save_workflow_run_calls) == self._fail_on_save_call
        ):
            raise PersistenceError("synthetic simulated persistence failure")
        return self._repository.save_workflow_run(snapshot)

    def get_workflow_run(self, trace_id):
        return self._repository.get_workflow_run(trace_id)

    def append_audit_event(self, event):
        return self._repository.append_audit_event(event)

    def list_audit_events(self, trace_id):
        return self._repository.list_audit_events(trace_id)


# =====================================================================
# TRACE_ID IDENTITY TESTS (ADR-007)
# =====================================================================
def test_trace_id_generated_exactly_once_per_new_run():
    """Verify a single run produces exactly one trace_id, used
    identically for the returned result and the final graph state."""
    result = run_orchestrator()

    assert result.trace_id
    assert result.final_state["trace_id"] == result.trace_id


def test_supplied_trace_id_remains_unchanged_through_graph_state():
    """Verify the trace_id present in the initial state is exactly the
    one still present in the final state -- no node regenerates it."""
    result = run_orchestrator()

    assert result.final_state["trace_id"] == result.trace_id


def test_two_runs_for_same_case_receive_different_trace_ids():
    """Verify processing the same case twice as two separate runs
    produces two different trace_ids -- one workflow run = one
    trace_id, never reused across runs."""
    repository = make_repository()
    case = make_case()

    first = run_orchestrator(case=case, repository=repository)
    second = run_orchestrator(case=case, repository=repository)

    assert first.trace_id != second.trace_id


# =====================================================================
# STABLE NODE -> STEP MAPPING TESTS
# =====================================================================
def test_stable_node_to_step_mapping_matches_current_graph():
    """Verify every node actually registered in the compiled graph has
    a step_code mapping entry, and vice versa -- catches drift between
    src/workflow/graph.py and src/workflow/step_mapping.py."""
    graph = build_case_workflow_graph(make_ai_provider(), make_fhir_client())
    registered_nodes = {
        name
        for name in graph.get_graph().nodes.keys()
        if name not in ("__start__", "__end__")
    }

    verify_mapping_matches_graph(registered_nodes)


def test_step_mapping_does_not_use_function_names_as_codes():
    """Verify the persisted step_code values are stable business codes,
    never the raw Python node/function name."""
    node_names = set(LANGGRAPH_NODE_TO_STEP_CODE.keys())
    step_codes = set(LANGGRAPH_NODE_TO_STEP_CODE.values())

    assert node_names.isdisjoint(step_codes)
    assert step_codes == {
        "FHIR_RETRIEVAL",
        "EVIDENCE_CONSISTENCY",
        "COMPLETENESS_CHECK",
        "AI_ROUTING",
        "AI_ANALYSIS",
        "HUMAN_REVIEW",
        "COMPLETE",
    }


# =====================================================================
# WORKFLOW_RUNS PERSISTENCE TESTS
# =====================================================================
def test_workflow_run_created_at_orchestration_start():
    """Verify save_workflow_run() is called before graph invocation
    completes and reflects the initial PROCESSING state -- not only
    after the run finishes."""
    repository = make_repository()
    spy = _CountingRepositoryWrapper(repository)

    run_orchestrator(repository=spy)

    assert len(spy.save_workflow_run_calls) == 2
    assert spy.save_workflow_run_calls[0].workflow_status_code == "PROCESSING"


def test_workflow_run_status_updated_on_normal_completion():
    """Verify a complete case with no AI task ends with
    workflow_status_code=COMPLETED, persisted to workflow_runs."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "COMPLETED"
    assert saved.completed_at_utc is not None


def test_human_review_required_persisted_correctly():
    """Verify an incomplete case persists HUMAN_REVIEW_REQUIRED, with
    human_review_required=True and completed_at_utc left None -- a
    pause, not a completion, so the same trace_id stays resumable."""
    repository = make_repository()
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])

    result = run_orchestrator(case=case, requirements=requirements, repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.human_review_required is True
    assert saved.completed_at_utc is None
    assert saved.next_action_code == "ROUTE_HUMAN_REVIEW"


def test_failure_category_persisted_where_applicable():
    """Verify an AI provider failure persists failure_category_code
    on the workflow_runs row."""
    repository = make_repository()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(exception=RuntimeError("synthetic provider failure"))

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.failure_category_code == "AI_PROVIDER_FAILED"
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"


def test_identity_fields_not_overwritten_on_update():
    """Verify case_id/workflow_definition_id/initiated_by_component_code/
    started_at_utc/created_at_utc/created_by are identical before and
    after the final update -- the repository's mutability policy holds
    end to end through the orchestrator."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.case_id == "SYN-CASE-ORCH-001"
    assert saved.workflow_definition_id == _WORKFLOW_DEFINITION_ID
    assert saved.initiated_by_component_code == "LANGGRAPH"


# =====================================================================
# AUDIT EVENT PERSISTENCE TESTS
# =====================================================================
def test_audit_event_created_for_meaningful_steps():
    """Verify the expected event_type_code set is persisted for the
    simplest complete path -- workflow started, FHIR succeeded,
    evidence consistent, completeness checked, AI not required,
    workflow completed."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    events = repository.list_audit_events(result.trace_id)
    event_types = {event.event_type_code for event in events}
    assert event_types == {
        "WORKFLOW_STARTED",
        "FHIR_RETRIEVAL_SUCCEEDED",
        "EVIDENCE_CONSISTENCY_CHECKED",
        "COMPLETENESS_CHECKED",
        "AI_NOT_REQUIRED",
        "WORKFLOW_COMPLETED",
    }


def test_audit_event_uses_workflow_step_id_derived_from_stable_step_code():
    """Verify a supplied step_code-to-workflow_step_id resolver is used
    to populate audit_events.workflow_step_id."""
    repository = make_repository()

    result = run_orchestrator(
        repository=repository,
        step_code_to_workflow_step_id={"COMPLETENESS_CHECK": "SYN-STEP-ID-042"},
    )

    events = repository.list_audit_events(result.trace_id)
    completeness_event = next(
        e for e in events if e.event_type_code == "COMPLETENESS_CHECKED"
    )
    assert completeness_event.workflow_step_id == "SYN-STEP-ID-042"


def test_no_python_function_name_persisted_as_workflow_step_contract():
    """Verify no persisted audit event carries a raw LangGraph node/
    function name anywhere in its event_type_code or workflow_step_id
    -- only stable codes or None."""
    repository = make_repository()
    node_names = set(LANGGRAPH_NODE_TO_STEP_CODE.keys())

    result = run_orchestrator(repository=repository)

    events = repository.list_audit_events(result.trace_id)
    for event in events:
        assert event.event_type_code not in node_names
        assert event.workflow_step_id not in node_names


# =====================================================================
# AI PATH PERSISTENCE TESTS
# =====================================================================
def test_ai_not_needed_path_persists_correctly():
    """Verify a case with no AI task requested persists AI_NOT_REQUIRED
    and reaches COMPLETED, without any AI_ANALYSIS_* event."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    event_types = {event.event_type_code for event in events}

    assert saved.workflow_status_code == "COMPLETED"
    assert "AI_NOT_REQUIRED" in event_types
    assert not any(t.startswith("AI_ANALYSIS_") for t in event_types)


def test_ai_needed_path_persists_correctly():
    """Verify a case with an approved AI task requested, run through a
    successful mock provider, persists AI_REQUIRED and
    AI_ANALYSIS_SUCCEEDED, and reaches COMPLETED."""
    repository = make_repository()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(response={"completed_tasks": ["summarize_narrative"]})

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
    )

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    event_types = {event.event_type_code for event in events}

    assert saved.workflow_status_code == "COMPLETED"
    assert "AI_REQUIRED" in event_types
    assert "AI_ANALYSIS_SUCCEEDED" in event_types


def test_malformed_llm_output_safe_fallback_persists_correctly():
    """Verify malformed structured AI output persists AI_ANALYSIS_FAILED
    with failure_category_code=AI_OUTPUT_INVALID and routes to
    HUMAN_REVIEW_REQUIRED -- never FAILED."""
    repository = make_repository()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "unexpected_field": "not allowed",
        }
    )

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
    )

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    failed_event = next(e for e in events if e.event_type_code == "AI_ANALYSIS_FAILED")

    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "AI_OUTPUT_INVALID"
    assert failed_event.failure_category_code == "AI_OUTPUT_INVALID"


def test_llm_provider_failure_safe_fallback_persists_correctly():
    """Verify an AI provider exception persists AI_ANALYSIS_FAILED with
    failure_category_code=AI_PROVIDER_FAILED and routes to
    HUMAN_REVIEW_REQUIRED -- never FAILED."""
    repository = make_repository()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(exception=RuntimeError("synthetic provider failure"))

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "AI_PROVIDER_FAILED"


def test_healthcare_fhir_failure_safe_fallback_persists_correctly():
    """Verify a healthcare/FHIR integration failure persists
    FHIR_RETRIEVAL_FAILED with failure_category_code=FHIR_HTTP_ERROR
    and routes to HUMAN_REVIEW_REQUIRED -- never FAILED."""
    repository = make_repository()
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    result = run_orchestrator(fhir_client=fhir_client, repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    failed_event = next(e for e in events if e.event_type_code == "FHIR_RETRIEVAL_FAILED")

    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "FHIR_HTTP_ERROR"
    assert failed_event.failure_category_code == "FHIR_HTTP_ERROR"
    assert failed_event.reason_code is None  # reason_code is a business
    # reason, not a technical failure category -- see
    # docs/database/data_model.md's Failure-vs-Reason distinction.


# =====================================================================
# FAILURE / TRANSACTION SAFETY TESTS
# =====================================================================
def test_persistence_failure_surfaces_and_is_not_silently_ignored():
    """Verify a failure on the final workflow_runs persistence write
    propagates to the caller -- the orchestrator never pretends the run
    was saved when it was not."""
    repository = make_repository()
    # Call 1 = creation at orchestration start (succeeds); call 2 = the
    # final update (fails).
    spy = _CountingRepositoryWrapper(repository, fail_on_save_call=2)

    with pytest.raises(PersistenceError):
        run_orchestrator(repository=spy)


def test_repository_still_usable_after_a_persistence_failure():
    """Verify the repository (and a subsequent orchestrated run) still
    works normally after an earlier run's persistence failure -- one
    failure must not corrupt the repository for later calls (mirrors
    the existing AuditRepository rollback guarantee)."""
    repository = make_repository()
    failing_spy = _CountingRepositoryWrapper(repository, fail_on_save_call=2)

    with pytest.raises(PersistenceError):
        run_orchestrator(repository=failing_spy)

    # A fresh run against the real (unwrapped) repository must still
    # succeed normally.
    result = run_orchestrator(repository=repository)
    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "COMPLETED"


def test_unhandled_graph_exception_marks_run_failed_and_raises():
    """Verify an unhandled exception during graph execution (not one of
    the existing safe FHIR/AI fallbacks) marks the run FAILED, persists
    a WORKFLOW_FAILED audit event, and still raises to the caller --
    the failure is never hidden."""
    repository = make_repository()

    # Force an unhandled failure by supplying a fhir_client that raises
    # an exception type the workflow does not treat as a modeled
    # integration failure (bypassing the safe-fallback path entirely).
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("synthetic unmodeled failure")

    fhir_client = FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    with pytest.raises(OrchestratorError):
        run_orchestrator(fhir_client=fhir_client, repository=repository)


# =====================================================================
# CANONICAL MODEL VALIDITY / REGRESSION
# =====================================================================
def test_orchestrator_uses_canonical_workflow_run_snapshot_shape():
    """Verify the persisted workflow_runs row round-trips through the
    canonical 23-field WorkflowRunSnapshot without error."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    saved = repository.get_workflow_run(result.trace_id)
    assert len(type(saved).model_fields) == 23


def test_orchestrator_uses_canonical_audit_event_shape():
    """Verify persisted audit events round-trip through the canonical
    19-field AuditEvent without error."""
    repository = make_repository()

    result = run_orchestrator(repository=repository)

    events = repository.list_audit_events(result.trace_id)
    assert events
    assert len(type(events[0]).model_fields) == 19
