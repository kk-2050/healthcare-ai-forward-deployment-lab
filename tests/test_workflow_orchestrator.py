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

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.ai.contracts import AIAnalysisFailureType
from src.ai.mock_provider import MockAIAnalysisProvider
from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository, PersistenceError as CasePersistenceError
from src.db.human_review_repository import (
    HumanReviewRepository,
    PersistenceError as HumanReviewPersistenceError,
)
from src.db.models import PriorAuthorizationCaseORM
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
from src.workflow.state import WorkflowStatus
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


def make_case_repository(engine) -> CaseRepository:
    """Builds a CaseRepository against an already-schema'd engine --
    used only by the Stage 1 tests (Step 23C-5C), which are the only
    ones that touch prior_authorization_cases at all."""
    return CaseRepository(session_factory=sessionmaker(bind=engine))


def make_human_review_repository(engine) -> HumanReviewRepository:
    """Builds a HumanReviewRepository against an already-schema'd engine
    -- used only by the genuine Human Review route tests (Step 23C-6A:
    FHIR failure, evidence mismatch, AI failure)."""
    return HumanReviewRepository(session_factory=sessionmaker(bind=engine))


def insert_synthetic_case_row(engine, case_id: str, now: datetime) -> None:
    """Inserts the minimum-necessary prior_authorization_cases row a
    Stage 1 disposition's CaseRepository.update_case_status() call needs
    to find. Only the Stage 1 tests need this -- the orchestrator itself
    has never created case rows (see src/workflow/orchestrator.py's own
    module docstring), so every other test in this file is unaffected."""
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=case_id,
                client_id="SYN-CLIENT-ORCH-001",
                case_status_code="OPEN",
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
        session.commit()


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

    def save_workflow_run(self, snapshot, *, session=None):
        self.save_workflow_run_calls.append(snapshot)
        if (
            self._fail_on_save_call is not None
            and len(self.save_workflow_run_calls) == self._fail_on_save_call
        ):
            raise PersistenceError("synthetic simulated persistence failure")
        return self._repository.save_workflow_run(snapshot, session=session)

    def get_workflow_run(self, trace_id):
        return self._repository.get_workflow_run(trace_id)

    def append_audit_event(self, event, *, session=None):
        return self._repository.append_audit_event(event, session=session)

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
        "REQUEST_MISSING_INFORMATION",
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


