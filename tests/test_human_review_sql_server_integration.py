# File Name: test_human_review_sql_server_integration.py
# Purpose: Opt-in real SQL Server integration test for the atomic Human Review decision-transition boundary (src/workflow/human_review_service.py).
# Creation Date: 2026-09-23
# Author: K.Kashiwagi
#
# Module Explanation:
# Same opt-in discipline as tests/test_workflow_orchestrator_integration.py
# (see that file for the established pattern this one reuses exactly):
# skipped entirely unless RUN_SQL_SERVER_INTEGRATION_TESTS=1 is set,
# requires SQL Server already migrated to revision f2fb22e3a41e with the
# stable Phase 1 reference catalog already loaded (95 rows / 14 tables,
# including the six CASE_CLOSE_* reason rows -- Steps 23C-2C3/2C4). It
# never calls a real FHIR service or Azure OpenAI, and never wires
# LangGraph -- it exercises resume_after_human_review() directly, the
# same way the existing file exercises run_prior_authorization_workflow()
# directly.
#
# Two independent synthetic fixtures, each with its own fixed IDs, so the
# two tests never interfere with each other even if run out of order:
# - test_close_case_decision_persists_atomically_against_real_sql_server:
#   the success path -- proves human_reviews, workflow_runs,
#   prior_authorization_cases, and audit_events all change together, in
#   one real SQL Server transaction.
# - test_audit_conflict_rolls_back_full_close_case_transaction: the
#   failure path -- pre-seeds a deliberately conflicting audit_events row
#   under the SAME deterministic event_id the service will generate, so
#   the conflict is only discovered after the review/workflow_run/case
#   writes have already been attempted inside the transaction. Proves
#   real SQL Server rolls all of them back together, not just the audit
#   write.
#
# All fixture setup (client, case, workflow_run, human_review, and the
# one deliberately conflicting audit event in the failure test) uses raw
# SQL, exactly like the existing integration test's client/case fixture
# -- deliberately never the ORM/repository code path this test exists to
# validate, so the fixture never quietly depends on the thing under test.
# Every synthetic row is cleaned up in a finally block, in FK-safe
# reverse dependency order, whether the test passes or fails.

import os
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from src.config.database import load_database_settings
from src.db.case_repository import CaseRepository
from src.db.engine import create_sql_server_engine
from src.db.human_review_repository import HumanReviewRepository
from src.db.reference_data import workflow_definition_id as get_workflow_definition_id
from src.db.repository import (
    AuditEventConflictError,
    AuditRepository,
    _round_to_datetime2_precision,
    deterministic_human_review_event_id,
)
from src.models.human_review import HumanReviewOutcome
from src.workflow.human_review_service import resume_after_human_review

_ENV_FLAG = "RUN_SQL_SERVER_INTEGRATION_TESTS"

pytestmark = pytest.mark.skipif(
    os.environ.get(_ENV_FLAG) != "1",
    reason=(
        f"Opt-in real SQL Server integration test -- set {_ENV_FLAG}=1 to run. "
        "Requires SQL Server already migrated to f2fb22e3a41e with reference "
        "data (including the six CASE_CLOSE_* reason rows) already loaded via "
        "src/db/reference_data.py."
    ),
)

# ---- Scenario 1 (success path) synthetic IDs ----
_CLIENT_ID_1 = "cli_hr_integration_test_001"
_CASE_ID_1 = "case_hr_integration_test_001"
_TRACE_ID_1 = "trace_hr_integration_test_001"
_REVIEW_ID_1 = "review_hr_integration_test_001"
_REVIEWER_REFERENCE_1 = "SYN-REVIEWER-INTEGRATION-001"

# ---- Scenario 2 (atomic rollback path) synthetic IDs -- fully distinct ----
_CLIENT_ID_2 = "cli_hr_integration_test_002"
_CASE_ID_2 = "case_hr_integration_test_002"
_TRACE_ID_2 = "trace_hr_integration_test_002"
_REVIEW_ID_2 = "review_hr_integration_test_002"
_REVIEWER_REFERENCE_2 = "SYN-REVIEWER-INTEGRATION-002"

_REASON_CODE_HUMAN_REVIEW = "HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION"
_REASON_CODE_CASE_CLOSE = "CASE_CLOSE_COMPLETED"


