# File Name: test_workflow_resume_sql_server_integration.py
# Purpose: Opt-in real SQL Server integration test for the same-run/same-trace resume boundary (src/workflow/resume_service.py, src/workflow/orchestrator.py's continuation core).
# Creation Date: 2026-09-30
# Author: K.Kashiwagi
#
# Module Explanation:
# Same opt-in discipline as tests/test_workflow_orchestrator_integration.py
# and tests/test_human_review_sql_server_integration.py (see those files for
# the established pattern this one reuses exactly): skipped entirely unless
# RUN_SQL_SERVER_INTEGRATION_TESTS=1 is set, requires SQL Server already
# migrated to revision f2fb22e3a41e with the stable Phase 1 reference
# catalog already loaded (97 rows / 14 tables, including WORKFLOW_RESUMED --
# Task 24B-4D). Never calls a real FHIR service or a real AI provider.
#
# What this test proves, and why real SQL Server is needed for it:
# The resume path (validate_and_claim_resume()'s atomic conditional-UPDATE
# claim, and _continue_claimed_workflow_processing()'s atomic disposition
# writes) has already been proven correct against an offline SQLite double
# (tests/test_workflow_continuation.py) and through the HTTP layer
# (tests/test_api_workflow_resume.py). Neither of those proves the SAME
# behavior holds against the real database engine this project actually
# targets: SQL Server's own row-locking and conditional-UPDATE semantics are
# what the atomic claim actually depends on to be race-safe, and its
# DATETIME2(3) column precision is what earlier real-SQL runs (Step
# 23C-2D3A1) found could silently break a naive equality comparison. This
# test is the first proof that the FULL, REAL, end-to-end application path
# -- an initial run reaching HUMAN_REVIEW_REQUIRED, a human reviewer
# deciding CONTINUE_WORKFLOW, and resume_workflow() genuinely continuing
# processing -- persists correctly against that real engine.
#
# How the workflow reaches Human Review (and why this route, not another):
# The initial run uses a FHIR-style client that returns HTTP 500. This is
# the smallest already-implemented route to HUMAN_REVIEW_REQUIRED that needs
# no AI involvement at all: route_after_healthcare_evidence() sends a failed
# FHIR outcome straight to human review, before evidence-consistency,
# completeness, or AI routing ever run (see src/workflow/graph.py). No new
# business rule or failure mode is invented here -- this is the exact route
# already proven offline in
# tests/test_workflow_orchestrator.py::test_healthcare_fhir_failure_safe_fallback_persists_correctly.
#
# TWO separate offline FHIR client instances are used, never one reused for
# both calls: the initial run's client always returns HTTP 500 (so the run
# genuinely cannot retrieve evidence and must route to human review); the
# resume call's client returns the same already-tested synthetic success
# Bundle used elsewhere in this project, representing the external
# dependency becoming available again after a human decided the case should
# continue. Both are backed by httpx.MockTransport -- neither ever makes a
# real network call. The AI provider is a small object that raises
# AssertionError if it is ever invoked at all; both the initial run and the
# resumed run take the AI-not-needed path (AIProcessingRequirements() with
# no requested tasks), so this test proves it never makes a live AI call.
#
# What "same-run/same-trace" means here, concretely:
# trace_id is generated exactly once, by the real orchestrator, the moment
# the initial run starts -- never by this test, never a second time. Every
# later step (the Human Review decision, the resume call, and the rejected
# second resume attempt) is required to use that SAME trace_id and update
# the SAME workflow_runs row already sitting in the database, never create
# a second one. WORKFLOW_STARTED is recorded exactly once, by the initial
# run only -- if resume ever re-emitted it, that would mean resume looked
# like a brand-new run starting, which the whole same-run/same-trace design
# exists to prevent. WORKFLOW_RESUMED is recorded exactly once, only when
# resume_workflow() actually continues processing -- never merely because a
# CONTINUE_WORKFLOW decision was recorded.
#
# Setup rule: raw SQL is used ONLY for the two rows the application itself
# never creates -- a synthetic client and a synthetic
# prior_authorization_cases row (see src/workflow/orchestrator.py's own
# module docstring: it has never created a case row). workflow_runs,
# human_reviews, and every audit_events row are created and updated
# entirely by the real application code under test (run_prior_authorization_
# workflow(), resume_after_human_review(), resume_workflow()) -- never
# raw-seeded, so this test can never quietly depend on assumptions about
# what that code does; it only observes what the code actually does against
# a real database.
#
# Every synthetic row this test writes (directly or through the application)
# is deleted in a finally block, in FK-safe reverse dependency order, on
# pass or fail. Stable reference/configuration rows are never touched here.