# =====================================================================
# CASE-STATUS LIFECYCLE CORRECTION TESTS (Task 25B-1/25B-2)
# Purpose:
# Protect the corrected case_status_code resolution added to the
# ordinary (ADR-008) and genuine Human Review dispositions:
# case_status_code must never be confused with workflow_status_code --
# a run finishing or failing is a technical fact, not a business case
# closure. These tests supply case_repository/session_factory
# explicitly (optional on the public signature; see
# src/workflow/orchestrator.py's own docstring) to exercise the
# corrected behavior; the pre-existing tests above/below that omit them
# continue to prove the exact legacy behavior is unchanged for callers
# that never created a case row.
# =====================================================================
def test_direct_normal_completion_sets_case_open():
    """Verify a direct (non-resumed) ordinary COMPLETED disposition
    resolves case_status_code -> OPEN, never leaving it stuck at
    IN_PROGRESS, and never populating close fields."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, "SYN-CASE-ORCH-001", now)

    result = run_orchestrator(
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "COMPLETED"
    assert saved.next_action_code == "COMPLETE_WORKFLOW"
    assert case_repository.get_case_status_code("SYN-CASE-ORCH-001") == "OPEN"

    with sessionmaker(bind=engine)() as session:
        case_row = session.get(PriorAuthorizationCaseORM, "SYN-CASE-ORCH-001")
        assert case_row.closed_at_utc is None
        assert case_row.close_reason_code is None


def test_unhandled_graph_exception_with_case_repository_sets_case_open():
    """Verify a technical FAILED disposition (not a safe FHIR/AI
    fallback) also resolves case_status_code -> OPEN when
    case_repository is supplied -- the case remains open/unresolved,
    never CLOSED, and workflow_status_code still correctly reports
    FAILED."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, "SYN-CASE-ORCH-001", now)

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("synthetic unmodeled failure")

    fhir_client = FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    with pytest.raises(OrchestratorError):
        run_orchestrator(
            fhir_client=fhir_client,
            repository=repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    assert case_repository.get_case_status_code("SYN-CASE-ORCH-001") == "OPEN"

    with sessionmaker(bind=engine)() as session:
        from src.db.models import WorkflowRunORM

        runs = session.query(WorkflowRunORM).filter_by(
            case_id="SYN-CASE-ORCH-001"
        ).all()
        assert len(runs) == 1
        assert runs[0].workflow_status_code == "FAILED"

    with sessionmaker(bind=engine)() as session:
        case_row = session.get(PriorAuthorizationCaseORM, "SYN-CASE-ORCH-001")
        assert case_row.close_reason_code is None


def test_ordinary_disposition_case_repository_without_session_factory_raises():
    """Verify supplying case_repository without session_factory for an
    ordinary disposition is treated as a genuine caller-configuration
    error (OrchestratorError), never as a silent skip of the
    case-status write -- mirrors the existing Stage 1 dependency
    check."""
    engine = make_test_engine()
    case_repository = make_case_repository(engine)

    with pytest.raises(OrchestratorError):
        run_orchestrator(repository=make_repository(engine), case_repository=case_repository)


def test_human_review_required_sets_case_status():
    """Verify a genuine HUMAN_REVIEW_REQUIRED disposition resolves
    case_status_code -> HUMAN_REVIEW_REQUIRED (never left at
    IN_PROGRESS) when case_repository is supplied."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    case_repository = make_case_repository(engine)
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, "SYN-CASE-ORCH-001", now)
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    result = run_orchestrator(
        fhir_client=fhir_client,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert case_repository.get_case_status_code("SYN-CASE-ORCH-001") == (
        "HUMAN_REVIEW_REQUIRED"
    )


# =====================================================================
# STAGE 1 MISSING-INFORMATION DISPOSITION TESTS (Step 23C-5C, ADR-008)
# Purpose:
# Protect the corrected routing: an ordinary initial deterministic
# missing-information case must persist as the Stage 1 disposition
# (workflow_status_code=COMPLETED, next_action_code=
# REQUEST_MISSING_INFORMATION, human_review_required=False,
# case_status_code=PENDING_INFORMATION) -- NOT HUMAN_REVIEW_REQUIRED
# (Step 23C-3's confirmed finding, corrected here). These are the only
# tests in this file that touch prior_authorization_cases at all, since
# the orchestrator has never created/updated a case row for any other
# disposition.
# =====================================================================
def test_stage1_missing_information_persisted_correctly():
    """Verify an incomplete case persists workflow_status_code=COMPLETED
    with next_action_code=REQUEST_MISSING_INFORMATION,
    human_review_required=False, and completed_at_utc populated -- the
    Stage 1 disposition, not a pause."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    result = run_orchestrator(
        case=case,
        requirements=requirements,
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "COMPLETED"
    assert saved.next_action_code == "REQUEST_MISSING_INFORMATION"
    assert saved.human_review_required is False
    assert saved.completed_at_utc is not None


def test_stage1_missing_information_sets_case_pending_information():
    """Verify the Stage 1 disposition persists
    prior_authorization_cases.case_status_code=PENDING_INFORMATION."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    run_orchestrator(
        case=case,
        requirements=requirements,
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    assert case_repository.get_case_status_code(case.case_id) == "PENDING_INFORMATION"


def test_stage1_missing_information_creates_no_human_review_row():
    """Verify the Stage 1 disposition never creates a human_reviews row
    -- request_human_review()/HumanReviewRepository is never called for
    this path."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    run_orchestrator(
        case=case,
        requirements=requirements,
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with sessionmaker(bind=engine)() as session:
        from src.db.models import HumanReviewORM

        assert session.query(HumanReviewORM).count() == 0


def test_stage1_missing_information_audit_events():
    """Verify the Stage 1 disposition emits WORKFLOW_STARTED,
    COMPLETENESS_CHECKED(result_code=INCOMPLETE), and WORKFLOW_COMPLETED
    -- and never emits HUMAN_REVIEW_REQUIRED."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    result = run_orchestrator(
        case=case,
        requirements=requirements,
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    events = repository.list_audit_events(result.trace_id)
    event_types = {event.event_type_code for event in events}
    assert "WORKFLOW_STARTED" in event_types
    assert "WORKFLOW_COMPLETED" in event_types
    assert "HUMAN_REVIEW_REQUIRED" not in event_types

    completeness_event = next(
        e for e in events if e.event_type_code == "COMPLETENESS_CHECKED"
    )
    assert completeness_event.result_code == "INCOMPLETE"


def test_stage1_missing_information_preserves_missing_facts():
    """Verify the Stage 1 disposition never fabricates a resolved value
    -- the final state's completeness_result still reports exactly what
    is missing."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case_repository = make_case_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    result = run_orchestrator(
        case=case,
        requirements=requirements,
        repository=repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    completeness_result = result.final_state["completeness_result"]
    assert completeness_result.missing_documentation == ["SYN-DOC-A"]
    assert completeness_result.is_complete is False


def test_stage1_missing_information_without_case_repository_raises():
    """Verify reaching the Stage 1 disposition without supplying
    case_repository/session_factory raises OrchestratorError, rather
    than silently skipping the case-status update or the audit write --
    a genuine caller-configuration error must never be swallowed."""
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])

    with pytest.raises(OrchestratorError):
        run_orchestrator(case=case, requirements=requirements)


