# File Name: test_audit_repository.py
# Purpose: Tests the prototype schema creation and AuditRepository behavior using an in-memory SQLite test double.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the Task 18A persistence foundation: the ORM
# schema (src/db/base.py, src/db/models.py) and AuditRepository
# (src/db/repository.py). Every test runs against an in-memory SQLite
# engine -- a TEST DOUBLE only. SQLite is NOT the Phase 1
# production/prototype database; it is used here only to test
# repository behavior without requiring a live SQL Server connection.
# Task 18B performs the real local Microsoft SQL Server integration
# test.

import inspect
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db import repository as repository_module
from src.db.base import create_database_schema
from src.db.models import AuditEventORM, WorkflowRunORM
from src.db.repository import (
    AuditEventConflictError,
    AuditRepository,
    PersistenceError,
    _round_to_datetime2_precision,
    deterministic_human_review_event_id,
)
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot


def make_test_engine():
    """
    Builds an in-memory SQLite engine for offline repository tests.

    StaticPool keeps one shared connection alive for the whole engine,
    so the in-memory database persists across the multiple sessions a
    repository call opens. Without it, SQLite would otherwise hand out
    a fresh, empty in-memory database per connection, making the
    repository unusable across separate calls.
    """
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_repository(engine=None) -> AuditRepository:
    """Builds an AuditRepository backed by a freshly schema'd in-memory engine."""
    if engine is None:
        engine = make_test_engine()
    create_database_schema(engine)
    return AuditRepository(session_factory=sessionmaker(bind=engine))


def make_snapshot(**overrides) -> WorkflowRunSnapshot:
    """A minimal, fully valid synthetic WorkflowRunSnapshot."""
    data = {
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "workflow_definition_id": "SYN-WORKFLOW-DEF-001",
        "workflow_status_code": "COMPLETE",
        "human_review_required": False,
        "failure_category_code": None,
        "initiated_by_component_code": "LANGGRAPH",
        "started_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "created_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "created_by": "SYSTEM",
        "updated_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "updated_by": "SYSTEM",
    }
    data.update(overrides)
    return WorkflowRunSnapshot(**data)


def make_event(**overrides) -> AuditEvent:
    """A minimal, fully valid synthetic AuditEvent."""
    data = {
        "event_id": "SYN-EVENT-001",
        "trace_id": "SYN-TRACE-001",
        "case_id": "SYN-CASE-001",
        "event_type_code": "WORKFLOW_COMPLETED",
        "event_category_code": AuditEventCategory.WORKFLOW,
        "workflow_status_code": "COMPLETE",
        "workflow_step_id": "SYN-STEP-001",
        "source_component_code": "LANGGRAPH",
        "actor_type_code": "SYSTEM",
        "result_code": "SUCCESS",
        "failure_category_code": None,
        "occurred_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "created_at_utc": datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "created_by": "SYSTEM",
    }
    data.update(overrides)
    return AuditEvent(**data)


# =====================================================================
# SCHEMA TESTS
# =====================================================================
def test_schema_creates_workflow_runs_table():
    """Verify create_database_schema() creates the workflow_runs
    table -- the repository has nothing to read/write without it."""
    # TEST-014M
    engine = make_test_engine()
    create_database_schema(engine)

    assert "workflow_runs" in sa_inspect(engine).get_table_names()


def test_schema_creates_audit_events_table():
    """Verify create_database_schema() creates the audit_events
    table."""
    # TEST-014N
    engine = make_test_engine()
    create_database_schema(engine)

    assert "audit_events" in sa_inspect(engine).get_table_names()


# =====================================================================
# WORKFLOW RUN PERSISTENCE TESTS
# =====================================================================
def test_workflow_run_can_be_saved():
    """Verify a new workflow run snapshot can be saved without
    error."""
    # TEST-014O
    repository = make_repository()

    repository.save_workflow_run(make_snapshot())


def test_workflow_run_can_be_retrieved_by_trace_id():
    """Verify a saved workflow run can be retrieved by its trace_id,
    with every field intact."""
    # TEST-014P
    repository = make_repository()
    snapshot = make_snapshot()

    repository.save_workflow_run(snapshot)
    retrieved = repository.get_workflow_run("SYN-TRACE-001")

    assert retrieved is not None
    assert retrieved.trace_id == snapshot.trace_id
    assert retrieved.case_id == snapshot.case_id
    assert retrieved.workflow_status_code == snapshot.workflow_status_code
    assert retrieved.human_review_required == snapshot.human_review_required