import os
from datetime import date, datetime, timezone

import httpx
import pytest
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from src.config.database import load_database_settings
from src.db.case_repository import CaseRepository
from src.db.engine import create_sql_server_engine
from src.db.human_review_repository import HumanReviewRepository
from src.db.reference_data import (
    resolve_step_code_to_workflow_step_id,
    workflow_definition_id as get_workflow_definition_id,
)
from src.db.repository import (
    AuditRepository,
    _round_to_datetime2_precision,
    deterministic_human_review_event_id,
)
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.case import PriorAuthorizationCase
from src.models.human_review import HumanReviewOutcome
from src.models.rules import CompletenessRequirements
from src.workflow.human_review_service import resume_after_human_review
from src.workflow.orchestrator import run_prior_authorization_workflow
from src.workflow.resume_service import ResumeNotEligibleError, resume_workflow

_ENV_FLAG = "RUN_SQL_SERVER_INTEGRATION_TESTS"

pytestmark = pytest.mark.skipif(
    os.environ.get(_ENV_FLAG) != "1",
    reason=(
        f"Opt-in real SQL Server integration test -- set {_ENV_FLAG}=1 to run. "
        "Requires SQL Server already migrated to f2fb22e3a41e with reference "
        "data (including WORKFLOW_RESUMED, Task 24B-4D) already loaded via "
        "src/db/reference_data.py."
    ),
)

# Fixed synthetic IDs for the two rows this test raw-seeds. trace_id and
# review_id are deliberately NOT fixed constants -- both are generated for
# real by the application code under test (uuid4 trace_id in
# src/workflow/orchestrator.py, uuid4 review_id in
# src/workflow/human_review_service.py's request_human_review()) and are
# captured from the running test instead.
_CLIENT_ID = "cli_resume_integration_test_001"
_CASE_ID = "case_resume_integration_test_001"
_MEMBER_ID = "SYN-MEMBER-RESUME-INTEGRATION"
_PROVIDER_ID = "SYN-PROVIDER-RESUME-INTEGRATION"
_REQUESTED_SERVICE_CODE = "SYN-LUMBAR-MRI"
_DIAGNOSIS_CODE = "SYN-LOW-BACK-PAIN"
_REQUESTED_DATE = date(2026, 1, 15)
_REVIEWER_REFERENCE = "SYN-REVIEWER-RESUME-INTEGRATION-001"