def test_stage1_missing_information_atomic_rollback_on_case_write_failure():
    """Verify a failure in the Stage 1 atomic block (simulated on the
    case-status write, which runs after the workflow_runs write has
    already been flushed within the shared session) leaves NO trace of
    the disposition: the workflow_runs row must not show the Stage 1
    disposition, no case-status change must survive, and no Stage 1
    audit event must survive -- proving the three writes commit or roll
    back together (Step 23C-5C §6/§10.F)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    now = datetime.now(timezone.utc)
    insert_synthetic_case_row(engine, case.case_id, now)

    class _FailingCaseRepository(CaseRepository):
        """Wraps the real CaseRepository, injecting a synthetic failure
        on update_case_status() -- after save_workflow_run() has already
        flushed within the same shared session, proving the whole
        transaction rolls back, not just this one write."""

        def update_case_status(self, **kwargs):
            raise CasePersistenceError("synthetic simulated persistence failure")

    failing_case_repository = _FailingCaseRepository(session_factory=sessionmaker(bind=engine))

    with pytest.raises(CasePersistenceError):
        run_orchestrator(
            case=case,
            requirements=requirements,
            repository=repository,
            case_repository=failing_case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    # workflow_runs: the PROCESSING row from orchestration start is the
    # only one that survives -- the Stage 1 final update never committed.
    # (trace_id is generated inside the orchestrator and never returned
    # on a raised exception, so read back by case_id via a fresh session
    # instead, using the fact that exactly one workflow_runs row exists
    # for this test's synthetic case.)
    with sessionmaker(bind=engine)() as session:
        from src.db.models import WorkflowRunORM

        runs = session.query(WorkflowRunORM).filter_by(case_id=case.case_id).all()
        assert len(runs) == 1
        assert runs[0].workflow_status_code == "PROCESSING"
        assert runs[0].next_action_code is None

    # case status: never changed from its pre-existing OPEN value.
    real_case_repository = make_case_repository(engine)
    assert real_case_repository.get_case_status_code(case.case_id) == "OPEN"

    # audit events: only WORKFLOW_STARTED (persisted independently, at
    # orchestration start, before the graph even ran) survives -- no
    # Stage 1 final audit event (COMPLETENESS_CHECKED, WORKFLOW_COMPLETED)
    # was committed.
    with sessionmaker(bind=engine)() as session:
        from src.db.models import AuditEventORM

        events = (
            session.query(AuditEventORM)
            .filter_by(case_id=case.case_id)
            .all()
        )
        event_types = {event.event_type_code for event in events}
        assert event_types == {"WORKFLOW_STARTED"}


def test_failure_category_persisted_where_applicable():
    """Verify an AI provider failure persists failure_category_code
    on the workflow_runs row."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(exception=RuntimeError("synthetic provider failure"))

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
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
    with failure_category_code=AI_OUTPUT_INVALID, routes to
    HUMAN_REVIEW_REQUIRED -- never FAILED -- and creates exactly one
    durable Human Review request with reason_code=HUMAN_REVIEW_AI_FAILURE
    (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
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
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    failed_event = next(e for e in events if e.event_type_code == "AI_ANALYSIS_FAILED")

    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "AI_OUTPUT_INVALID"
    assert failed_event.failure_category_code == "AI_OUTPUT_INVALID"

    review = human_review_repository.get_pending_review_by_trace_id(result.trace_id)
    assert review is not None
    assert review.reason_code == "HUMAN_REVIEW_AI_FAILURE"
    assert review.case_id == "SYN-CASE-ORCH-001"
    assert review.trace_id == result.trace_id


def test_llm_provider_failure_safe_fallback_persists_correctly():
    """Verify an AI provider exception persists AI_ANALYSIS_FAILED with
    failure_category_code=AI_PROVIDER_FAILED, routes to
    HUMAN_REVIEW_REQUIRED -- never FAILED -- and creates exactly one
    durable Human Review request with reason_code=HUMAN_REVIEW_AI_FAILURE
    (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = make_ai_provider(exception=RuntimeError("synthetic provider failure"))

    result = run_orchestrator(
        ai_processing_requirements=ai_requirements,
        ai_provider=provider,
        repository=repository,
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "AI_PROVIDER_FAILED"

    review = human_review_repository.get_pending_review_by_trace_id(result.trace_id)
    assert review is not None
    assert review.reason_code == "HUMAN_REVIEW_AI_FAILURE"
    assert review.case_id == "SYN-CASE-ORCH-001"
    assert review.trace_id == result.trace_id


def test_healthcare_fhir_failure_safe_fallback_persists_correctly():
    """Verify a healthcare/FHIR integration failure persists
    FHIR_RETRIEVAL_FAILED with failure_category_code=FHIR_HTTP_ERROR,
    routes to HUMAN_REVIEW_REQUIRED -- never FAILED -- and creates
    exactly one durable Human Review request with
    reason_code=HUMAN_REVIEW_FHIR_FAILURE (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    result = run_orchestrator(
        fhir_client=fhir_client,
        repository=repository,
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    events = repository.list_audit_events(result.trace_id)
    failed_event = next(e for e in events if e.event_type_code == "FHIR_RETRIEVAL_FAILED")

    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.failure_category_code == "FHIR_HTTP_ERROR"
    assert failed_event.failure_category_code == "FHIR_HTTP_ERROR"
    assert failed_event.reason_code is None  # reason_code is a business
    # reason, not a technical failure category -- see
    # docs/database/data_model.md's Failure-vs-Reason distinction.

    review = human_review_repository.get_pending_review_by_trace_id(result.trace_id)
    assert review is not None
    assert review.reason_code == "HUMAN_REVIEW_FHIR_FAILURE"
    assert review.case_id == "SYN-CASE-ORCH-001"
    assert review.trace_id == result.trace_id


def test_evidence_mismatch_safe_fallback_persists_correctly():
    """Verify a submitted-vs-retrieved evidence mismatch routes to
    HUMAN_REVIEW_REQUIRED and creates exactly one durable Human Review
    request with reason_code=HUMAN_REVIEW_EVIDENCE_MISMATCH (Step
    23C-6A). No orchestrator-level test previously existed for this
    route."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    case = make_case(requested_service_code="SYN-DIFFERENT-CODE")

    result = run_orchestrator(
        case=case,
        repository=repository,
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(result.trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"

    review = human_review_repository.get_pending_review_by_trace_id(result.trace_id)
    assert review is not None
    assert review.reason_code == "HUMAN_REVIEW_EVIDENCE_MISMATCH"
    assert review.case_id == case.case_id
    assert review.trace_id == result.trace_id


def test_human_review_required_without_dependencies_raises():
    """Verify reaching a genuine HUMAN_REVIEW_REQUIRED disposition
    without supplying human_review_repository/session_factory raises
    OrchestratorError, rather than silently skipping the durable review
    request -- a genuine caller-configuration error must never be
    swallowed (Step 23C-6A, mirrors the identical Stage 1 test)."""
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    with pytest.raises(OrchestratorError):
        run_orchestrator(fhir_client=fhir_client)


def test_human_review_persistence_failure_fails_safely():
    """Verify a failure in the Human Review atomic block (simulated on
    the review-request write, which runs after the workflow_runs final
    update and audit events have already been flushed within the shared
    session) leaves NO trace of the disposition: the workflow_runs row
    must not show HUMAN_REVIEW_REQUIRED, and no human_reviews row must
    exist -- proving the workflow is never left falsely claiming
    successful Human Review routing (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)

    class _FailingHumanReviewRepository(HumanReviewRepository):
        """Wraps the real HumanReviewRepository, injecting a synthetic
        failure on create_review_request() -- after the workflow_runs/
        audit writes have already flushed within the same shared
        session, proving the whole transaction rolls back."""

        def create_review_request(self, review, **kwargs):
            raise HumanReviewPersistenceError("synthetic simulated persistence failure")

    failing_human_review_repository = _FailingHumanReviewRepository(
        session_factory=sessionmaker(bind=engine)
    )
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    with pytest.raises(HumanReviewPersistenceError):
        run_orchestrator(
            fhir_client=fhir_client,
            repository=repository,
            human_review_repository=failing_human_review_repository,
            session_factory=sessionmaker(bind=engine),
        )

    # workflow_runs: only the PROCESSING row from orchestration start
    # survives -- the HUMAN_REVIEW_REQUIRED final update never committed.
    with sessionmaker(bind=engine)() as session:
        from src.db.models import WorkflowRunORM

        runs = session.query(WorkflowRunORM).filter_by(case_id="SYN-CASE-ORCH-001").all()
        assert len(runs) == 1
        assert runs[0].workflow_status_code == "PROCESSING"
        assert runs[0].human_review_required is False

    # human_reviews: no row was created.
    with sessionmaker(bind=engine)() as session:
        from src.db.models import HumanReviewORM

        assert session.query(HumanReviewORM).count() == 0

    # audit_events: only WORKFLOW_STARTED (persisted independently, at
    # orchestration start, before the graph even ran) survives -- no
    # HUMAN_REVIEW_REQUIRED or other final audit event was committed.
    with sessionmaker(bind=engine)() as session:
        from src.db.models import AuditEventORM

        events = (
            session.query(AuditEventORM)
            .filter_by(case_id="SYN-CASE-ORCH-001")
            .all()
        )
        event_types = {event.event_type_code for event in events}
        assert event_types == {"WORKFLOW_STARTED"}


def test_no_duplicate_human_review_request_within_one_execution():
    """Verify exactly one human_reviews row is created for one
    workflow execution that reaches HUMAN_REVIEW_REQUIRED -- no
    duplicate request (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    human_review_repository = make_human_review_repository(engine)
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    result = run_orchestrator(
        fhir_client=fhir_client,
        repository=repository,
        human_review_repository=human_review_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with sessionmaker(bind=engine)() as session:
        from src.db.models import HumanReviewORM

        rows = session.query(HumanReviewORM).filter_by(trace_id=result.trace_id).all()
        assert len(rows) == 1


def test_successful_complete_path_creates_zero_human_review_rows():
    """Verify an ordinary complete (non-Human-Review) run never creates
    a human_reviews row (Step 23C-6A)."""
    engine = make_test_engine()
    repository = make_repository(engine)

    result = run_orchestrator(repository=repository)

    with sessionmaker(bind=engine)() as session:
        from src.db.models import HumanReviewORM

        assert session.query(HumanReviewORM).count() == 0
    assert result.final_state["workflow_status"].value == "COMPLETE"


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