def _utc_naive(value: datetime) -> datetime:
    """Normalizes a datetime for equality comparison against a value read
    back from real SQL Server. Two distinct effects are needed, for two
    distinct reasons -- both delegated to the exact same helpers
    src/db/repository.py's own audit semantic comparison uses, rather
    than re-implementing subtly different rounding logic a second time
    in this test file:

    1. pyodbc returns naive datetimes for mssql.DATETIME2 columns, and
       SQLAlchemy's default expire_on_commit=True means several values
       in this test are re-read from the database after commit -- so a
       locally-generated tz-aware `datetime.now(timezone.utc)` would
       otherwise fail equality against the value read back, even though
       both represent the exact same UTC instant.
    2. Real SQL Server persists every *_at_utc column as
       mssql.DATETIME2(precision=3) -- millisecond precision -- so a
       Python value carrying microsecond precision is rounded (to the
       nearest millisecond, ties away from zero -- verified directly
       against real SQL Server in Step 23C-2D3A1) the moment it is first
       persisted. Comparing without accounting for this would make this
       test's own assertions fail on the exact same precision mismatch
       that Step 23C-2D3A's first real-SQL run exposed as a genuine
       production defect (since fixed in
       src/db/repository.py::_normalize_for_comparison()).
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return _round_to_datetime2_precision(value)


def _make_session_factory():
    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    return sessionmaker(bind=engine), engine


def _assert_synthetic_ids_absent(
    session, *, client_id: str, case_id: str, trace_id: str, review_id: str
) -> None:
    """SELECT-only precondition check. Fails loudly, rather than silently
    deleting unknown leftover state, if any of these IDs already exist --
    stale rows from a previous interrupted run must be investigated, not
    silently discarded."""
    existing = session.execute(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM clients WHERE client_id = :client_id) AS c1, "
            "(SELECT COUNT(*) FROM prior_authorization_cases WHERE case_id = :case_id) AS c2, "
            "(SELECT COUNT(*) FROM workflow_runs WHERE trace_id = :trace_id) AS c3, "
            "(SELECT COUNT(*) FROM human_reviews WHERE review_id = :review_id) AS c4"
        ),
        {
            "client_id": client_id,
            "case_id": case_id,
            "trace_id": trace_id,
            "review_id": review_id,
        },
    ).one()
    assert existing.c1 == existing.c2 == existing.c3 == existing.c4 == 0, (
        "Stale synthetic Human Review integration-test rows already exist "
        f"for client_id={client_id!r}/case_id={case_id!r}/trace_id={trace_id!r}/"
        f"review_id={review_id!r}. Refusing to silently overwrite or delete "
        "unknown leftover state -- investigate and clean up manually before "
        "re-running this test."
    )


def _insert_synthetic_client(session, client_id: str, now) -> None:
    """Raw SQL insert -- clients has no SQLAlchemy ORM class (Wave 1, raw
    DDL only; see src/db/models.py's Foreign Key Policy)."""
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
            "client_id": client_id,
            "client_code": "HR_INTEGRATION_TEST_CLIENT",
            "client_name": "Human Review Integration Test Client (synthetic)",
            "now": now,
        },
    )


def _insert_synthetic_case(session, case_id: str, client_id: str, now) -> None:
    """Raw SQL insert, deliberately not going through CaseRepository --
    this fixture must not depend on the code path being tested."""
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
            "case_id": case_id,
            "client_id": client_id,
            "member_id": "SYN-MEMBER-HR-INTEGRATION",
            "provider_id": "SYN-PROVIDER-HR-INTEGRATION",
            "requested_service_code": "SYN-LUMBAR-MRI",
            "requested_date": date(2026, 1, 15),
            "now": now,
        },
    )


def _insert_synthetic_workflow_run(session, trace_id: str, case_id: str, now) -> None:
    """Raw SQL insert -- deliberately not going through AuditRepository,
    for the same reason as the case insert above. Represents a run that
    has already reached HUMAN_REVIEW_REQUIRED and is awaiting decision."""
    session.execute(
        sa.text(
            "INSERT INTO workflow_runs "
            "(trace_id, case_id, workflow_definition_id, workflow_status_code, "
            "next_action_code, human_review_required, failure_category_code, "
            "processing_department_id, processing_location_id, "
            "initiated_by_component_code, started_at_utc, completed_at_utc, "
            "schema_version, metadata_json, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:trace_id, :case_id, :workflow_definition_id, "
            "'HUMAN_REVIEW_REQUIRED', 'ROUTE_HUMAN_REVIEW', 1, NULL, NULL, NULL, "
            "'FASTAPI', :now, NULL, '1', NULL, :now, 'SYSTEM', :now, 'SYSTEM', 0)"
        ),
        {
            "trace_id": trace_id,
            "case_id": case_id,
            "workflow_definition_id": get_workflow_definition_id(),
            "now": now,
        },
    )


