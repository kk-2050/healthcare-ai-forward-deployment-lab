# File Name: test_workflow_resume_service.py
# Purpose: Tests src/workflow/resume_service.py's deterministic resume eligibility, persisted case-identity validation, and atomic claim behavior using an in-memory SQLite test double.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect Step 24B-3A's eligibility/claim layer only --
# they never invoke LangGraph, the FHIR-style client, or the AI
# provider, and never expect WORKFLOW_RESUMED or any final workflow
# disposition to be persisted (that is a separate, later,
# continuation-orchestration step). Every test runs against an
# in-memory SQLite engine (a TEST DOUBLE only, same convention as
# tests/test_workflow_orchestrator.py) -- never a live SQL Server.

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import HumanReviewORM, PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import AuditRepository
from src.models.case import PriorAuthorizationCase
from src.workflow.resume_service import (
    ResumeCaseIdentityMismatchError,
    ResumeClaimConflictError,
    ResumeNotEligibleError,
    ResumeTraceNotFoundError,
    validate_and_claim_resume,
)

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-RESUME-001"
_TRACE_ID = "trace_resume_001"
_CASE_ID = "case_resume_001"
_REVIEW_ID = "review_resume_001"


def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as tests/test_workflow_orchestrator.py)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_environment():
    """Builds a freshly schema'd in-memory engine plus the three
    repositories validate_and_claim_resume() needs."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    return (
        engine,
        AuditRepository(session_factory=session_factory),
        HumanReviewRepository(session_factory=session_factory),
        CaseRepository(session_factory=session_factory),
    )


def insert_case(engine, **overrides) -> None:
    """Inserts the minimum prior_authorization_cases row, with the
    exact identity fields the default make_supplied_case() also uses by
    default, so a test only needs to override what it cares about."""
    now = datetime.now(timezone.utc)
    data = {
        "case_id": _CASE_ID,
        "client_id": "SYN-CLIENT-RESUME-001",
        "case_status_code": "OPEN",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-LUMBAR-MRI",
        "requested_date": date(2026, 1, 15),
        "source_component_code": "FASTAPI",
        "opened_at_utc": now,
        "created_at_utc": now,
        "created_by": "SYSTEM",
        "updated_at_utc": now,
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    with sessionmaker(bind=engine)() as session:
        session.add(PriorAuthorizationCaseORM(**data))
        session.commit()


def insert_workflow_run(engine, **overrides) -> None:
    now = datetime.now(timezone.utc)
    data = {
        "trace_id": _TRACE_ID,
        "case_id": _CASE_ID,
        "workflow_definition_id": _WORKFLOW_DEFINITION_ID,
        "workflow_status_code": "PENDING_RESUME",
        "next_action_code": "CONTINUE_PROCESSING",
        "human_review_required": False,
        "initiated_by_component_code": "LANGGRAPH",
        "started_at_utc": now,
        "created_at_utc": now,
        "created_by": "SYSTEM",
        "updated_at_utc": now,
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    with sessionmaker(bind=engine)() as session:
        session.add(WorkflowRunORM(**data))
        session.commit()


def insert_human_review(engine, **overrides) -> None:
    now = datetime.now(timezone.utc)
    data = {
        "review_id": _REVIEW_ID,
        "trace_id": _TRACE_ID,
        "case_id": _CASE_ID,
        "review_status_code": "COMPLETED",
        "review_outcome_code": "CONTINUE_WORKFLOW",
        "reason_code": "HUMAN_REVIEW_FHIR_FAILURE",
        "requested_at_utc": now,
        "completed_at_utc": now,
        "reviewer_actor_type_code": "HUMAN_REVIEWER",
        "reviewer_reference": "SYN-REVIEWER-RESUME-001",
        "source_component_code": "HUMAN_REVIEW_SERVICE",
        "created_at_utc": now,
        "created_by": "SYSTEM",
        "updated_at_utc": now,
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    with sessionmaker(bind=engine)() as session:
        session.add(HumanReviewORM(**data))
        session.commit()


def make_full_fixture(engine, **overrides) -> None:
    """Inserts a fully eligible case/workflow_run/human_review fixture
    -- the exact state a real CONTINUE_WORKFLOW decision would have
    produced. Pass case_overrides/run_overrides/review_overrides to
    deliberately break one condition at a time."""
    insert_case(engine, **overrides.get("case_overrides", {}))
    insert_workflow_run(engine, **overrides.get("run_overrides", {}))
    insert_human_review(engine, **overrides.get("review_overrides", {}))


def make_supplied_case(**overrides) -> PriorAuthorizationCase:
    """A caller-supplied case matching the default fixture's identity
    exactly, with a diagnosis/documentation/notes shape that is
    deliberately DIFFERENT from what a first attempt might have used --
    proving those fields are never compared."""
    data = {
        "case_id": _CASE_ID,
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-LUMBAR-MRI",
        "diagnosis_code": "SYN-FRESH-DIAGNOSIS-CODE",
        "requested_date": date(2026, 1, 15),
        "supporting_documentation": ["SYN-FRESH-DOC-A", "SYN-FRESH-DOC-B"],
        "clinical_notes": "Freshly re-supplied clinical notes for resume.",
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


# =====================================================================
# ELIGIBILITY TESTS
# =====================================================================
def test_valid_eligibility_succeeds():
    """Verify a fully eligible fixture passes and returns a structured
    result with the correct identifiers."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.trace_id == _TRACE_ID
    assert result.case_id == _CASE_ID
    assert result.review_id == _REVIEW_ID


