# File Name: test_human_review_service.py
# Purpose: Tests the atomic Human Review decision-transition business logic (all four outcomes, replay, rollback) using an in-memory SQLite test double.
# Creation Date: 2026-09-22
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect src/workflow/human_review_service.py's
# Step 23C-2B2 behavior: the four approved outcome state transitions
# (CONTINUE_WORKFLOW/REQUEST_MORE_INFORMATION/ESCALATE/CLOSE_CASE), the
# atomic shared-transaction guarantee, and the corrected replay design
# (no early "already done" shortcut -- every write is always attempted,
# and each repository's own idempotency absorbs a genuine replay). This
# file does NOT test Task 24 True Resume, WORKFLOW_RESUMED, real SQL
# Server behavior, or CASE_CLOSE_* reference-data loading (all
# explicitly out of scope for this step) -- every CLOSE_CASE reason
# code used here is validated by this module's own Python-level
# _validate_close_case_input(), never a database FK (reasons has no
# ORM-level FK object on prior_authorization_cases.close_reason_code,
# per the project's Foreign Key Policy), so no real-database
# CASE_CLOSE_* rows are needed to exercise this logic offline.

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import create_database_schema
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import AuditEventORM, HumanReviewORM, PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import (
    AuditEventConflictError,
    AuditRepository,
    deterministic_human_review_event_id,
)
from src.models.audit import AuditEvent, AuditEventCategory
from src.models.human_review import HumanReviewOutcome, HumanReviewStatus
from src.workflow.human_review_service import (
    InvalidCloseReasonError,
    ResumeError,
    resume_after_human_review,
)

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_DECISION_AT = datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc)


