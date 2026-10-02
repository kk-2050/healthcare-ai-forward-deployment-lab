# File Name: test_human_review_transaction.py
# Purpose: Tests that a Human Review decision, its workflow_runs update, and its required audit event(s) can share one caller-owned SQLAlchemy transaction, and roll back together if any one write fails.
# Creation Date: 2026-09-22
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the cross-repository proof for Step 23C-2B1's core purpose
# (see its docstring section 1/7 and Step 23C-2A section 7): the
# previously-confirmed correctness gap where Human Review state and
# workflow state could be committed while a required audit event was
# silently lost. There is no orchestrator yet that does this wiring for
# real (that is Step 23C-2B2's job) -- this file exercises
# HumanReviewRepository and AuditRepository directly, sharing one
# caller-owned Session, to prove the repository-layer foundation itself
# supports atomic all-or-nothing persistence before any business logic
# is built on top of it. In-memory SQLite test double only -- no real
# SQL Server.

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import create_database_schema
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import (
    AuditEventORM,
    HumanReviewORM,
    PriorAuthorizationCaseORM,
    WorkflowDefinitionORM,
    WorkflowRunORM,
)
from src.db.repository import (
    AuditEventConflictError,
    AuditRepository,
    deterministic_human_review_event_id,
)
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot
from src.models.human_review import HumanReviewOutcome, HumanReviewRecord, HumanReviewStatus

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def make_test_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def seed_case_and_run(session_factory) -> None:
    """Creates the minimal synthetic parent rows (workflow_definitions,
    prior_authorization_cases, workflow_runs) a human_reviews row and
    its resume need, plus one pending human_reviews row."""
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
        session.add(
            PriorAuthorizationCaseORM(
                case_id="SYN-CASE-001",
                client_id="SYN-CLIENT-001",
                member_id="SYN-MEMBER-001",
                provider_id="SYN-PROVIDER-001",
                requested_service_code="SYN-SERVICE-100",
                requested_date=_NOW.date(),
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


def make_completed_event(**overrides) -> AuditEvent:
    data = {
        "event_id": deterministic_human_review_event_id(
            "SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED"
        ),
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "event_type_code": "HUMAN_REVIEW_COMPLETED",
        "event_category_code": AuditEventCategory.HUMAN,
        "source_component_code": "HUMAN_REVIEW_SERVICE",
        "actor_type_code": "HUMAN_REVIEWER",
        "actor_identifier": "SYNTH_REVIEWER_001",
        "result_code": "SUCCESS",
        "occurred_at_utc": _NOW,
        "created_at_utc": _NOW,
        "created_by": "SYNTH_REVIEWER_001",
    }
    data.update(overrides)
    return AuditEvent(**data)


def test_shared_transaction_persists_all_writes_together():
    """Verify a Human Review decision, its workflow_runs update, and its
    audit event all commit together under one caller-owned session."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    seed_case_and_run(session_factory)

    human_review_repository = HumanReviewRepository(session_factory=session_factory)
    audit_repository = AuditRepository(session_factory=session_factory)

    session = session_factory()
    try:
        human_review_repository.record_review_outcome(
            review_id="SYN-REVIEW-001",
            review_outcome_code=HumanReviewOutcome.ESCALATE,
            completed_at_utc=_NOW,
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference="SYNTH_REVIEWER_001",
            updated_by="SYNTH_REVIEWER_001",
            session=session,
        )
        audit_repository.save_workflow_run(
            WorkflowRunSnapshot(
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_status_code="COMPLETED",
                next_action_code="ROUTE_HUMAN_REVIEW",
                human_review_required=False,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=_NOW,
                completed_at_utc=_NOW,
                created_at_utc=_NOW,
                created_by="SYSTEM",
                updated_at_utc=_NOW,
                updated_by="SYSTEM",
            ),
            session=session,
        )
        audit_repository.append_audit_event(make_completed_event(), session=session)
        session.commit()
    finally:
        session.close()

    verify_session = session_factory()
    review = verify_session.get(HumanReviewORM, "SYN-REVIEW-001")
    run = verify_session.get(WorkflowRunORM, "SYN-TRACE-001")
    events = (
        verify_session.query(AuditEventORM)
        .filter(AuditEventORM.trace_id == "SYN-TRACE-001")
        .all()
    )
    verify_session.close()

    assert review.review_status_code == HumanReviewStatus.COMPLETED.value
    assert review.review_outcome_code == HumanReviewOutcome.ESCALATE.value
    assert run.workflow_status_code == "COMPLETED"
    assert len(events) == 1
    assert events[0].event_type_code == "HUMAN_REVIEW_COMPLETED"


def test_shared_transaction_rolls_back_all_writes_when_required_audit_write_fails():
    """Verify that if the required audit write fails (a genuine semantic
    conflict on the deterministic event_id) within the shared
    transaction, rolling back leaves NO partial state -- neither the
    Human Review decision nor the workflow_runs update survives, even
    though both of those individual writes had already succeeded
    in-session before the audit write failed. This is the exact gap
    Step 23C-1 identified: durable partial persistence must never
    happen silently."""
    engine = make_test_engine()
    create_database_schema(engine)
    session_factory = sessionmaker(bind=engine)
    seed_case_and_run(session_factory)

    human_review_repository = HumanReviewRepository(session_factory=session_factory)
    audit_repository = AuditRepository(session_factory=session_factory)

    # Pre-seed a CONFLICTING event under the same deterministic event_id
    # in a separate, already-committed transaction -- simulating "the
    # required audit write cannot succeed as intended."
    conflicting_event_id = deterministic_human_review_event_id(
        "SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED"
    )
    audit_repository.append_audit_event(
        make_completed_event(event_id=conflicting_event_id, result_code="FAILED")
    )

    session = session_factory()
    try:
        human_review_repository.record_review_outcome(
            review_id="SYN-REVIEW-001",
            review_outcome_code=HumanReviewOutcome.ESCALATE,
            completed_at_utc=_NOW,
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference="SYNTH_REVIEWER_001",
            updated_by="SYNTH_REVIEWER_001",
            session=session,
        )
        audit_repository.save_workflow_run(
            WorkflowRunSnapshot(
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                workflow_definition_id="SYN-WORKFLOW-DEF-001",
                workflow_status_code="COMPLETED",
                next_action_code="ROUTE_HUMAN_REVIEW",
                human_review_required=False,
                initiated_by_component_code="LANGGRAPH",
                started_at_utc=_NOW,
                completed_at_utc=_NOW,
                created_at_utc=_NOW,
                created_by="SYSTEM",
                updated_at_utc=_NOW,
                updated_by="SYSTEM",
            ),
            session=session,
        )
        with pytest.raises(AuditEventConflictError):
            audit_repository.append_audit_event(
                make_completed_event(result_code="SUCCESS"), session=session
            )
        session.rollback()
    finally:
        session.close()

    verify_session = session_factory()
    review = verify_session.get(HumanReviewORM, "SYN-REVIEW-001")
    run = verify_session.get(WorkflowRunORM, "SYN-TRACE-001")
    verify_session.close()

    # No partial state: the review is still pending, the run is still
    # HUMAN_REVIEW_REQUIRED -- neither the review nor the workflow
    # update survived the rollback, even though both succeeded
    # in-session before the audit write failed.
    assert review.review_status_code == HumanReviewStatus.REQUESTED.value
    assert review.review_outcome_code is None
    assert run.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