def _insert_synthetic_human_review(
    session, review_id: str, trace_id: str, case_id: str, now
) -> None:
    """Raw SQL insert -- deliberately not going through
    HumanReviewRepository.create_review_request(), for the same reason as
    the other fixture inserts above. Represents a review still REQUESTED,
    awaiting a decision."""
    session.execute(
        sa.text(
            "INSERT INTO human_reviews "
            "(review_id, trace_id, case_id, review_status_code, review_outcome_code, "
            "reason_code, assigned_department_id, assigned_location_id, "
            "requested_at_utc, started_at_utc, completed_at_utc, "
            "reviewer_actor_type_code, reviewer_reference, review_note_text, "
            "source_component_code, metadata_json, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:review_id, :trace_id, :case_id, 'REQUESTED', NULL, "
            ":reason_code, NULL, NULL, "
            ":now, NULL, NULL, NULL, NULL, NULL, "
            "'HUMAN_REVIEW_SERVICE', NULL, "
            ":now, 'SYSTEM', :now, 'SYSTEM', 0)"
        ),
        {
            "review_id": review_id,
            "trace_id": trace_id,
            "case_id": case_id,
            "reason_code": _REASON_CODE_HUMAN_REVIEW,
            "now": now,
        },
    )


def _insert_conflicting_audit_event(
    session, *, event_id: str, trace_id: str, case_id: str, reviewer_reference: str, occurred_at_utc, now
) -> None:
    """Raw SQL insert of one deliberately conflicting audit_events row,
    under the SAME event_id resume_after_human_review() will compute for
    its HUMAN_REVIEW_COMPLETED event, but with a different occurred_at_utc
    -- the one semantic field this test intentionally disagrees on. Every
    other field matches what the service will generate, so this row
    satisfies every real FK constraint and looks like a genuine,
    previously-recorded event; only occurred_at_utc differs, which is
    exactly what append_audit_event()'s semantic comparison (Step
    23C-2B1) must detect."""
    session.execute(
        sa.text(
            "INSERT INTO audit_events "
            "(event_id, trace_id, case_id, event_type_code, event_category_code, "
            "workflow_status_code, workflow_step_id, source_component_code, "
            "actor_type_code, actor_identifier, result_code, failure_category_code, "
            "reason_code, related_event_id, occurred_at_utc, schema_version, "
            "metadata_json, created_at_utc, created_by) "
            "VALUES (:event_id, :trace_id, :case_id, 'HUMAN_REVIEW_COMPLETED', 'HUMAN', "
            "NULL, NULL, 'HUMAN_REVIEW_SERVICE', "
            "'HUMAN_REVIEWER', :reviewer_reference, 'SUCCESS', NULL, "
            "NULL, NULL, :occurred_at_utc, '1', "
            "NULL, :now, 'SYSTEM')"
        ),
        {
            "event_id": event_id,
            "trace_id": trace_id,
            "case_id": case_id,
            "reviewer_reference": reviewer_reference,
            "occurred_at_utc": occurred_at_utc,
            "now": now,
        },
    )