def test_trace_not_found_rejected():
    """Verify a nonexistent trace_id raises ResumeTraceNotFoundError
    before any write is attempted."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )

    with pytest.raises(ResumeTraceNotFoundError):
        validate_and_claim_resume(
            trace_id="trace_does_not_exist",
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_wrong_workflow_status_rejected():
    """Verify workflow_status_code != PENDING_RESUME raises
    ResumeNotEligibleError."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(
        engine, run_overrides={"workflow_status_code": "PROCESSING", "next_action_code": None}
    )

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_wrong_next_action_rejected():
    """Verify next_action_code != CONTINUE_PROCESSING raises
    ResumeNotEligibleError even when workflow_status_code IS
    PENDING_RESUME."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine, run_overrides={"next_action_code": "ROUTE_HUMAN_REVIEW"})

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_no_completed_human_review_rejected():
    """Verify no completed Human Review for the trace_id raises
    ResumeNotEligibleError (fixture has no human_reviews row at all)."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    insert_case(engine)
    insert_workflow_run(engine)
    # No human review inserted at all.

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_review_outcome_not_continue_workflow_rejected():
    """Verify a completed review with a different outcome (e.g.
    ESCALATE) raises ResumeNotEligibleError."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine, review_overrides={"review_outcome_code": "ESCALATE"})

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_review_case_id_mismatch_with_run_case_id_rejected():
    """Verify a completed review whose case_id disagrees with the
    workflow run's own case_id raises ResumeNotEligibleError -- a
    data-integrity condition, checked explicitly rather than assumed."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    insert_case(engine)
    insert_case(engine, case_id="case_resume_OTHER", member_id="SYN-MEMBER-OTHER")
    insert_workflow_run(engine)
    insert_human_review(engine, case_id="case_resume_OTHER")

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_persisted_case_missing_rejected():
    """Verify a workflow run whose case_id has no matching
    prior_authorization_cases row raises ResumeTraceNotFoundError."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    # No case inserted at all -- only the run and review.
    insert_workflow_run(engine)
    insert_human_review(engine)

    with pytest.raises(ResumeTraceNotFoundError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


# =====================================================================
# CASE IDENTITY TESTS -- durable fields must match
# =====================================================================
def test_case_id_mismatch_rejected():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(case_id="case_resume_DIFFERENT"),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_member_id_mismatch_rejected():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(member_id="SYN-MEMBER-DIFFERENT"),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_provider_id_mismatch_rejected():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(provider_id="SYN-PROVIDER-DIFFERENT"),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_requested_service_code_mismatch_rejected():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(requested_service_code="SYN-DIFFERENT-SERVICE"),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_requested_date_mismatch_rejected():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(requested_date=date(2099, 1, 1)),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_identity_mismatch_happens_before_claim():
    """Verify a case-identity mismatch leaves the workflow run
    completely untouched -- still PENDING_RESUME/CONTINUE_PROCESSING,
    proving the identity check runs (and fails) strictly before the
    atomic claim is ever attempted."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with pytest.raises(ResumeCaseIdentityMismatchError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(member_id="SYN-MEMBER-DIFFERENT"),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )

    saved = workflow_repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "PENDING_RESUME"
    assert saved.next_action_code == "CONTINUE_PROCESSING"