def make_test_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_environment(*, with_case: bool = True):
    """Builds a fresh in-memory environment: schema, the three
    repositories, and a synthetic workflow_definition + (optionally) a
    prior_authorization_cases row + a HUMAN_REVIEW_REQUIRED workflow_run
    + one REQUESTED human_reviews row. Returns a dict of everything a
    test needs."""
    from src.db.models import WorkflowDefinitionORM

    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            WorkflowDefinitionORM(
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_code="PRIOR_AUTHORIZATION",
                version_no="1.0",
                workflow_name="Prior Authorization Phase 1",
                effective_from_utc=_NOW,
                created_at_utc=_NOW,
                created_by="SYSTEM",
                updated_at_utc=_NOW,
                updated_by="SYSTEM",
            )
        )
        if with_case:
            session.add(
                PriorAuthorizationCaseORM(
                    case_id="SYN-CASE-001",
                    client_id="SYN-CLIENT-001",
                    member_id="SYN-MEMBER-001",
                    provider_id="SYN-PROVIDER-001",
                    requested_service_code="SYN-SERVICE-100",
                    requested_date=_NOW.date(),
                    case_status_code="HUMAN_REVIEW_REQUIRED",
                    source_component_code="FASTAPI",
                    opened_at_utc=_NOW,
                    created_at_utc=_NOW,
                    created_by="SYSTEM",
                    updated_at_utc=_NOW,
                    updated_by="SYSTEM",
                )
            )
        session.add(
            WorkflowRunORM(
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_status_code="HUMAN_REVIEW_REQUIRED",
                human_review_required=True,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=_NOW,
                created_at_utc=_NOW,
                created_by="SYSTEM",
                updated_at_utc=_NOW,
                updated_by="SYSTEM",
            )
        )
        session.add(
            HumanReviewORM(
                review_id="SYN-REVIEW-001",
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                review_status_code=HumanReviewStatus.REQUESTED.value,
                reason_code="HUMAN_REVIEW_EVIDENCE_MISMATCH",
                requested_at_utc=_NOW,
                source_component_code="HUMAN_REVIEW_SERVICE",
                created_at_utc=_NOW,
                created_by="SYSTEM",
                updated_at_utc=_NOW,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    return {
        "engine": engine,
        "session_factory": session_factory,
        "human_review_repository": HumanReviewRepository(session_factory=session_factory),
        "workflow_repository": AuditRepository(session_factory=session_factory),
        "case_repository": CaseRepository(session_factory=session_factory),
    }


def resume(env, outcome, **overrides):
    kwargs = dict(
        review_id="SYN-REVIEW-001",
        review_outcome_code=outcome,
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYNTH_REVIEWER_001",
        decision_at_utc=_DECISION_AT,
        session_factory=env["session_factory"],
        workflow_repository=env["workflow_repository"],
        human_review_repository=env["human_review_repository"],
        case_repository=env["case_repository"],
    )
    kwargs.update(overrides)
    return resume_after_human_review(**kwargs)


def _fetch_run(env):
    with env["session_factory"]() as session:
        return session.get(WorkflowRunORM, "SYN-TRACE-001")


def _fetch_review(env):
    with env["session_factory"]() as session:
        return session.get(HumanReviewORM, "SYN-REVIEW-001")


def _fetch_case(env):
    with env["session_factory"]() as session:
        return session.get(PriorAuthorizationCaseORM, "SYN-CASE-001")


def _fetch_events(env):
    with env["session_factory"]() as session:
        return (
            session.query(AuditEventORM)
            .filter(AuditEventORM.trace_id == "SYN-TRACE-001")
            .all()
        )


# =====================================================================
# A. GENERAL TRANSACTION BEHAVIOR
# =====================================================================
def test_all_required_writes_commit_together_on_success():
    """Verify review, workflow, case, and audit all reflect the
    decision after a successful call."""
    env = make_environment()

    resume(env, HumanReviewOutcome.ESCALATE)

    review = _fetch_review(env)
    run = _fetch_run(env)
    case = _fetch_case(env)
    events = _fetch_events(env)

    assert review.review_status_code == HumanReviewStatus.COMPLETED.value
    assert run.workflow_status_code == "COMPLETED"
    assert case.case_status_code == "HUMAN_REVIEW_REQUIRED"
    assert len(events) == 2


def test_audit_failure_rolls_back_review_and_workflow_changes():
    """Verify a conflicting audit write rolls back the review and
    workflow changes that had already succeeded in-session before the
    audit write failed."""
    env = make_environment()
    conflicting_id = deterministic_human_review_event_id(
        "SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED"
    )
    env["workflow_repository"].append_audit_event(
        AuditEvent(
            event_id=conflicting_id,
            trace_id="SYN-TRACE-001",
            case_id="SYN-CASE-001",
            event_type_code="HUMAN_REVIEW_COMPLETED",
            event_category_code=AuditEventCategory.HUMAN,
            source_component_code="HUMAN_REVIEW_SERVICE",
            actor_type_code="HUMAN_REVIEWER",
            actor_identifier="SOMEONE_ELSE",  # differs -> forces a conflict
            result_code="SUCCESS",
            occurred_at_utc=_DECISION_AT,
            created_at_utc=_DECISION_AT,
            created_by="SYSTEM",
        )
    )

    with pytest.raises(AuditEventConflictError):
        resume(env, HumanReviewOutcome.ESCALATE)

    review = _fetch_review(env)
    run = _fetch_run(env)
    assert review.review_status_code == HumanReviewStatus.REQUESTED.value
    assert run.workflow_status_code == "HUMAN_REVIEW_REQUIRED"


def test_case_write_failure_rolls_back_review_workflow_and_audit():
    """Verify a case-update failure (case_id not found) rolls back the
    review and workflow changes, and no audit event survives."""
    env = make_environment(with_case=False)  # case deliberately absent

    with pytest.raises(Exception):
        resume(env, HumanReviewOutcome.REQUEST_MORE_INFORMATION)

    review = _fetch_review(env)
    run = _fetch_run(env)
    events = _fetch_events(env)
    assert review.review_status_code == HumanReviewStatus.REQUESTED.value
    assert run.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert events == []


def test_identical_decision_replay_is_idempotent():
    """Verify calling resume_after_human_review() twice with identical
    parameters (including decision_at_utc) succeeds both times with no
    net change and no error on the second call."""
    env = make_environment()

    first = resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW)
    second = resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW)

    assert first.review.review_outcome_code == second.review.review_outcome_code
    events = _fetch_events(env)
    assert len(events) == 1  # CONTINUE_WORKFLOW emits only HUMAN_REVIEW_COMPLETED


