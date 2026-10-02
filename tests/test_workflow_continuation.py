# File Name: test_workflow_continuation.py
# Purpose: Tests the same-run/same-trace resume continuation core (src/workflow/orchestrator.py's internal continuation helper) and resume_workflow()'s public end-to-end entry point (src/workflow/resume_service.py) using an in-memory SQLite test double.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect Step 24B-4A: the actual graph continuation logic
# (_continue_claimed_workflow_processing() in orchestrator.py -- an
# INTERNAL helper, never a supported public entry point) and
# resume_workflow() (resume_service.py), the sole supported
# application-level end-to-end continuation entry point, which owns the
# full authorization boundary (eligibility validation, the Human Review
# CONTINUE_WORKFLOW check, case-identity validation, and the atomic
# resume claim -- validate_and_claim_resume()) before continuation ever
# runs. Every test runs against an in-memory SQLite engine and
# MockAIAnalysisProvider/FHIRStyleClient backed by httpx.MockTransport
# (same convention as tests/test_workflow_orchestrator.py) -- never a
# live LLM, a live healthcare system, or a live SQL Server.
#
# Scope boundary: these tests exercise the SAME-RUN/SAME-TRACE
# APPLICATION-LEVEL CONTINUATION architecture only (Task 24 Option A --
# see docs/decisions/ADR-007 and the Task 24A/24B-1 design lock). They
# never exercise real FHIR/AI provider configuration, Stage 2
# unresolved missing-information routing (not implemented), or the
# resume HTTP endpoint (not implemented -- Task 24B-4A is the
# continuation core only).

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.workflow.orchestrator as orchestrator_module
import src.workflow.resume_service as resume_service_module
from src.ai.mock_provider import MockAIAnalysisProvider
from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import PriorAuthorizationCaseORM
from src.db.repository import AuditRepository, deterministic_human_review_event_id
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.audit import WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.human_review import HumanReviewOutcome
from src.models.rules import CompletenessRequirements
from src.workflow.human_review_service import resume_after_human_review
from src.workflow.orchestrator import (
    OrchestratorError,
    _continue_claimed_workflow_processing,
    run_prior_authorization_workflow,
)
from src.workflow.resume_service import resume_workflow

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-CONTINUATION-001"
_TRACE_ID = "trace_continuation_001"


# =====================================================================
# FIXTURES
# Kept local to this file, matching the existing convention in
# tests/test_workflow_orchestrator.py and
# tests/test_workflow_resume_service.py.
# =====================================================================
def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (see test_audit_repository.py for why)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_environment():
    """Builds a freshly schema'd in-memory engine plus the three
    repositories the continuation path needs."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    return (
        engine,
        AuditRepository(session_factory=session_factory),
        HumanReviewRepository(session_factory=session_factory),
        CaseRepository(session_factory=session_factory),
    )


def make_case(**overrides) -> PriorAuthorizationCase:
    data = {
        "case_id": "SYN-CASE-CONTINUATION-001",
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


def insert_case_row(engine, case: PriorAuthorizationCase) -> None:
    """Inserts the durable prior_authorization_cases row a real case
    would have -- required both for Stage 1 disposition writes and for
    resume_service's own case-identity validation."""
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=case.case_id,
                client_id="SYN-CLIENT-CONTINUATION-001",
                case_status_code="OPEN",
                member_id=case.member_id,
                provider_id=case.provider_id,
                requested_service_code=case.requested_service_code,
                requested_date=case.requested_date,
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()


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


def make_fhir_client(json_body=None, status_code=200) -> FHIRStyleClient:
    body = valid_fhir_bundle_json() if json_body is None else json_body

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def make_ai_provider(**kwargs) -> MockAIAnalysisProvider:
    if not kwargs:
        kwargs = {"response": {"completed_tasks": []}}
    return MockAIAnalysisProvider(**kwargs)