def _utc_naive(value: datetime) -> datetime:
    """Normalizes a datetime for equality comparison against a value read
    back from real SQL Server -- identical in spirit and effect to the
    helper of the same name in tests/test_human_review_sql_server_integration.py
    (see that file's docstring for the full two-part reasoning: naive vs.
    aware datetimes, and DATETIME2(3) millisecond rounding)."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return _round_to_datetime2_precision(value)


def _make_session_factory():
    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    return sessionmaker(bind=engine), engine


def _assert_synthetic_ids_absent(session, *, client_id: str, case_id: str) -> None:
    """
    SELECT-only precondition check. Fails loudly, rather than silently
    deleting unknown leftover state, if a stale row from a previous
    interrupted run already exists for these fixed IDs. workflow_runs/
    human_reviews are checked by case_id here (not trace_id/review_id --
    both are generated fresh by the application on every run, so no fixed
    value exists to check before the test starts).
    """
    existing = session.execute(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM clients WHERE client_id = :client_id) AS c1, "
            "(SELECT COUNT(*) FROM prior_authorization_cases WHERE case_id = :case_id) AS c2, "
            "(SELECT COUNT(*) FROM workflow_runs WHERE case_id = :case_id) AS c3, "
            "(SELECT COUNT(*) FROM human_reviews WHERE case_id = :case_id) AS c4"
        ),
        {"client_id": client_id, "case_id": case_id},
    ).one()
    assert existing.c1 == existing.c2 == existing.c3 == existing.c4 == 0, (
        "Stale synthetic resume integration-test rows already exist for "
        f"client_id={client_id!r}/case_id={case_id!r}. Refusing to silently "
        "overwrite or delete unknown leftover state -- investigate and clean "
        "up manually before re-running this test."
    )


def _insert_synthetic_client(session, now) -> None:
    """Raw SQL insert -- clients has no SQLAlchemy ORM class (Wave 1, raw
    DDL only; see src/db/models.py's Foreign Key Policy). The application
    code under test never creates a client row."""
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
            "client_id": _CLIENT_ID,
            "client_code": "RESUME_INTEGRATION_TEST_CLIENT",
            "client_name": "Resume Integration Test Client (synthetic)",
            "now": now,
        },
    )


def _insert_synthetic_case(session, now) -> None:
    """Raw SQL insert -- run_prior_authorization_workflow()/resume_workflow()
    never create a prior_authorization_cases row (confirmed directly in
    src/workflow/orchestrator.py's own module docstring); resume_workflow()'s
    case-identity check requires one to already exist, so it must be
    raw-seeded here, deliberately never through CaseRepository."""
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
            "case_id": _CASE_ID,
            "client_id": _CLIENT_ID,
            "member_id": _MEMBER_ID,
            "provider_id": _PROVIDER_ID,
            "requested_service_code": _REQUESTED_SERVICE_CODE,
            "requested_date": _REQUESTED_DATE,
            "now": now,
        },
    )


def _cleanup_synthetic_rows(session, *, case_id: str, client_id: str) -> None:
    """
    Deletes synthetic rows in FK-safe reverse dependency order:
    audit_events -> human_reviews -> workflow_runs ->
    prior_authorization_cases -> clients. Stable reference/config rows are
    never touched here. Commits the cleanup itself; a cleanup failure is
    rolled back and re-raised, never concealed.

    Deletes audit_events/human_reviews/workflow_runs by case_id, not by
    trace_id. trace_id is generated by the application only after the
    initial run succeeds, so it may still be None if that call persists
    some rows and then raises before returning -- cleanup must not depend
    on having captured it. case_id is safe to use here instead: it is a
    fixed, test-owned synthetic ID, already confirmed absent by
    _assert_synthetic_ids_absent() before this test wrote anything, so
    every row bearing it was created by this test run, and only by this
    test run -- never a broader real-data cleanup.
    """
    try:
        session.execute(
            sa.text("DELETE FROM audit_events WHERE case_id = :case_id"),
            {"case_id": case_id},
        )
        session.execute(
            sa.text("DELETE FROM human_reviews WHERE case_id = :case_id"),
            {"case_id": case_id},
        )
        session.execute(
            sa.text("DELETE FROM workflow_runs WHERE case_id = :case_id"),
            {"case_id": case_id},
        )
        session.execute(
            sa.text("DELETE FROM prior_authorization_cases WHERE case_id = :case_id"),
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


def _valid_fhir_bundle_json():
    """A minimal, fully valid synthetic FHIR-style Bundle whose facts agree
    with this file's seeded case -- the same already-tested synthetic
    pattern used throughout this project (see
    tests/test_workflow_orchestrator_integration.py's make_fhir_client())."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-RESUME-INTEGRATION-001",
                    "status": "active",
                    "intent": "order",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _REQUESTED_SERVICE_CODE,
                                "display": "Lumbar MRI (synthetic)",
                            }
                        ]
                    },
                    "reasonReference": [
                        {"reference": "Condition/SYN-COND-RESUME-INTEGRATION-001"}
                    ],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-RESUME-INTEGRATION-001",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _DIAGNOSIS_CODE,
                                "display": "Low back pain (synthetic)",
                            }
                        ]
                    },
                }
            },
        ],
    }


def make_failing_fhir_client() -> FHIRStyleClient:
    """Offline FHIR-style client that always returns HTTP 500 -- backed by
    httpx.MockTransport, never a real network call. Drives the initial run
    into the already-implemented HUMAN_REVIEW_REQUIRED route
    (reason_code=HUMAN_REVIEW_FHIR_FAILURE, failure_category_code=
    FHIR_HTTP_ERROR). A separate instance from make_success_fhir_client()
    below -- never reused for the resume call."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "synthetic integration failure"})

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def make_success_fhir_client() -> FHIRStyleClient:
    """Offline FHIR-style client that always returns the valid synthetic
    Bundle above -- backed by httpx.MockTransport, never a real network
    call. Represents the external dependency becoming available again
    after the human reviewer's CONTINUE_WORKFLOW decision, so
    resume_workflow() can genuinely continue processing. A separate
    instance from make_failing_fhir_client() above."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_valid_fhir_bundle_json())

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