def test_mismatched_deterministic_audit_replay_conflicts():
    """Verify replaying the same review_id/outcome with a DIFFERENT
    decision_at_utc raises AuditEventConflictError -- occurred_at_utc is
    part of the audit event's semantic identity (Step 23C-2B1/2B2)."""
    env = make_environment()
    resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW, decision_at_utc=_DECISION_AT)

    with pytest.raises(AuditEventConflictError):
        resume(
            env,
            HumanReviewOutcome.CONTINUE_WORKFLOW,
            decision_at_utc=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        )


# =====================================================================
# B. CONTINUE_WORKFLOW
# =====================================================================
def test_continue_workflow_full_contract():
    """Verify CONTINUE_WORKFLOW's complete approved contract in one
    pass: review/workflow/audit state, and the absence of
    WORKFLOW_COMPLETED/WORKFLOW_RESUMED."""
    env = make_environment()

    result = resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW)

    review = _fetch_review(env)
    run = _fetch_run(env)
    events = _fetch_events(env)

    assert review.review_status_code == HumanReviewStatus.COMPLETED.value
    assert review.review_outcome_code == HumanReviewOutcome.CONTINUE_WORKFLOW.value
    assert review.completed_at_utc is not None

    assert run.workflow_status_code == "PENDING_RESUME"
    assert run.next_action_code == "CONTINUE_PROCESSING"
    assert run.completed_at_utc is None
    assert run.trace_id == "SYN-TRACE-001"  # same row/same trace_id

    event_types = {event.event_type_code for event in events}
    assert event_types == {"HUMAN_REVIEW_COMPLETED"}
    assert "WORKFLOW_COMPLETED" not in event_types
    assert "WORKFLOW_RESUMED" not in event_types
    for event in events:
        assert event.source_component_code == "HUMAN_REVIEW_SERVICE"

    assert result.workflow_run.workflow_status_code == "PENDING_RESUME"


def test_continue_workflow_does_not_close_or_change_case_status():
    """Verify CONTINUE_WORKFLOW never touches case_status_code."""
    env = make_environment()

    resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW)

    case = _fetch_case(env)
    assert case.case_status_code == "HUMAN_REVIEW_REQUIRED"  # unchanged


# =====================================================================
# C. REQUEST_MORE_INFORMATION
# =====================================================================
def test_request_more_information_full_contract():
    env = make_environment()

    resume(env, HumanReviewOutcome.REQUEST_MORE_INFORMATION)

    review = _fetch_review(env)
    run = _fetch_run(env)
    case = _fetch_case(env)
    events = _fetch_events(env)

    assert review.review_outcome_code == HumanReviewOutcome.REQUEST_MORE_INFORMATION.value
    assert run.workflow_status_code == "COMPLETED"
    assert run.next_action_code == "REQUEST_MISSING_INFORMATION"
    assert run.completed_at_utc is not None
    assert case.case_status_code == "PENDING_INFORMATION"
    assert case.case_status_code != "CLOSED"

    event_types = {event.event_type_code for event in events}
    assert event_types == {"HUMAN_REVIEW_COMPLETED", "WORKFLOW_COMPLETED"}


# =====================================================================
# D. ESCALATE
# =====================================================================
def test_escalate_full_contract():
    env = make_environment()

    resume(env, HumanReviewOutcome.ESCALATE)

    review = _fetch_review(env)
    run = _fetch_run(env)
    case = _fetch_case(env)
    events = _fetch_events(env)

    assert review.review_outcome_code == HumanReviewOutcome.ESCALATE.value
    assert run.workflow_status_code == "COMPLETED"
    assert run.next_action_code == "ROUTE_HUMAN_REVIEW"
    assert case.case_status_code == "HUMAN_REVIEW_REQUIRED"

    event_types = {event.event_type_code for event in events}
    assert event_types == {"HUMAN_REVIEW_COMPLETED", "WORKFLOW_COMPLETED"}