def advance_to_pending_resume(
    *,
    engine,
    repository,
    human_review_repository,
    case_repository,
    case,
    fhir_client,
) -> str:
    """Runs the initial orchestrator against a failing FHIR dependency
    so the run reaches a GENUINE HUMAN_REVIEW_REQUIRED disposition with
    a real human_reviews row, then records a CONTINUE_WORKFLOW decision
    via resume_after_human_review() -- producing the exact
    PENDING_RESUME/CONTINUE_PROCESSING state a real reviewer decision
    would leave behind. Returns the resulting review_id (NOT the
    trace_id -- callers already know trace_id, and every test that uses
    this needs review_id to check WORKFLOW_RESUMED's deterministic
    event_id)."""
    result = run_prior_authorization_workflow(
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=fhir_client,
        repository=repository,
        workflow_definition_id=_WORKFLOW_DEFINITION_ID,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )
    pending_review = human_review_repository.get_pending_review_by_trace_id(
        result.trace_id
    )
    resume_after_human_review(
        review_id=pending_review.review_id,
        review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYN-REVIEWER-CONTINUATION-001",
        decision_at_utc=datetime.now(timezone.utc),
        session_factory=sessionmaker(bind=engine),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )
    return result.trace_id, pending_review.review_id


def insert_claimed_workflow_run(engine, case: PriorAuthorizationCase, **overrides) -> None:
    """Inserts a workflow_runs row directly in the exact PROCESSING/NULL
    state a successful atomic claim would leave -- used only by the
    narrowly-scoped internal-helper unit tests below, which call
    _continue_claimed_workflow_processing() directly rather than going
    through the full resume_workflow() authorization boundary."""
    now = datetime.now(timezone.utc)
    data = {
        "trace_id": _TRACE_ID,
        "case_id": case.case_id,
        "workflow_definition_id": _WORKFLOW_DEFINITION_ID,
        "workflow_status_code": "PROCESSING",
        "next_action_code": None,
        "human_review_required": False,
        "initiated_by_component_code": "LANGGRAPH",
        "started_at_utc": now,
        "created_at_utc": now,
        "created_by": "SYSTEM",
        "updated_at_utc": now,
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    from src.db.models import WorkflowRunORM

    with sessionmaker(bind=engine)() as session:
        session.add(WorkflowRunORM(**data))
        session.commit()


# =====================================================================
# INTERNAL HELPER BOUNDARY TEST
# =====================================================================
def test_internal_continuation_is_not_public_resume_entry_point():
    """Confirms resume_workflow() is the sole supported
    application-level end-to-end continuation entry point:
    _continue_claimed_workflow_processing() is not exported from either
    module's __all__, so it cannot be discovered as a documented API
    and used to bypass the Human Review + validate_and_claim_resume()
    authorization boundary. This does not claim the helper is
    unimportable -- Python's leading underscore is a convention, not an
    enforcement mechanism -- only that it is internal, unexported, and
    not part of the supported public application API."""
    assert "resume_workflow" in resume_service_module.__all__
    assert (
        "_continue_claimed_workflow_processing"
        not in orchestrator_module.__all__
    )
    assert "continue_workflow_processing" not in orchestrator_module.__all__
    assert not hasattr(orchestrator_module, "continue_workflow_processing")
    assert hasattr(orchestrator_module, "_continue_claimed_workflow_processing")


# =====================================================================
# INTERNAL HELPER PRECONDITION (RACE/STALENESS GUARD) TESTS
# Purpose:
# Narrowly-scoped unit tests of _continue_claimed_workflow_processing()'s
# own defensive fresh-read check, calling it directly (bypassing
# resume_workflow()) -- appropriate ONLY for testing this internal
# failure behavior in isolation, never as a template for how a real
# caller should invoke continuation.
# =====================================================================
def test_internal_continuation_refuses_when_status_not_processing():
    """Verify the precondition check refuses (raises OrchestratorError,
    never invokes the graph) when workflow_status_code is not
    PROCESSING -- e.g. still PENDING_RESUME, never actually claimed."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(
        engine, case, workflow_status_code="PENDING_RESUME", next_action_code="CONTINUE_PROCESSING"
    )
    provider = make_ai_provider()

    with pytest.raises(OrchestratorError):
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_irrelevant",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=provider,
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    assert provider.last_request is None  # the graph was never invoked


def test_internal_continuation_refuses_when_next_action_not_null():
    """Verify the precondition check refuses when next_action_code is
    not NULL, even though workflow_status_code IS PROCESSING -- both
    conditions are required together."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(engine, case, next_action_code="ROUTE_HUMAN_REVIEW")
    provider = make_ai_provider()

    with pytest.raises(OrchestratorError):
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_irrelevant",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=provider,
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    assert provider.last_request is None


def test_internal_continuation_refuses_when_case_id_does_not_match():
    """Verify the precondition check refuses when the supplied case's
    case_id disagrees with the claimed run's own case_id."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(engine, case)
    other_case = make_case(case_id="SYN-CASE-DIFFERENT")
    provider = make_ai_provider()

    with pytest.raises(OrchestratorError):
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_irrelevant",
            case=other_case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=provider,
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    assert provider.last_request is None


def test_internal_continuation_refuses_for_unknown_trace_id():
    """Verify the precondition check refuses when no workflow_runs row
    exists at all for the supplied trace_id."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)

    with pytest.raises(OrchestratorError):
        _continue_claimed_workflow_processing(
            trace_id="trace_does_not_exist",
            review_id="review_irrelevant",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=make_ai_provider(),
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )


# =====================================================================
# COMPENSATION TESTS (setup failure before graph.invoke())
# =====================================================================
def test_setup_failure_reverts_claim_to_pending_resume(monkeypatch):
    """Verify a setup failure before graph.invoke() (simulated by
    making build_case_workflow_graph raise) reverts the claim back to
    PENDING_RESUME/CONTINUE_PROCESSING via the race-safe conditional
    UPDATE, and the ORIGINAL setup error propagates unchanged -- no
    WORKFLOW_RESUMED is ever recorded."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(engine, case)

    def raising_builder(*args, **kwargs):
        raise RuntimeError("synthetic graph build failure")

    monkeypatch.setattr(orchestrator_module, "build_case_workflow_graph", raising_builder)

    with pytest.raises(RuntimeError, match="synthetic graph build failure"):
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_setup_failure",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=make_ai_provider(),
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    saved = repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "PENDING_RESUME"
    assert saved.next_action_code == "CONTINUE_PROCESSING"
    assert repository.list_audit_events(_TRACE_ID) == []


def test_compensation_failure_raises_chained_error_without_overwriting(monkeypatch):
    """Verify that if the resume claim cannot be safely reverted (the
    row changed to a real disposition between the precondition check
    and the compensation attempt -- simulated directly), the resulting
    OrchestratorError chains the original setup error via __cause__,
    and the row's actual current state is left completely untouched --
    proving _revert_resume_claim() never blindly overwrites."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(engine, case)

    def raising_builder(*args, **kwargs):
        raise RuntimeError("synthetic graph build failure")

    monkeypatch.setattr(orchestrator_module, "build_case_workflow_graph", raising_builder)

    real_claim = repository.claim_workflow_run_for_resume

    def claim_after_row_changed(*args, **kwargs):
        # Simulate a concurrent process moving the row to a genuine
        # disposition between this helper's precondition check and this
        # compensation attempt.
        repository.save_workflow_run(
            WorkflowRunSnapshot(
                trace_id=_TRACE_ID,
                case_id=case.case_id,
                workflow_definition_id=_WORKFLOW_DEFINITION_ID,
                workflow_status_code="HUMAN_REVIEW_REQUIRED",
                next_action_code="ROUTE_HUMAN_REVIEW",
                human_review_required=True,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=datetime.now(timezone.utc),
                created_at_utc=datetime.now(timezone.utc),
                created_by="SYSTEM",
                updated_at_utc=datetime.now(timezone.utc),
                updated_by="CONCURRENT_PROCESS",
            )
        )
        return real_claim(*args, **kwargs)

    repository.claim_workflow_run_for_resume = claim_after_row_changed

    with pytest.raises(OrchestratorError) as excinfo:
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_setup_failure",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=make_ai_provider(),
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    assert isinstance(excinfo.value.__cause__, RuntimeError)
    saved = repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.updated_by == "CONCURRENT_PROCESS"


# =====================================================================
# GRAPH INVOCATION FAILURE TESTS
# =====================================================================
class _RaisingGraph:
    """A fake compiled graph whose invoke() always raises -- used only
    to exercise the post-invocation failure path deterministically."""

    def invoke(self, state):
        raise RuntimeError("synthetic graph invocation failure")


def test_graph_invocation_failure_persists_workflow_resumed_and_failed(monkeypatch):
    """Verify that when graph.invoke() itself fails unsafely,
    WORKFLOW_RESUMED and WORKFLOW_FAILED are persisted together
    atomically (via _persist_resumed_terminal_disposition()), the run
    is marked FAILED, OrchestratorError is raised, and (Task 25B-1)
    case_status_code resolves to OPEN -- the case remains open/
    unresolved, never CLOSED, even though this resumed run itself
    failed."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    insert_claimed_workflow_run(engine, case)
    # Simulate the real claimed-for-resume case state (IN_PROGRESS) so
    # the assertion below actually proves the FAILED disposition moved
    # it to OPEN, rather than it merely staying at insert_case_row()'s
    # own OPEN default.
    case_repository.update_case_status(
        case_id=case.case_id,
        case_status_code="IN_PROGRESS",
        updated_by="SYSTEM",
        updated_at_utc=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(
        orchestrator_module, "build_case_workflow_graph", lambda *a, **k: _RaisingGraph()
    )

    with pytest.raises(OrchestratorError):
        _continue_claimed_workflow_processing(
            trace_id=_TRACE_ID,
            review_id="review_invocation_failure",
            case=case,
            completeness_requirements=make_requirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=make_ai_provider(),
            fhir_client=make_fhir_client(),
            repository=repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    saved = repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "FAILED"
    events = repository.list_audit_events(_TRACE_ID)
    event_types = {event.event_type_code for event in events}
    assert event_types == {"WORKFLOW_RESUMED", "WORKFLOW_FAILED"}
    resumed_event = next(e for e in events if e.event_type_code == "WORKFLOW_RESUMED")
    assert resumed_event.event_id == deterministic_human_review_event_id(
        "review_invocation_failure", "WORKFLOW_RESUMED"
    )
    assert case_repository.get_case_status_code(case.case_id) == "OPEN"


# =====================================================================
# END-TO-END resume_workflow() TESTS
# =====================================================================
def test_resume_workflow_completes_successfully_via_public_entry_point():
    """Verify the full authorized path -- HUMAN_REVIEW_REQUIRED ->
    CONTINUE_WORKFLOW decision -> resume_workflow() with a corrected
    FHIR client -- completes the run as COMPLETED, using ONLY the
    public resume_workflow() entry point. Also verifies the Task 25B-1
    case-status lifecycle correction: the case started this test at
    HUMAN_REVIEW_REQUIRED (set when it first paused for review) and
    must resolve to OPEN once the resumed run reaches its own final
    COMPLETED disposition -- never left at HUMAN_REVIEW_REQUIRED or
    IN_PROGRESS."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, review_id = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )
    assert case_repository.get_case_status_code(case.case_id) == "HUMAN_REVIEW_REQUIRED"

    result = resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),  # corrected, now succeeds
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    assert result.trace_id == trace_id
    saved = repository.get_workflow_run(trace_id)
    assert saved.workflow_status_code == "COMPLETED"
    assert case_repository.get_case_status_code(case.case_id) == "OPEN"