def test_eligibility_failure_happens_before_claim():
    """Verify an eligibility failure (not identity) also leaves the
    workflow run untouched -- the claim is never attempted."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine, review_overrides={"review_outcome_code": "ESCALATE"})

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )

    saved = workflow_repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "PENDING_RESUME"
    assert saved.next_action_code == "CONTINUE_PROCESSING"


# =====================================================================
# POSITIVE IDENTITY BEHAVIOR -- non-durable fields must NOT be compared
# =====================================================================
def test_diagnosis_code_difference_is_not_rejected():
    """Verify a caller-supplied diagnosis_code that differs from
    whatever the original run may have used is accepted -- there is no
    durable value to compare it against."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(diagnosis_code="SYN-COMPLETELY-DIFFERENT-DX"),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.trace_id == _TRACE_ID


def test_supporting_documentation_difference_is_not_rejected():
    """Verify different supporting_documentation is accepted -- not
    durably persisted, so nothing to compare."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(supporting_documentation=["SYN-ENTIRELY-NEW-DOC"]),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.trace_id == _TRACE_ID


def test_clinical_notes_difference_is_not_rejected():
    """Verify different clinical_notes text is accepted -- not durably
    persisted, so nothing to compare."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(clinical_notes="Completely different notes text."),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.trace_id == _TRACE_ID


# =====================================================================
# CLAIM TESTS
# =====================================================================
def test_valid_eligibility_results_in_processing_and_null_next_action():
    """Verify a successful call ends with the SAME workflow run in
    PROCESSING/NULL -- the exact claimed state."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.workflow_run.workflow_status_code == "PROCESSING"
    assert result.workflow_run.next_action_code is None
    saved = workflow_repository.get_workflow_run(_TRACE_ID)
    assert saved.workflow_status_code == "PROCESSING"
    assert saved.next_action_code is None


def test_same_trace_id_preserved():
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    assert result.trace_id == _TRACE_ID
    assert result.workflow_run.trace_id == _TRACE_ID


def test_no_new_workflow_run_created():
    """Verify exactly one workflow_runs row exists before and after a
    successful resume eligibility/claim call."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    with sessionmaker(bind=engine)() as session:
        before_count = session.query(WorkflowRunORM).count()

    validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    with sessionmaker(bind=engine)() as session:
        after_count = session.query(WorkflowRunORM).count()

    assert before_count == after_count == 1


def test_second_claim_attempt_is_rejected_safely():
    """Verify calling validate_and_claim_resume() a second time for
    the same (now-claimed) trace_id fails with ResumeNotEligibleError,
    since workflow_status_code is no longer PENDING_RESUME -- proving a
    genuine duplicate resume request is safely refused, not silently
    re-processed."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    with pytest.raises(ResumeNotEligibleError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )


def test_claim_conflict_after_eligibility_reads_pass_fails_safely():
    """Verify the exact race scenario the atomic claim exists to catch:
    eligibility reads pass, but the row is claimed by someone else
    (simulated directly via the repository) between those reads and
    this call's own claim attempt -- raises ResumeClaimConflictError,
    not a silent retry or a false success."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    # Simulate a concurrent resume request winning the race by claiming
    # the row directly, via the same repository method, right before
    # this call's own claim attempt would run.
    real_claim = workflow_repository.claim_workflow_run_for_resume

    def claim_after_stealing_it(*args, **kwargs):
        real_claim(
            _TRACE_ID,
            updated_at_utc=datetime.now(timezone.utc),
            updated_by="CONCURRENT_REQUEST",
        )
        return real_claim(*args, **kwargs)

    workflow_repository.claim_workflow_run_for_resume = claim_after_stealing_it

    with pytest.raises(ResumeClaimConflictError):
        validate_and_claim_resume(
            trace_id=_TRACE_ID,
            case=make_supplied_case(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )

    saved = workflow_repository.get_workflow_run(_TRACE_ID)
    assert saved.updated_by == "CONCURRENT_REQUEST"


# =====================================================================
# SECURITY / NO RAW ERROR EXPOSURE
# =====================================================================
def test_result_contains_no_clinical_fields():
    """Verify ResumeEligibilityResult exposes only durable metadata --
    no diagnosis/documentation/notes field exists on it at all."""
    engine, workflow_repository, human_review_repository, case_repository = (
        make_environment()
    )
    make_full_fixture(engine)

    result = validate_and_claim_resume(
        trace_id=_TRACE_ID,
        case=make_supplied_case(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
    )

    result_fields = set(vars(result).keys())
    assert "diagnosis_code" not in result_fields
    assert "supporting_documentation" not in result_fields
    assert "clinical_notes" not in result_fields