def test_saving_same_trace_id_updates_instead_of_duplicating():
    """Verify saving a second snapshot for the same trace_id updates
    the existing row instead of creating a duplicate -- workflow_runs
    holds current state, one row per trace_id."""
    # TEST-014Q
    engine = make_test_engine()
    repository = make_repository(engine)

    repository.save_workflow_run(make_snapshot(workflow_status_code="PROCESSING"))
    repository.save_workflow_run(make_snapshot(workflow_status_code="COMPLETE"))

    retrieved = repository.get_workflow_run("SYN-TRACE-001")
    assert retrieved.workflow_status_code == "COMPLETE"

    with sessionmaker(bind=engine)() as session:
        row_count = session.query(WorkflowRunORM).count()
    assert row_count == 1


def test_missing_workflow_run_returns_none():
    """Verify retrieving a trace_id that was never saved returns None,
    not an exception or a fabricated result."""
    repository = make_repository()

    assert repository.get_workflow_run("SYN-TRACE-DOES-NOT-EXIST") is None


# =====================================================================
# AUDIT EVENT TESTS
# =====================================================================
def test_audit_event_can_be_appended():
    """Verify a single audit event can be appended without error."""
    # TEST-014R
    repository = make_repository()

    repository.append_audit_event(make_event())


def test_multiple_audit_events_are_retained():
    """Verify appending several audit events for the same trace_id
    retains all of them, not just the most recent one."""
    # TEST-014S
    repository = make_repository()

    repository.append_audit_event(make_event(event_id="SYN-EVENT-001"))
    repository.append_audit_event(make_event(event_id="SYN-EVENT-002"))
    repository.append_audit_event(make_event(event_id="SYN-EVENT-003"))

    events = repository.list_audit_events("SYN-TRACE-001")
    assert len(events) == 3


def test_audit_events_are_returned_in_chronological_order():
    """Verify list_audit_events() returns events ordered by
    occurred_at_utc, regardless of the order they were appended in."""
    # TEST-014T
    repository = make_repository()

    later = make_event(
        event_id="SYN-EVENT-LATER",
        occurred_at_utc=datetime(2026, 1, 15, 12, 5, 0, tzinfo=timezone.utc),
    )
    earlier = make_event(
        event_id="SYN-EVENT-EARLIER",
        occurred_at_utc=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )

    repository.append_audit_event(later)
    repository.append_audit_event(earlier)

    events = repository.list_audit_events("SYN-TRACE-001")
    assert [event.event_id for event in events] == [
        "SYN-EVENT-EARLIER",
        "SYN-EVENT-LATER",
    ]


def test_audit_events_are_isolated_by_trace_id():
    """Verify list_audit_events() for one trace_id never returns
    another trace's events."""
    # TEST-014U
    repository = make_repository()

    repository.append_audit_event(
        make_event(event_id="SYN-EVENT-A", trace_id="SYN-TRACE-A")
    )
    repository.append_audit_event(
        make_event(event_id="SYN-EVENT-B", trace_id="SYN-TRACE-B")
    )

    events_a = repository.list_audit_events("SYN-TRACE-A")
    assert [event.event_id for event in events_a] == ["SYN-EVENT-A"]


def test_duplicate_event_id_with_different_semantics_raises_conflict():
    """Verify appending a second event with an already-used event_id
    but DIFFERENT semantic content (e.g. a different result_code)
    raises AuditEventConflictError instead of silently overwriting the
    first event (Step 23C-2B1)."""
    # TEST-014V
    repository = make_repository()

    repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))

    with pytest.raises(AuditEventConflictError):
        repository.append_audit_event(
            make_event(event_id="SYN-EVENT-DUP", result_code="FAILED")
        )


def test_duplicate_event_id_with_identical_semantics_is_idempotent():
    """Verify appending the exact same event twice (same event_id, same
    semantic fields) is a safe no-op, not an error and not a duplicate
    row -- this is what makes a Human Review decision retry after a
    partial-failure rollback safe (Step 23C-2A/2B1)."""
    repository = make_repository()

    repository.append_audit_event(make_event(event_id="SYN-EVENT-REPLAY"))
    repository.append_audit_event(make_event(event_id="SYN-EVENT-REPLAY"))  # no raise

    events = repository.list_audit_events("SYN-TRACE-001")
    assert [event.event_id for event in events] == ["SYN-EVENT-REPLAY"]


