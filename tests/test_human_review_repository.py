# File Name: test_human_review_repository.py
# Purpose: Tests HumanReviewRepository's duplicate-pending, CANCELLED-protection, idempotency, and caller-owned-transaction behavior using an in-memory SQLite test double.
# Creation Date: 2026-09-22
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the Step 23C-2A/2B1 persistence-foundation
# contracts in src/db/human_review_repository.py: duplicate-pending
# review detection/reuse, the CANCELLED-review protection, and
# caller-owned shared-transaction support (session= parameter). Every
# test runs against an in-memory SQLite engine -- a TEST DOUBLE only;
# real SQL Server compatibility was already validated separately when
# migration f2fb22e3a41e was applied and the Task 23 reference data was
# loaded (Task 23B). This file does not yet test the four Human Review
# outcome business mappings (CONTINUE_WORKFLOW/REQUEST_MORE_INFORMATION/
# ESCALATE/CLOSE_CASE) -- that is Step 23C-2B2's scope.

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import create_database_schema
from src.db.human_review_repository import (
    HumanReviewConflictError,
    HumanReviewRepository,
    PersistenceError,
)
from src.db.models import PriorAuthorizationCaseORM, WorkflowDefinitionORM, WorkflowRunORM
from src.models.human_review import HumanReviewOutcome, HumanReviewRecord, HumanReviewStatus


def make_test_engine():
    """In-memory SQLite engine with StaticPool -- see
    tests/test_audit_repository.py's identical helper for why StaticPool
    is required (one shared connection across multiple sessions)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_repository(engine=None) -> tuple[HumanReviewRepository, sessionmaker]:
    """Builds a HumanReviewRepository backed by a freshly schema'd
    in-memory engine, with a synthetic workflow_run/case/definition row
    already present so human_reviews rows have valid parents."""
    if engine is None:
        engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add(
            WorkflowDefinitionORM(
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_code="PRIOR_AUTHORIZATION",
                version_no="1.0",
                workflow_name="Prior Authorization Phase 1",
                effective_from_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.add(
            PriorAuthorizationCaseORM(
                case_id="SYN-CASE-001",
                client_id="SYN-CLIENT-001",
                member_id="SYN-MEMBER-001",
                provider_id="SYN-PROVIDER-001",
                requested_service_code="SYN-SERVICE-100",
                requested_date=now.date(),
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
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_status_code="HUMAN_REVIEW_REQUIRED",
                human_review_required=True,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    return HumanReviewRepository(session_factory=session_factory), session_factory


def make_review(**overrides) -> HumanReviewRecord:
    """A minimal, fully valid synthetic HumanReviewRecord, pending."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    data = {
        "review_id": "SYN-REVIEW-001",
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "review_status_code": HumanReviewStatus.REQUESTED,
        "reason_code": "HUMAN_REVIEW_EVIDENCE_MISMATCH",
        "assigned_department_id": None,
        "assigned_location_id": None,
        "requested_at_utc": now,
        "source_component_code": "HUMAN_REVIEW_SERVICE",
        "created_at_utc": now,
        "created_by": "SYSTEM",
        "updated_at_utc": now,
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    return HumanReviewRecord(**data)


# =====================================================================
# DUPLICATE PENDING REVIEW
# =====================================================================
def test_identical_duplicate_pending_review_returns_existing_review():
    """Verify an identical second request (same case_id/reason_code/
    assigned_department_id/assigned_location_id) for a trace_id that
    already has a pending review returns the EXISTING review --
    idempotent success, not a second row."""
    repository, _ = make_repository()
    first = repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))

    second = repository.create_review_request(
        make_review(review_id="SYN-REVIEW-002")
    )

    assert second.review_id == first.review_id == "SYN-REVIEW-001"


def test_materially_different_pending_review_raises_conflict():
    """Verify a second request for the same trace_id with a different
    reason_code raises HumanReviewConflictError -- never a silent
    overwrite, never a second competing pending row."""
    repository, _ = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))

    with pytest.raises(HumanReviewConflictError):
        repository.create_review_request(
            make_review(
                review_id="SYN-REVIEW-002",
                reason_code="HUMAN_REVIEW_AI_FAILURE",
            )
        )


def test_no_second_active_pending_row_is_created(monkeypatch=None):
    """Verify that after an identical-duplicate request and a rejected
    conflicting request, exactly one human_reviews row exists for the
    trace_id."""
    repository, session_factory = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))
    repository.create_review_request(make_review(review_id="SYN-REVIEW-002"))
    with pytest.raises(HumanReviewConflictError):
        repository.create_review_request(
            make_review(review_id="SYN-REVIEW-003", reason_code="HUMAN_REVIEW_AI_FAILURE")
        )

    from src.db.models import HumanReviewORM

    with session_factory() as session:
        count = (
            session.query(HumanReviewORM)
            .filter(HumanReviewORM.trace_id == "SYN-TRACE-001")
            .count()
        )
    assert count == 1