def _cleanup_synthetic_rows(session, *, trace_id: str, case_id: str, client_id: str) -> None:
    """Deletes synthetic rows in FK-safe reverse dependency order:
    audit_events -> human_reviews -> workflow_runs ->
    prior_authorization_cases -> clients. Stable reference/config rows
    are never touched here. Commits the cleanup itself; a cleanup
    failure is rolled back and re-raised, never concealed."""
    try:
        session.execute(
            sa.text("DELETE FROM audit_events WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        session.execute(
            sa.text("DELETE FROM human_reviews WHERE trace_id = :trace_id"),
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
            {"case_id": case_id},
        )
        session.execute(
            sa.text("DELETE FROM clients WHERE client_id = :client_id"),
            {"client_id": client_id},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def test_close_case_decision_persists_atomically_against_real_sql_server():
    """
    Success-path real SQL Server proof: a CLOSE_CASE Human Review
    decision moves human_reviews, workflow_runs, AND
    prior_authorization_cases together, and appends exactly two audit
    events (HUMAN_REVIEW_COMPLETED, WORKFLOW_COMPLETED), all inside the
    one real SQLAlchemy transaction resume_after_human_review() opens.
    Confirms no WORKFLOW_RESUMED, no new trace_id, no new case.
    """
    session_factory, engine = _make_session_factory()
    setup_session = session_factory()
    now = datetime.now(timezone.utc)

    try:
        _assert_synthetic_ids_absent(
            setup_session,
            client_id=_CLIENT_ID_1,
            case_id=_CASE_ID_1,
            trace_id=_TRACE_ID_1,
            review_id=_REVIEW_ID_1,
        )

        _insert_synthetic_client(setup_session, _CLIENT_ID_1, now)
        _insert_synthetic_case(setup_session, _CASE_ID_1, _CLIENT_ID_1, now)
        _insert_synthetic_workflow_run(setup_session, _TRACE_ID_1, _CASE_ID_1, now)
        _insert_synthetic_human_review(
            setup_session, _REVIEW_ID_1, _TRACE_ID_1, _CASE_ID_1, now
        )
        setup_session.commit()

        workflow_repository = AuditRepository(session_factory=session_factory)
        human_review_repository = HumanReviewRepository(session_factory=session_factory)
        case_repository = CaseRepository(session_factory=session_factory)

        decision_at_utc = datetime.now(timezone.utc)

        result = resume_after_human_review(
            review_id=_REVIEW_ID_1,
            review_outcome_code=HumanReviewOutcome.CLOSE_CASE,
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference=_REVIEWER_REFERENCE_1,
            decision_at_utc=decision_at_utc,
            session_factory=session_factory,
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            close_reason_code=_REASON_CODE_CASE_CLOSE,
        )

        # human_reviews
        assert result.review.review_status_code.value == "COMPLETED"
        assert result.review.review_outcome_code == HumanReviewOutcome.CLOSE_CASE
        assert _utc_naive(result.review.completed_at_utc) == _utc_naive(decision_at_utc)
        assert result.review.reviewer_actor_type_code == "HUMAN_REVIEWER"
        assert result.review.reviewer_reference == _REVIEWER_REFERENCE_1

        # workflow_runs -- SAME trace_id, now terminal
        assert result.workflow_run.trace_id == _TRACE_ID_1
        assert result.workflow_run.workflow_status_code == "COMPLETED"
        assert result.workflow_run.next_action_code == "COMPLETE_WORKFLOW"
        assert result.workflow_run.human_review_required is False
        assert _utc_naive(result.workflow_run.completed_at_utc) == _utc_naive(decision_at_utc)

        # prior_authorization_cases -- read fresh via raw SQL, since
        # CaseRepository only exposes case_status_code directly.
        verify_session = session_factory()
        try:
            case_row = verify_session.execute(
                sa.text(
                    "SELECT case_status_code, closed_at_utc, closed_by, "
                    "close_reason_code FROM prior_authorization_cases "
                    "WHERE case_id = :case_id"
                ),
                {"case_id": _CASE_ID_1},
            ).one()
        finally:
            verify_session.close()

        assert case_row.case_status_code == "CLOSED"
        assert _utc_naive(case_row.closed_at_utc) == _utc_naive(decision_at_utc)
        assert case_row.closed_by == _REVIEWER_REFERENCE_1
        assert case_row.close_reason_code == _REASON_CODE_CASE_CLOSE

        # audit_events -- exactly two, both for this decision
        events = workflow_repository.list_audit_events(_TRACE_ID_1)
        assert len(events) == 2
        event_types = {event.event_type_code for event in events}
        assert event_types == {"HUMAN_REVIEW_COMPLETED", "WORKFLOW_COMPLETED"}
        assert "WORKFLOW_RESUMED" not in event_types
        for event in events:
            assert event.source_component_code == "HUMAN_REVIEW_SERVICE"
            assert _utc_naive(event.occurred_at_utc) == _utc_naive(decision_at_utc)

    finally:
        cleanup_session = session_factory()
        _cleanup_synthetic_rows(
            cleanup_session,
            trace_id=_TRACE_ID_1,
            case_id=_CASE_ID_1,
            client_id=_CLIENT_ID_1,
        )
        cleanup_session.close()
        setup_session.close()
        engine.dispose()


def test_audit_conflict_rolls_back_full_close_case_transaction():
    """
    Atomic-rollback real SQL Server proof: a deliberately conflicting
    audit_events row is pre-seeded under the SAME deterministic event_id
    the service will compute for HUMAN_REVIEW_COMPLETED, differing only
    in occurred_at_utc. Because record_review_outcome()/
    save_workflow_run()/update_case_status() all run (and flush, but do
    not commit) BEFORE append_audit_event() discovers the conflict, this
    proves real SQL Server rolls back everything already flushed in that
    transaction, not just the audit write itself.
    """
    session_factory, engine = _make_session_factory()
    setup_session = session_factory()
    now = datetime.now(timezone.utc)
    decision_at_utc = datetime.now(timezone.utc)
    conflicting_occurred_at_utc = decision_at_utc - timedelta(hours=1)

    conflicting_event_id = deterministic_human_review_event_id(
        _REVIEW_ID_2, "HUMAN_REVIEW_COMPLETED"
    )

    try:
        _assert_synthetic_ids_absent(
            setup_session,
            client_id=_CLIENT_ID_2,
            case_id=_CASE_ID_2,
            trace_id=_TRACE_ID_2,
            review_id=_REVIEW_ID_2,
        )

        _insert_synthetic_client(setup_session, _CLIENT_ID_2, now)
        _insert_synthetic_case(setup_session, _CASE_ID_2, _CLIENT_ID_2, now)
        _insert_synthetic_workflow_run(setup_session, _TRACE_ID_2, _CASE_ID_2, now)
        _insert_synthetic_human_review(
            setup_session, _REVIEW_ID_2, _TRACE_ID_2, _CASE_ID_2, now
        )
        _insert_conflicting_audit_event(
            setup_session,
            event_id=conflicting_event_id,
            trace_id=_TRACE_ID_2,
            case_id=_CASE_ID_2,
            reviewer_reference=_REVIEWER_REFERENCE_2,
            occurred_at_utc=conflicting_occurred_at_utc,
            now=now,
        )
        setup_session.commit()

        workflow_repository = AuditRepository(session_factory=session_factory)
        human_review_repository = HumanReviewRepository(session_factory=session_factory)
        case_repository = CaseRepository(session_factory=session_factory)

        with pytest.raises(AuditEventConflictError):
            resume_after_human_review(
                review_id=_REVIEW_ID_2,
                review_outcome_code=HumanReviewOutcome.CLOSE_CASE,
                reviewer_actor_type_code="HUMAN_REVIEWER",
                reviewer_reference=_REVIEWER_REFERENCE_2,
                decision_at_utc=decision_at_utc,
                session_factory=session_factory,
                workflow_repository=workflow_repository,
                human_review_repository=human_review_repository,
                case_repository=case_repository,
                close_reason_code=_REASON_CODE_CASE_CLOSE,
            )

        # Fresh read session -- everything must be exactly as it was
        # before the failed call, never partially applied.
        verify_session = session_factory()
        try:
            review_row = verify_session.execute(
                sa.text(
                    "SELECT review_status_code, review_outcome_code, "
                    "completed_at_utc FROM human_reviews WHERE review_id = :review_id"
                ),
                {"review_id": _REVIEW_ID_2},
            ).one()
            run_row = verify_session.execute(
                sa.text(
                    "SELECT workflow_status_code, next_action_code, "
                    "human_review_required, completed_at_utc FROM workflow_runs "
                    "WHERE trace_id = :trace_id"
                ),
                {"trace_id": _TRACE_ID_2},
            ).one()
            case_row = verify_session.execute(
                sa.text(
                    "SELECT case_status_code, closed_at_utc, closed_by, "
                    "close_reason_code FROM prior_authorization_cases "
                    "WHERE case_id = :case_id"
                ),
                {"case_id": _CASE_ID_2},
            ).one()
        finally:
            verify_session.close()

        assert review_row.review_status_code == "REQUESTED"
        assert review_row.review_outcome_code is None
        assert review_row.completed_at_utc is None

        assert run_row.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
        assert run_row.next_action_code == "ROUTE_HUMAN_REVIEW"
        assert bool(run_row.human_review_required) is True
        assert run_row.completed_at_utc is None

        assert case_row.case_status_code == "OPEN"
        assert case_row.closed_at_utc is None
        assert case_row.closed_by is None
        assert case_row.close_reason_code is None

        events = workflow_repository.list_audit_events(_TRACE_ID_2)
        assert len(events) == 1
        assert events[0].event_id == conflicting_event_id
        assert events[0].event_type_code == "HUMAN_REVIEW_COMPLETED"
        assert _utc_naive(events[0].occurred_at_utc) == _utc_naive(conflicting_occurred_at_utc)
        assert "WORKFLOW_COMPLETED" not in {e.event_type_code for e in events}

    finally:
        cleanup_session = session_factory()
        _cleanup_synthetic_rows(
            cleanup_session,
            trace_id=_TRACE_ID_2,
            case_id=_CASE_ID_2,
            client_id=_CLIENT_ID_2,
        )
        cleanup_session.close()
        setup_session.close()
        engine.dispose()