def test_replay_with_same_occurred_at_utc_and_different_created_at_utc_is_idempotent():
    """Verify a replay that reuses the ORIGINAL occurred_at_utc (the
    logical transition time) but has a different created_at_utc (the
    row-write timestamp, naturally different on a retry) is still
    treated as an identical, idempotent replay -- created_at_utc is
    CONTROL/provenance metadata, excluded from the semantic comparison
    (see _AUDIT_EVENT_SEMANTIC_FIELDS in src/db/repository.py)."""
    repository = make_repository()
    original_occurred_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    repository.append_audit_event(
        make_event(
            event_id="SYN-EVENT-RETRY",
            occurred_at_utc=original_occurred_at,
            created_at_utc=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
    )
    repository.append_audit_event(
        make_event(
            event_id="SYN-EVENT-RETRY",
            occurred_at_utc=original_occurred_at,  # reused, not regenerated
            created_at_utc=datetime(2026, 1, 15, 12, 0, 5, tzinfo=timezone.utc),
        )
    )  # must not raise

    events = repository.list_audit_events("SYN-TRACE-001")
    assert len(events) == 1


def test_replay_with_different_occurred_at_utc_is_a_conflict():
    """Verify a replay with a DIFFERENT occurred_at_utc than the
    original is treated as a semantic conflict, not an idempotent
    replay -- occurred_at_utc is documented as a BUSINESS field
    (docs/database/data_dictionary.md: "When the event actually
    occurred"), part of the event's meaning, not incidental retry
    metadata. A caller must reuse the original transition's
    occurred_at_utc to replay it safely."""
    repository = make_repository()

    repository.append_audit_event(
        make_event(
            event_id="SYN-EVENT-RETRY",
            occurred_at_utc=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
    )

    with pytest.raises(AuditEventConflictError):
        repository.append_audit_event(
            make_event(
                event_id="SYN-EVENT-RETRY",
                occurred_at_utc=datetime(2026, 1, 15, 12, 0, 5, tzinfo=timezone.utc),
            )
        )


# =====================================================================
# DATETIME2(3) CANONICALIZATION (Step 23C-2D3A2)
# Purpose:
# Real SQL Server persists every *_at_utc column as
# mssql.DATETIME2(precision=3) -- millisecond precision -- so a Python
# datetime carrying microsecond precision (e.g. datetime.now(timezone.utc))
# is rounded the moment it is first persisted. Step 23C-2D3A1 confirmed
# directly against real SQL Server (a table-free SELECT CAST, five
# cases including an exact half-millisecond tie and a day boundary) that
# this rounding is to the NEAREST millisecond, ties away from zero -- not
# truncation, not banker's rounding. _round_to_datetime2_precision()
# reproduces that exact rule so a legitimate replay using the ORIGINAL,
# un-rounded occurred_at_utc value compares equal to the already-rounded
# persisted value, without weakening genuine conflict detection.
# =====================================================================
def test_round_to_datetime2_precision_rounds_down():
    """.158200 -> .158000 (ordinary round-down case)."""
    value = datetime(2026, 1, 15, 12, 0, 0, 158200)
    assert _round_to_datetime2_precision(value) == datetime(2026, 1, 15, 12, 0, 0, 158000)


def test_round_to_datetime2_precision_rounds_up():
    """.158954 -> .159000 -- the exact value observed in the real Step
    23C-2D3A test failure against real SQL Server."""
    value = datetime(2026, 1, 15, 12, 0, 0, 158954)
    assert _round_to_datetime2_precision(value) == datetime(2026, 1, 15, 12, 0, 0, 159000)


def test_round_to_datetime2_precision_exact_tie_rounds_up():
    """.158500 -> .159000 -- an exact half-millisecond tie must round
    AWAY FROM ZERO (matching real SQL Server, verified directly in Step
    23C-2D3A1), not round-half-to-even/banker's rounding (which would
    give .158, since 158 is even)."""
    value = datetime(2026, 1, 15, 12, 0, 0, 158500)
    assert _round_to_datetime2_precision(value) == datetime(2026, 1, 15, 12, 0, 0, 159000)


def test_round_to_datetime2_precision_second_rollover():
    """.999600 -> the next second, .000000 -- rounding must carry across
    a second boundary, not overflow into an invalid microsecond value."""
    value = datetime(2026, 1, 15, 12, 0, 0, 999600)
    assert _round_to_datetime2_precision(value) == datetime(2026, 1, 15, 12, 0, 1, 0)


def test_round_to_datetime2_precision_day_rollover():
    """23:59:59.999500 -> the next day, 00:00:00.000000 -- rounding must
    correctly cascade through second/minute/hour/day boundaries, exactly
    as real SQL Server does (verified directly in Step 23C-2D3A1)."""
    value = datetime(2026, 1, 15, 23, 59, 59, 999500)
    assert _round_to_datetime2_precision(value) == datetime(2026, 1, 16, 0, 0, 0, 0)


def test_round_to_datetime2_precision_already_aligned_is_unchanged():
    """A value already exactly on a millisecond boundary must round to
    itself, not drift."""
    value = datetime(2026, 1, 15, 12, 0, 0, 159000)
    assert _round_to_datetime2_precision(value) == value


def test_audit_replay_survives_real_datetime2_rounding():
    """
    Reproduces the exact Step 23C-2D3A/23C-2D3A1 defect without
    requiring real SQL Server: simulates the persisted first-write state
    (occurred_at_utc already rounded to .159000, as real SQL Server
    would have stored it) directly, then replays the SAME deterministic
    event_id using the ORIGINAL, un-rounded Python value (.158954) --
    exactly what a legitimate retry of the same logical Human Review
    transition looks like. Before this step's fix, this raised
    AuditEventConflictError; after the fix, it must be treated as an
    idempotent replay: no exception, no second row.
    """
    engine = make_test_engine()
    repository = make_repository(engine)
    session_factory = sessionmaker(bind=engine)

    # Simulate the row real SQL Server would already have persisted --
    # occurred_at_utc pre-rounded to the millisecond, exactly as the
    # database itself would produce, not as this repository's own write
    # path (which this test does not exercise for the first write).
    already_persisted_occurred_at = datetime(2026, 1, 15, 12, 0, 0, 159000)
    with session_factory() as session:
        session.add(
            AuditEventORM(
                event_id="SYN-EVENT-DATETIME2-REPLAY",
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                event_type_code="HUMAN_REVIEW_COMPLETED",
                event_category_code="HUMAN",
                source_component_code="HUMAN_REVIEW_SERVICE",
                actor_type_code="HUMAN_REVIEWER",
                actor_identifier="SYN-REVIEWER-001",
                result_code="SUCCESS",
                occurred_at_utc=already_persisted_occurred_at,
                schema_version="1",
                created_at_utc=already_persisted_occurred_at,
                created_by="SYSTEM",
            )
        )
        session.commit()

    # Replay with the ORIGINAL, un-rounded occurred_at_utc -- exactly
    # what a caller correctly following resume_after_human_review()'s
    # documented contract (reuse the original decision_at_utc) would
    # supply on a retry.
    original_occurred_at = datetime(2026, 1, 15, 12, 0, 0, 158954, tzinfo=timezone.utc)
    repository.append_audit_event(
        AuditEvent(
            event_id="SYN-EVENT-DATETIME2-REPLAY",
            trace_id="SYN-TRACE-001",
            case_id="SYN-CASE-001",
            event_type_code="HUMAN_REVIEW_COMPLETED",
            event_category_code=AuditEventCategory.HUMAN,
            source_component_code="HUMAN_REVIEW_SERVICE",
            actor_type_code="HUMAN_REVIEWER",
            actor_identifier="SYN-REVIEWER-001",
            result_code="SUCCESS",
            occurred_at_utc=original_occurred_at,
            schema_version="1",
            created_at_utc=original_occurred_at,
            created_by="SYSTEM",
        )
    )  # must not raise

    events = repository.list_audit_events("SYN-TRACE-001")
    assert len(events) == 1


def test_audit_replay_with_genuinely_different_millisecond_still_conflicts():
    """
    Proves the DATETIME2(3) canonicalization fix does NOT weaken genuine
    conflict detection: a persisted value of .159000 and an incoming
    value that canonicalizes to a genuinely different millisecond
    (.161000 -- 2ms apart, not sub-millisecond noise) must still raise
    AuditEventConflictError, and the existing row must remain unchanged.
    """
    engine = make_test_engine()
    repository = make_repository(engine)
    session_factory = sessionmaker(bind=engine)

    persisted_occurred_at = datetime(2026, 1, 15, 12, 0, 0, 159000)
    with session_factory() as session:
        session.add(
            AuditEventORM(
                event_id="SYN-EVENT-GENUINE-CONFLICT",
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                event_type_code="HUMAN_REVIEW_COMPLETED",
                event_category_code="HUMAN",
                source_component_code="HUMAN_REVIEW_SERVICE",
                actor_type_code="HUMAN_REVIEWER",
                actor_identifier="SYN-REVIEWER-001",
                result_code="SUCCESS",
                occurred_at_utc=persisted_occurred_at,
                schema_version="1",
                created_at_utc=persisted_occurred_at,
                created_by="SYSTEM",
            )
        )
        session.commit()

    genuinely_different_occurred_at = datetime(
        2026, 1, 15, 12, 0, 0, 161000, tzinfo=timezone.utc
    )
    with pytest.raises(AuditEventConflictError):
        repository.append_audit_event(
            AuditEvent(
                event_id="SYN-EVENT-GENUINE-CONFLICT",
                trace_id="SYN-TRACE-001",
                case_id="SYN-CASE-001",
                event_type_code="HUMAN_REVIEW_COMPLETED",
                event_category_code=AuditEventCategory.HUMAN,
                source_component_code="HUMAN_REVIEW_SERVICE",
                actor_type_code="HUMAN_REVIEWER",
                actor_identifier="SYN-REVIEWER-001",
                result_code="SUCCESS",
                occurred_at_utc=genuinely_different_occurred_at,
                schema_version="1",
                created_at_utc=genuinely_different_occurred_at,
                created_by="SYSTEM",
            )
        )

    with session_factory() as session:
        row = session.get(AuditEventORM, "SYN-EVENT-GENUINE-CONFLICT")
    assert row.occurred_at_utc == persisted_occurred_at


# =====================================================================
# DETERMINISTIC HUMAN REVIEW AUDIT EVENT ID
# =====================================================================
def test_deterministic_event_id_is_stable():
    """Verify the same review_id + event_type_code always produce the
    same event_id."""
    first = deterministic_human_review_event_id("SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED")
    second = deterministic_human_review_event_id("SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED")

    assert first == second
    assert len(first) == 36  # standard UUID string length


def test_deterministic_event_id_differs_by_review_id():
    """Verify a different review_id produces a different event_id for
    the same event_type_code."""
    first = deterministic_human_review_event_id("SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED")
    second = deterministic_human_review_event_id("SYN-REVIEW-002", "HUMAN_REVIEW_COMPLETED")

    assert first != second


def test_deterministic_event_id_differs_by_event_type_code():
    """Verify a different event_type_code produces a different
    event_id for the same review_id."""
    first = deterministic_human_review_event_id("SYN-REVIEW-001", "HUMAN_REVIEW_COMPLETED")
    second = deterministic_human_review_event_id("SYN-REVIEW-001", "WORKFLOW_COMPLETED")

    assert first != second


# =====================================================================
# CALLER-OWNED TRANSACTION SUPPORT
# =====================================================================
def test_save_workflow_run_with_supplied_session_does_not_commit_independently():
    """Verify save_workflow_run(session=...) is undone by the caller's
    rollback -- proving the method itself never commits when session=
    is supplied (mirrors the identical HumanReviewRepository test)."""
    engine = make_test_engine()
    repository = make_repository(engine)
    session_factory = sessionmaker(bind=engine)

    caller_session = session_factory()
    repository.save_workflow_run(make_snapshot(), session=caller_session)
    caller_session.rollback()
    caller_session.close()

    assert repository.get_workflow_run("SYN-TRACE-001") is None


def test_append_audit_event_with_supplied_session_does_not_commit_independently():
    """Verify append_audit_event(session=...) is undone by the caller's
    rollback -- proving the method itself never commits when session=
    is supplied."""
    engine = make_test_engine()
    repository = make_repository(engine)
    session_factory = sessionmaker(bind=engine)

    caller_session = session_factory()
    repository.append_audit_event(make_event(), session=caller_session)
    caller_session.rollback()
    caller_session.close()

    assert repository.list_audit_events("SYN-TRACE-001") == []


def test_supplied_session_write_without_caller_commit_is_not_closed():
    """Verify a caller-supplied session remains open and usable after
    append_audit_event() returns -- the repository must never close a
    session it doesn't own."""
    engine = make_test_engine()
    repository = make_repository(engine)
    session_factory = sessionmaker(bind=engine)

    caller_session = session_factory()
    repository.append_audit_event(make_event(), session=caller_session)

    # A closed session would raise here; this must not raise.
    assert caller_session.get(AuditEventORM, "SYN-EVENT-001") is not None

    caller_session.commit()
    caller_session.close()


def test_write_without_supplied_session_preserves_current_behavior():
    """Verify calling without session= still commits immediately --
    existing callers (e.g. src/workflow/orchestrator.py) are unaffected
    by the caller-owned-transaction refactor."""
    repository = make_repository()

    repository.save_workflow_run(make_snapshot())
    repository.append_audit_event(make_event())

    assert repository.get_workflow_run("SYN-TRACE-001") is not None
    assert len(repository.list_audit_events("SYN-TRACE-001")) == 1


# =====================================================================
# ATOMIC RESUME CLAIM TESTS (Step 24B-2)
# Purpose:
# Protect claim_workflow_run_for_resume()'s race-safe conditional-UPDATE
# behavior: PENDING_RESUME/CONTINUE_PROCESSING -> PROCESSING/NULL, and
# its deterministic refusal when the precondition does not hold.
# =====================================================================
def make_pending_resume_snapshot(**overrides) -> WorkflowRunSnapshot:
    """A synthetic WorkflowRunSnapshot already in the exact state a real
    CONTINUE_WORKFLOW Human Review decision would have produced."""
    data = {
        "workflow_status_code": "PENDING_RESUME",
        "next_action_code": "CONTINUE_PROCESSING",
        "human_review_required": False,
    }
    data.update(overrides)
    return make_snapshot(**data)


def test_claim_transitions_pending_resume_to_processing():
    """Verify a successful claim moves workflow_status_code from
    PENDING_RESUME to PROCESSING."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())

    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert claimed is True
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PROCESSING"


def test_claim_clears_next_action_to_null():
    """Verify a successful claim clears next_action_code to NULL --
    CONTINUE_PROCESSING's job (telling the caller what to do) is done
    once the claim succeeds."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())

    repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.next_action_code is None


def test_claim_updates_updated_at_utc_and_updated_by():
    """Verify a successful claim persists the supplied updated_at_utc/
    updated_by."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())
    claim_time = datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc)

    repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001", updated_at_utc=claim_time, updated_by="RESUME_SERVICE"
    )

    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.updated_by == "RESUME_SERVICE"


def test_claim_does_not_change_unrelated_fields():
    """Verify a successful claim leaves identity/unrelated fields
    (case_id, workflow_definition_id, started_at_utc, created_at_utc,
    created_by, human_review_required, failure_category_code) exactly
    as they were."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())

    repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.case_id == "SYN-CASE-001"
    assert saved.workflow_definition_id == "SYN-WORKFLOW-DEF-001"
    assert saved.human_review_required is False
    assert saved.failure_category_code is None


def test_claim_fails_when_status_is_not_pending_resume():
    """Verify a claim attempt against a run NOT in PENDING_RESUME is
    refused (0 rows affected), and the run's state is untouched."""
    repository = make_repository()
    repository.save_workflow_run(make_snapshot(workflow_status_code="PROCESSING"))

    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert claimed is False
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PROCESSING"


def test_claim_fails_when_next_action_is_not_continue_processing():
    """Verify a claim attempt against a run whose next_action_code does
    not match CONTINUE_PROCESSING is refused, even if
    workflow_status_code is PENDING_RESUME -- both preconditions are
    required together."""
    repository = make_repository()
    repository.save_workflow_run(
        make_pending_resume_snapshot(next_action_code="ROUTE_HUMAN_REVIEW")
    )

    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert claimed is False


def test_claim_fails_for_unknown_trace_id():
    """Verify a claim attempt against a trace_id with no workflow_runs
    row at all is refused (0 rows affected), not an error."""
    repository = make_repository()

    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-DOES-NOT-EXIST",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert claimed is False


def test_second_claim_after_successful_claim_is_refused():
    """Verify the exact race-safety property: once a claim succeeds,
    an immediately-following second claim attempt for the same
    trace_id is refused (0 rows affected) -- simulating a concurrent
    duplicate resume request arriving just after the first succeeded."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())

    first_claim = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )
    second_claim = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 1, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert first_claim is True
    assert second_claim is False
    # The row must still reflect the FIRST claim's write, never a second
    # transition or corruption from the refused second attempt.
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PROCESSING"
    assert saved.updated_by == "SYSTEM"


def test_claim_supports_caller_owned_session():
    """Verify claim_workflow_run_for_resume(session=...) is undone by
    the caller's rollback -- proving the method itself never commits
    when session= is supplied, identical in spirit to every other
    caller-owned-session test in this file."""
    engine = make_test_engine()
    repository = make_repository(engine)
    repository.save_workflow_run(make_pending_resume_snapshot())
    session_factory = sessionmaker(bind=engine)

    caller_session = session_factory()
    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
        session=caller_session,
    )
    caller_session.rollback()
    caller_session.close()

    assert claimed is True  # the claim itself succeeded within the transaction
    # but was never committed, so a fresh read shows the ORIGINAL state.
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PENDING_RESUME"
    assert saved.next_action_code == "CONTINUE_PROCESSING"


# =====================================================================
# ATOMIC RESUME CLAIM COMPENSATION TESTS (Step 24B-4A)
# Purpose:
# Protect claim_workflow_run_for_resume()'s generalized bidirectional
# behavior: the SAME conditional-UPDATE primitive, called with reversed
# arguments, race-safely reverts a claim
# (PROCESSING/NULL -> PENDING_RESUME/CONTINUE_PROCESSING) when
# continuation setup fails before graph invocation -- see
# src/workflow/orchestrator.py's _revert_resume_claim().
# =====================================================================
def test_compensation_transitions_processing_to_pending_resume():
    """Verify the reverse conditional transition (compensation):
    PROCESSING/NULL -> PENDING_RESUME/CONTINUE_PROCESSING, using the
    same claim method with swapped arguments."""
    repository = make_repository()
    repository.save_workflow_run(
        make_snapshot(workflow_status_code="PROCESSING", next_action_code=None)
    )

    reverted = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        expected_status="PROCESSING",
        expected_next_action=None,
        new_status="PENDING_RESUME",
        new_next_action="CONTINUE_PROCESSING",
        updated_at_utc=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert reverted is True
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PENDING_RESUME"
    assert saved.next_action_code == "CONTINUE_PROCESSING"


def test_compensation_refused_when_state_no_longer_matches():
    """Verify compensation is refused (0 rows affected) if the row is
    no longer in PROCESSING/NULL -- e.g. it already reached a genuine
    disposition like HUMAN_REVIEW_REQUIRED."""
    repository = make_repository()
    repository.save_workflow_run(
        make_snapshot(
            workflow_status_code="HUMAN_REVIEW_REQUIRED",
            next_action_code="ROUTE_HUMAN_REVIEW",
            human_review_required=True,
        )
    )

    reverted = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        expected_status="PROCESSING",
        expected_next_action=None,
        new_status="PENDING_RESUME",
        new_next_action="CONTINUE_PROCESSING",
        updated_at_utc=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert reverted is False


def test_refused_compensation_does_not_overwrite_changed_row():
    """Verify a refused compensation attempt leaves the row's actual
    current state completely untouched -- proving the conditional
    UPDATE never silently overwrites a row that changed for a
    legitimate reason since the claim."""
    repository = make_repository()
    repository.save_workflow_run(
        make_snapshot(
            workflow_status_code="HUMAN_REVIEW_REQUIRED",
            next_action_code="ROUTE_HUMAN_REVIEW",
            human_review_required=True,
        )
    )

    repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        expected_status="PROCESSING",
        expected_next_action=None,
        new_status="PENDING_RESUME",
        new_next_action="CONTINUE_PROCESSING",
        updated_at_utc=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
    assert saved.next_action_code == "ROUTE_HUMAN_REVIEW"
    assert saved.human_review_required is True


def test_original_claim_direction_unaffected_by_generalization():
    """Regression: the default (claim) direction -- no new_next_action
    argument supplied -- still clears next_action_code to NULL exactly
    as before the bidirectional generalization (Step 24B-2 behavior
    unchanged)."""
    repository = make_repository()
    repository.save_workflow_run(make_pending_resume_snapshot())

    claimed = repository.claim_workflow_run_for_resume(
        "SYN-TRACE-001",
        updated_at_utc=datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        updated_by="SYSTEM",
    )

    assert claimed is True
    saved = repository.get_workflow_run("SYN-TRACE-001")
    assert saved.workflow_status_code == "PROCESSING"
    assert saved.next_action_code is None


# =====================================================================
# FAILURE / TRANSACTION TESTS
# =====================================================================
def test_failed_write_rolls_back_and_repository_still_usable():
    """Verify a failed write (a semantically-conflicting duplicate
    event_id) rolls back cleanly, and the repository can still be used
    successfully afterward -- one failure must not corrupt the
    repository for later calls."""
    # TEST-014W
    repository = make_repository()
    repository.append_audit_event(make_event(event_id="SYN-EVENT-DUP"))

    with pytest.raises(AuditEventConflictError):
        repository.append_audit_event(
            make_event(event_id="SYN-EVENT-DUP", result_code="FAILED")
        )

    repository.append_audit_event(make_event(event_id="SYN-EVENT-AFTER-FAILURE"))
    events = repository.list_audit_events("SYN-TRACE-001")

    assert {event.event_id for event in events} == {
        "SYN-EVENT-DUP",
        "SYN-EVENT-AFTER-FAILURE",
    }


def test_repository_does_not_mutate_workflow_run_snapshot_input():
    """Verify saving a snapshot never modifies the caller's
    WorkflowRunSnapshot object."""
    # TEST-014X
    repository = make_repository()
    snapshot = make_snapshot()
    original_status = snapshot.workflow_status_code

    repository.save_workflow_run(snapshot)

    assert snapshot.workflow_status_code == original_status


def test_repository_does_not_mutate_audit_event_input():
    """Verify appending an event never modifies the caller's
    AuditEvent object."""
    # TEST-014Y
    repository = make_repository()
    event = make_event()
    original_event_type = event.event_type_code

    repository.append_audit_event(event)

    assert event.event_type_code == original_event_type


# =====================================================================
# SECURITY BOUNDARY TESTS
# =====================================================================
def test_audit_models_contain_no_raw_clinical_or_fhir_fields():
    """Verify neither persistence model exposes raw clinical text or
    FHIR payload fields -- the audit layer records workflow activity,
    not raw healthcare content."""
    # TEST-014Z
    forbidden_fields = {
        "clinical_notes",
        "fhir_payload",
        "ai_prompt",
        "ai_response",
        "patient_name",
        "date_of_birth",
        "address",
        "phone",
        "email",
        "member_id",
        "provider_id",
    }

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_audit_models_contain_no_secret_or_connection_fields():
    """Verify neither persistence model exposes an API key, secret, or
    connection-string field."""
    # TEST-014AA
    forbidden_fields = {"api_key", "connection_string", "password", "token"}

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_audit_models_contain_no_approval_denial_fields():
    """Verify neither persistence model exposes an approval, denial,
    or medical-necessity field -- the audit layer never makes or
    records a clinical decision."""
    # TEST-014AB
    forbidden_fields = {"approval", "denial", "medical_necessity"}

    snapshot_fields = set(WorkflowRunSnapshot.model_fields.keys())
    event_fields = set(AuditEvent.model_fields.keys())

    assert not (forbidden_fields & snapshot_fields)
    assert not (forbidden_fields & event_fields)


def test_repository_uses_no_ai_dependency():
    """Verify src/db/repository.py imports nothing from src/ai/* and
    does not import an OpenAI/LLM library -- this repository is
    persistence-only and must never depend on AI."""
    # TEST-014AC
    import_lines = [
        line.strip()
        for line in inspect.getsource(repository_module).splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]

    assert not any("src.ai" in line for line in import_lines)
    assert not any("openai" in line.lower() for line in import_lines)


def test_repository_tests_require_no_live_sql_server(monkeypatch):
    """
    Verify these repository tests never attempt a real network
    connection -- SQLite in-memory is a TEST DOUBLE only; Task 18B
    performs the real local Microsoft SQL Server integration test.
    """
    # TEST-014AD
    import socket

    def _blocked_connect(self, *args, **kwargs):
        raise AssertionError("network connection attempted during repository test")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

    repository = make_repository()
    repository.save_workflow_run(make_snapshot())
    repository.append_audit_event(make_event())

    assert repository.get_workflow_run("SYN-TRACE-001") is not None