def test_resume_workflow_passes_qualifying_review_id_to_workflow_resumed():
    """Verify WORKFLOW_RESUMED's event_id matches
    deterministic_human_review_event_id(review_id, "WORKFLOW_RESUMED")
    for the review_id that authorized this resume -- proving
    resume_workflow() actually threads it through validate_and_claim_
    resume()'s result rather than discarding it."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, review_id = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    events = repository.list_audit_events(trace_id)
    resumed_event = next(e for e in events if e.event_type_code == "WORKFLOW_RESUMED")
    assert resumed_event.event_id == deterministic_human_review_event_id(
        review_id, "WORKFLOW_RESUMED"
    )


def test_workflow_resumed_emitted_exactly_once_per_resume():
    """Verify exactly one WORKFLOW_RESUMED event exists after one
    successful resume."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, _ = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    events = repository.list_audit_events(trace_id)
    resumed_events = [e for e in events if e.event_type_code == "WORKFLOW_RESUMED"]
    assert len(resumed_events) == 1


def test_ordinary_resumed_events_remain_random_uuid():
    """Verify a resumed run's ordinary events (e.g. WORKFLOW_COMPLETED)
    do NOT share WORKFLOW_RESUMED's deterministic-ID scheme -- proving
    only WORKFLOW_RESUMED was changed by this design, not every event
    this module creates."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, review_id = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    events = repository.list_audit_events(trace_id)
    completed_event = next(e for e in events if e.event_type_code == "WORKFLOW_COMPLETED")
    assert completed_event.event_id != deterministic_human_review_event_id(
        review_id, "WORKFLOW_COMPLETED"
    )


def test_resumed_run_reaching_stage1_missing_information():
    """Verify continuation can reach the Stage 1
    MISSING_INFORMATION_REQUESTED disposition -- proving the internal
    helper's Stage 1 branch (reusing _persist_stage1_disposition()
    unchanged) works for a resumed run, not only an initial one."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case(supporting_documentation=[])
    insert_case_row(engine, case)
    trace_id, _ = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(required_documentation=["SYN-DOC-A"]),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),  # now succeeds
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(trace_id)
    assert saved.workflow_status_code == "COMPLETED"
    assert saved.next_action_code == "REQUEST_MISSING_INFORMATION"
    assert saved.human_review_required is False
    assert case_repository.get_case_status_code(case.case_id) == "PENDING_INFORMATION"