def test_completed_review_does_not_block_a_genuinely_new_one():
    """Verify a COMPLETED review for a trace_id does not prevent a
    later, genuinely new review request for the same trace_id."""
    repository, _ = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))
    repository.record_review_outcome(
        review_id="SYN-REVIEW-001",
        review_outcome_code=HumanReviewOutcome.ESCALATE,
        completed_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYNTH_REVIEWER_001",
        updated_by="SYNTH_REVIEWER_001",
    )

    new_review = repository.create_review_request(
        make_review(review_id="SYN-REVIEW-002")
    )

    assert new_review.review_id == "SYN-REVIEW-002"


# =====================================================================
# CANCELLED REVIEW PROTECTION
# =====================================================================
def test_cancelled_review_cannot_be_completed():
    """Verify a decision attempt against a CANCELLED review raises
    HumanReviewConflictError and never resurrects it into COMPLETED."""
    repository, session_factory = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))
    from src.db.models import HumanReviewORM

    with session_factory() as session:
        row = session.get(HumanReviewORM, "SYN-REVIEW-001")
        row.review_status_code = HumanReviewStatus.CANCELLED.value
        session.commit()

    with pytest.raises(HumanReviewConflictError):
        repository.record_review_outcome(
            review_id="SYN-REVIEW-001",
            review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
            completed_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference="SYNTH_REVIEWER_001",
            updated_by="SYNTH_REVIEWER_001",
        )

    with session_factory() as session:
        row = session.get(HumanReviewORM, "SYN-REVIEW-001")
        assert row.review_status_code == HumanReviewStatus.CANCELLED.value
        assert row.review_outcome_code is None


# =====================================================================
# DECISION IDEMPOTENCY / CONFLICT
# =====================================================================
def test_completed_review_same_outcome_replay_is_idempotent():
    """Verify recording the identical outcome twice is a safe no-op."""
    repository, _ = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))
    kwargs = dict(
        review_id="SYN-REVIEW-001",
        review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
        completed_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYNTH_REVIEWER_001",
        updated_by="SYNTH_REVIEWER_001",
    )

    repository.record_review_outcome(**kwargs)
    repository.record_review_outcome(**kwargs)  # must not raise


def test_completed_review_different_outcome_replay_conflicts():
    """Verify recording a different outcome for an already-COMPLETED
    review raises HumanReviewConflictError."""
    repository, _ = make_repository()
    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))
    repository.record_review_outcome(
        review_id="SYN-REVIEW-001",
        review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
        completed_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        reviewer_actor_type_code="HUMAN_REVIEWER",
        reviewer_reference="SYNTH_REVIEWER_001",
        updated_by="SYNTH_REVIEWER_001",
    )

    with pytest.raises(HumanReviewConflictError):
        repository.record_review_outcome(
            review_id="SYN-REVIEW-001",
            review_outcome_code=HumanReviewOutcome.CLOSE_CASE,
            completed_at_utc=datetime(2026, 1, 15, 13, 5, 0, tzinfo=timezone.utc),
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference="SYNTH_REVIEWER_001",
            updated_by="SYNTH_REVIEWER_001",
        )


# =====================================================================
# CALLER-OWNED TRANSACTION SUPPORT
# =====================================================================
def test_supplied_session_write_does_not_commit_independently():
    """Verify a write made with a caller-supplied session is undone if
    the CALLER rolls back -- proving the repository method itself never
    calls commit() when session= is supplied (only the caller controls
    commit/rollback). (StaticPool shares one physical SQLite connection
    across sessions in this test double, so a cross-session
    read-before-commit check would not reliably demonstrate isolation;
    rollback is the deterministic proof instead.)"""
    repository, session_factory = make_repository()

    caller_session = session_factory()
    repository.create_review_request(
        make_review(review_id="SYN-REVIEW-001"), session=caller_session
    )
    caller_session.rollback()
    caller_session.close()

    from src.db.models import HumanReviewORM

    with session_factory() as other_session:
        assert other_session.get(HumanReviewORM, "SYN-REVIEW-001") is None


def test_write_without_supplied_session_preserves_current_behavior():
    """Verify calling without session= still commits and is immediately
    visible -- existing callers are unaffected by the refactor."""
    repository, session_factory = make_repository()

    repository.create_review_request(make_review(review_id="SYN-REVIEW-001"))

    from src.db.models import HumanReviewORM

    with session_factory() as other_session:
        assert other_session.get(HumanReviewORM, "SYN-REVIEW-001") is not None


def test_caller_owned_session_is_not_closed_by_repository_method():
    """Verify a caller-supplied session remains open and usable after
    the repository method returns -- the repository must never close a
    session it doesn't own."""
    repository, session_factory = make_repository()

    caller_session = session_factory()
    repository.create_review_request(
        make_review(review_id="SYN-REVIEW-001"), session=caller_session
    )

    # A closed SQLAlchemy Session raises when used; this must not raise.
    from src.db.models import HumanReviewORM

    assert caller_session.get(HumanReviewORM, "SYN-REVIEW-001") is not None

    caller_session.commit()
    caller_session.close()