class _NeverCalledAIProvider:
    """Fails the test loudly if the AI provider is ever invoked. Both the
    initial run and the resumed run request no AI tasks
    (AIProcessingRequirements() with an empty task list), so AI routing
    never reaches this provider on either path -- this class exists only
    to prove that directly, never as a working AI double."""

    def analyze(self, request):
        raise AssertionError(
            "AI provider was called on the AI-not-needed resume integration test path"
        )


def make_case() -> PriorAuthorizationCase:
    """The caller-supplied case used for both the initial run and the
    resume call. Its five durable fields (case_id, member_id, provider_id,
    requested_service_code, requested_date) exactly match the raw-seeded
    prior_authorization_cases row, satisfying resume_workflow()'s
    case-identity check; diagnosis_code matches the success Bundle's
    Condition so evidence-consistency passes on resume."""
    return PriorAuthorizationCase(
        case_id=_CASE_ID,
        member_id=_MEMBER_ID,
        provider_id=_PROVIDER_ID,
        requested_service_code=_REQUESTED_SERVICE_CODE,
        diagnosis_code=_DIAGNOSIS_CODE,
        requested_date=_REQUESTED_DATE,
    )


def test_continue_workflow_resume_persists_atomically_against_real_sql_server():
    """
    The first real SQL Server proof of the full same-run/same-trace resume
    path: an initial run reaches HUMAN_REVIEW_REQUIRED and persists a real
    human_reviews REQUESTED row; a human reviewer decides CONTINUE_WORKFLOW;
    resume_workflow() genuinely continues processing on the SAME workflow_
    runs row and the SAME trace_id, persisting exactly one WORKFLOW_RESUMED
    event and reaching COMPLETED; and an immediate second resume attempt is
    safely rejected, changing nothing. Cleans up every synthetic row it
    wrote (directly or through the application), in FK-safe order, even on
    failure.
    """
    session_factory, engine = _make_session_factory()
    setup_session = session_factory()
    now = datetime.now(timezone.utc)
    trace_id: str | None = None

    try:
        _assert_synthetic_ids_absent(setup_session, client_id=_CLIENT_ID, case_id=_CASE_ID)

        # 0. Verify required stable reference rows exist -- fail with a
        # clear message rather than silently inventing them here.
        step_mapping = resolve_step_code_to_workflow_step_id(setup_session)
        assert step_mapping, (
            "No workflow_definition_steps rows found. Run "
            "`python -m src.db.reference_data` (reviewed and approved) "
            "before running this integration test."
        )

        _insert_synthetic_client(setup_session, now)
        _insert_synthetic_case(setup_session, now)
        setup_session.commit()

        workflow_repository = AuditRepository(session_factory=session_factory)
        human_review_repository = HumanReviewRepository(session_factory=session_factory)
        case_repository = CaseRepository(session_factory=session_factory)

        # ---- 1-3: initial real run reaches HUMAN_REVIEW_REQUIRED ----
        result = run_prior_authorization_workflow(
            case=make_case(),
            completeness_requirements=CompletenessRequirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=_NeverCalledAIProvider(),
            fhir_client=make_failing_fhir_client(),
            repository=workflow_repository,
            workflow_definition_id=get_workflow_definition_id(),
            step_code_to_workflow_step_id=step_mapping,
            human_review_repository=human_review_repository,
            session_factory=session_factory,
        )
        trace_id = result.trace_id

        initial_run = workflow_repository.get_workflow_run(trace_id)
        assert initial_run is not None
        assert initial_run.workflow_status_code == "HUMAN_REVIEW_REQUIRED"
        assert initial_run.next_action_code == "ROUTE_HUMAN_REVIEW"
        assert initial_run.human_review_required is True
        assert initial_run.failure_category_code == "FHIR_HTTP_ERROR"

        pending_review = human_review_repository.get_pending_review_by_trace_id(trace_id)
        assert pending_review is not None
        assert pending_review.review_status_code.value == "REQUESTED"
        assert pending_review.review_outcome_code is None
        assert pending_review.reason_code == "HUMAN_REVIEW_FHIR_FAILURE"
        assert pending_review.case_id == _CASE_ID
        assert pending_review.trace_id == trace_id
        review_id = pending_review.review_id

        initial_events = workflow_repository.list_audit_events(trace_id)
        started_events = [e for e in initial_events if e.event_type_code == "WORKFLOW_STARTED"]
        assert len(started_events) == 1

        # ---- 4: CONTINUE_WORKFLOW decision ----
        decision_at_utc = datetime.now(timezone.utc)
        resume_after_human_review(
            review_id=review_id,
            review_outcome_code=HumanReviewOutcome.CONTINUE_WORKFLOW,
            reviewer_actor_type_code="HUMAN_REVIEWER",
            reviewer_reference=_REVIEWER_REFERENCE,
            decision_at_utc=decision_at_utc,
            session_factory=session_factory,
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
        )

        pending_resume_run = workflow_repository.get_workflow_run(trace_id)
        assert pending_resume_run.workflow_status_code == "PENDING_RESUME"
        assert pending_resume_run.next_action_code == "CONTINUE_PROCESSING"
        assert pending_resume_run.completed_at_utc is None

        # ---- 5-12: resume_workflow() continues the SAME run ----
        resume_result = resume_workflow(
            trace_id=trace_id,
            case=make_case(),
            completeness_requirements=CompletenessRequirements(),
            ai_processing_requirements=AIProcessingRequirements(),
            ai_provider=_NeverCalledAIProvider(),
            fhir_client=make_success_fhir_client(),
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=session_factory,
        )

        assert resume_result.trace_id == trace_id

        with sessionmaker(bind=engine)() as verify_session:
            run_count = verify_session.execute(
                sa.text("SELECT COUNT(*) FROM workflow_runs WHERE trace_id = :trace_id"),
                {"trace_id": trace_id},
            ).scalar_one()
            case_run_count = verify_session.execute(
                sa.text("SELECT COUNT(*) FROM workflow_runs WHERE case_id = :case_id"),
                {"case_id": _CASE_ID},
            ).scalar_one()
        assert run_count == 1
        assert case_run_count == 1

        final_run = workflow_repository.get_workflow_run(trace_id)
        assert final_run.workflow_status_code == "COMPLETED"
        assert final_run.next_action_code == "COMPLETE_WORKFLOW"
        assert final_run.completed_at_utc is not None

        events_after_resume = workflow_repository.list_audit_events(trace_id)
        assert {e.trace_id for e in events_after_resume} == {trace_id}

        resumed_events = [e for e in events_after_resume if e.event_type_code == "WORKFLOW_RESUMED"]
        assert len(resumed_events) == 1
        assert resumed_events[0].event_id == deterministic_human_review_event_id(
            review_id, "WORKFLOW_RESUMED"
        )

        started_events_after_resume = [
            e for e in events_after_resume if e.event_type_code == "WORKFLOW_STARTED"
        ]
        assert len(started_events_after_resume) == 1

        # ---- 13-14: a second resume attempt is rejected and changes nothing ----
        with pytest.raises(ResumeNotEligibleError):
            resume_workflow(
                trace_id=trace_id,
                case=make_case(),
                completeness_requirements=CompletenessRequirements(),
                ai_processing_requirements=AIProcessingRequirements(),
                ai_provider=_NeverCalledAIProvider(),
                fhir_client=make_success_fhir_client(),
                workflow_repository=workflow_repository,
                human_review_repository=human_review_repository,
                case_repository=case_repository,
                session_factory=session_factory,
            )

        run_after_second_attempt = workflow_repository.get_workflow_run(trace_id)
        assert run_after_second_attempt.workflow_status_code == "COMPLETED"
        assert run_after_second_attempt.next_action_code == "COMPLETE_WORKFLOW"
        assert _utc_naive(run_after_second_attempt.completed_at_utc) == _utc_naive(
            final_run.completed_at_utc
        )

        events_after_second_attempt = workflow_repository.list_audit_events(trace_id)
        assert len(events_after_second_attempt) == len(events_after_resume)
        assert {e.event_id for e in events_after_second_attempt} == {
            e.event_id for e in events_after_resume
        }

    finally:
        # ---- 15: cleanup, always, pass or fail ----
        cleanup_session = session_factory()
        _cleanup_synthetic_rows(cleanup_session, case_id=_CASE_ID, client_id=_CLIENT_ID)
        cleanup_session.close()
        setup_session.close()
        engine.dispose()