def test_escalate_does_not_auto_create_a_second_review():
    """Verify ROUTE_HUMAN_REVIEW as next_action_code does not itself
    cause a second human_reviews row to be created -- it signals the
    next required action, never proof one was already created."""
    env = make_environment()

    resume(env, HumanReviewOutcome.ESCALATE)

    with env["session_factory"]() as session:
        count = (
            session.query(HumanReviewORM)
            .filter(HumanReviewORM.trace_id == "SYN-TRACE-001")
            .count()
        )
    assert count == 1


def test_escalate_introduces_no_security_or_privilege_concept():
    """Verify ESCALATE's case status is exactly the approved
    HUMAN_REVIEW_REQUIRED value -- no ESCALATED status, no
    security-queue-flavored value is ever written."""
    env = make_environment()

    resume(env, HumanReviewOutcome.ESCALATE)

    case = _fetch_case(env)
    assert case.case_status_code == "HUMAN_REVIEW_REQUIRED"
    assert case.case_status_code != "ESCALATED"


# =====================================================================
# E. CLOSE_CASE
# =====================================================================
def test_close_case_missing_reason_code_rejected():
    env = make_environment()

    with pytest.raises(InvalidCloseReasonError):
        resume(env, HumanReviewOutcome.CLOSE_CASE)

    # Nothing persisted -- validation happens before any DB interaction.
    review = _fetch_review(env)
    assert review.review_status_code == HumanReviewStatus.REQUESTED.value


def test_close_case_unapproved_reason_code_rejected():
    env = make_environment()

    with pytest.raises(InvalidCloseReasonError):
        resume(
            env,
            HumanReviewOutcome.CLOSE_CASE,
            close_reason_code="NOT_AN_APPROVED_CODE",
        )


def test_close_case_other_without_text_rejected():
    env = make_environment()

    with pytest.raises(InvalidCloseReasonError):
        resume(
            env,
            HumanReviewOutcome.CLOSE_CASE,
            close_reason_code="CASE_CLOSE_OTHER",
        )

    with pytest.raises(InvalidCloseReasonError):
        resume(
            env,
            HumanReviewOutcome.CLOSE_CASE,
            close_reason_code="CASE_CLOSE_OTHER",
            close_reason_text="   ",  # whitespace-only is not valid text
        )


def test_close_case_valid_reason_full_contract():
    env = make_environment()

    resume(
        env,
        HumanReviewOutcome.CLOSE_CASE,
        close_reason_code="CASE_CLOSE_COMPLETED",
    )

    review = _fetch_review(env)
    run = _fetch_run(env)
    case = _fetch_case(env)
    events = _fetch_events(env)

    assert review.review_outcome_code == HumanReviewOutcome.CLOSE_CASE.value

    assert run.workflow_status_code == "COMPLETED"
    assert run.next_action_code == "COMPLETE_WORKFLOW"
    assert run.completed_at_utc is not None

    assert case.case_status_code == "CLOSED"
    assert case.closed_at_utc is not None
    assert case.closed_by == "SYNTH_REVIEWER_001"  # reviewer_reference, not invented
    assert case.close_reason_code == "CASE_CLOSE_COMPLETED"
    assert case.close_reason_text is None  # not required for this code

    event_types = {event.event_type_code for event in events}
    assert event_types == {"HUMAN_REVIEW_COMPLETED", "WORKFLOW_COMPLETED"}


def test_close_case_other_with_text_persists_text():
    env = make_environment()

    resume(
        env,
        HumanReviewOutcome.CLOSE_CASE,
        close_reason_code="CASE_CLOSE_OTHER",
        close_reason_text="Synthetic explanatory reason for this test.",
    )

    case = _fetch_case(env)
    assert case.close_reason_code == "CASE_CLOSE_OTHER"
    assert case.close_reason_text == "Synthetic explanatory reason for this test."


# =====================================================================
# PRECONDITION / NOT-FOUND HANDLING
# =====================================================================
def test_unknown_review_id_raises_resume_error():
    env = make_environment()

    with pytest.raises(ResumeError):
        resume(env, HumanReviewOutcome.CONTINUE_WORKFLOW, review_id="DOES-NOT-EXIST")