def test_resumed_run_re_failing_creates_new_human_review():
    """Verify a resumed run that fails again (still-broken FHIR
    dependency) routes back to HUMAN_REVIEW_REQUIRED and creates a
    SECOND, genuinely new human_reviews row for the SAME trace_id --
    the first review is already COMPLETED, so this is not blocked by
    the duplicate-pending contract."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, first_review_id = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "still broken"}),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    saved = repository.get_workflow_run(trace_id)
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    second_review = human_review_repository.get_pending_review_by_trace_id(trace_id)
    assert second_review is not None
    assert second_review.review_id != first_review_id


def test_second_legitimate_resume_cycle_uses_different_review_id_and_event_id():
    """Verify a full second Human Review -> CONTINUE_WORKFLOW -> resume
    cycle on the SAME trace_id (first resume fails FHIR again, creating
    a new Human Review, decided again as CONTINUE_WORKFLOW) produces a
    SECOND WORKFLOW_RESUMED event with a DIFFERENT event_id from the
    first, because the second cycle's review_id differs -- proving
    legitimate repeated resumes on one trace_id are never conflated or
    rejected as duplicates."""
    engine, repository, human_review_repository, case_repository = make_environment()
    case = make_case()
    insert_case_row(engine, case)
    trace_id, first_review_id = advance_to_pending_resume(
        engine=engine,
        repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        case=case,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    # First resume attempt: FHIR still broken -> HUMAN_REVIEW_REQUIRED again.
    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "still broken"}),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )
    second_pending_review = human_review_repository.get_pending_review_by_trace_id(trace_id)
    resume_after_human_review(
        review_id=second_pending_review.review_id,
        review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYN-REVIEWER-CONTINUATION-002",
        decision_at_utc=datetime.now(timezone.utc),
        session_factory=sessionmaker(bind=engine),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    # Second resume attempt: FHIR now genuinely fixed -> COMPLETED.
    resume_workflow(
        trace_id=trace_id,
        case=case,
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=make_fhir_client(),
        workflow_repository=repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    events = repository.list_audit_events(trace_id)
    resumed_events = [e for e in events if e.event_type_code == "WORKFLOW_RESUMED"]
    assert len(resumed_events) == 2
    resumed_event_ids = {event.event_id for event in resumed_events}
    assert resumed_event_ids == {
        deterministic_human_review_event_id(first_review_id, "WORKFLOW_RESUMED"),
        deterministic_human_review_event_id(
            second_pending_review.review_id, "WORKFLOW_RESUMED"
        ),
    }
    assert len(resumed_event_ids) == 2  # the two IDs are genuinely different

    saved = repository.get_workflow_run(trace_id)
    assert saved.workflow_status_code == "COMPLETED"


# =====================================================================
# PURE UNIT TESTS -- deterministic event_id derivation itself
# =====================================================================
def test_workflow_resumed_id_differs_for_different_review_ids():
    """Verify two different review_ids produce two different
    WORKFLOW_RESUMED event_ids."""
    first = deterministic_human_review_event_id("review_A", "WORKFLOW_RESUMED")
    second = deterministic_human_review_event_id("review_B", "WORKFLOW_RESUMED")
    assert first != second


def test_workflow_resumed_id_stable_for_same_review_id():
    """Verify the same review_id always produces the same
    WORKFLOW_RESUMED event_id."""
    first = deterministic_human_review_event_id("review_A", "WORKFLOW_RESUMED")
    second = deterministic_human_review_event_id("review_A", "WORKFLOW_RESUMED")
    assert first == second
