# File Name: human_review_service.py
# Purpose: Implements Human-in-the-Loop review request creation and the atomic, safe, same-trace_id application-level decision-transition boundary.
# Creation Date: 2026-09-21
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the one place Task 23's pause/decision logic lives. It
# contains NO LangGraph invocation and NO routing decisions --
# src/workflow/graph.py is completely unmodified by this task. There is
# no LangGraph checkpointer/interrupt mechanism in this project
# (confirmed directly: src/workflow/graph.py's graph.compile() takes no
# checkpointer argument), so a human-review decision transition here is
# an explicit application-level state transition, not a graph-native
# continuation: it never re-invokes the graph, never re-runs the
# FHIR/AI steps that already ran, and never changes their
# already-persisted results. It only records the human decision and
# moves the SAME workflow_runs row (and, where the outcome requires it,
# the SAME prior_authorization_cases row) to their next state.
#
# ATOMICITY (Step 23C-2B1/2B2):
# resume_after_human_review() opens exactly ONE SQLAlchemy Session and
# passes it (session=) into every repository call it makes --
# human_review_repository.record_review_outcome(), the case-status
# update where applicable, and every append_audit_event() call. All of
# it commits together, or none of it does. This closes the
# previously-confirmed gap where Human Review state and workflow state
# could be committed while a required audit event was silently lost
# (Step 23C-1's finding) -- see docs no longer apply here; the fix is
# in this file and in the repositories it calls (session= support,
# Step 23C-2B1).
#
# REPLAY (Step 23C-2B2, corrected design):
# This function does NOT special-case "the review/run is already in
# its target state, therefore return success without touching
# anything" -- Step 23C-2A/2B2 explicitly rejected that shortcut,
# because it is exactly what caused the audit-loss gap (a retry after
# a partial failure would see "already COMPLETED" and skip re-emitting
# the missing audit event forever). Instead, every call always attempts
# the full write sequence; each repository call's own idempotency
# (Step 23C-2B1) absorbs a genuine replay transparently -- an identical
# replay (same review_id, same outcome, same decision_at_utc, same
# resulting values) commits with no net change; a replay that differs
# in any way that matters raises the specific conflict exception for
# whichever write disagreed (HumanReviewConflictError /
# AuditEventConflictError), and the WHOLE transaction rolls back.
#
# DESIGN NOTE -- why every review outcome completes the workflow run,
# except CONTINUE_WORKFLOW:
# workflow_statuses.COMPLETED's own canonical description (see
# docs/database/reference_data.md Section 4) is: "This workflow run
# completed successfully; use next_action_code for the business next
# step." REQUEST_MORE_INFORMATION/ESCALATE/CLOSE_CASE all have
# human_review_outcomes.returns_to_workflow = 0 (docs/database/
# reference_data.md Section 18) -- the case does not return to
# automated workflow processing for any of them, so this run correctly
# reaches its terminal disposition. CONTINUE_WORKFLOW is the sole
# returns_to_workflow = 1 outcome: this run transitions to the
# nonterminal PENDING_RESUME status instead (Step 23B's approved
# canonical addition) -- completed_at_utc stays NULL, WORKFLOW_COMPLETED
# is never emitted, and WORKFLOW_RESUMED is never emitted by this task.
# Task 24 owns the actual transition out of PENDING_RESUME and owns
# WORKFLOW_RESUMED entirely -- this module never produces either.

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.case_repository import CaseRepository
from src.db.human_review_repository import (
    HumanReviewConflictError,
    HumanReviewRepository,
    PersistenceError as HumanReviewPersistenceError,
)
from src.db.repository import AuditRepository, deterministic_human_review_event_id
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot
from src.models.human_review import HumanReviewOutcome, HumanReviewRecord, HumanReviewStatus

_SCHEMA_VERSION = "1"


class ResumeError(Exception):
    """Raised when a decision-transition request is invalid -- unknown
    review_id, unknown trace_id/workflow run, or (see
    InvalidCloseReasonError below) invalid CLOSE_CASE input. Never
    silently ignored; the caller always sees why it failed."""


class InvalidCloseReasonError(Exception):
    """Raised when a CLOSE_CASE decision is attempted without a valid,
    approved close_reason_code, or without non-empty close_reason_text
    when close_reason_code is CASE_CLOSE_OTHER. No default reason is
    ever substituted -- see docs/security.md's Missing Information
    Safety Contract's deny-by-default principle, applied here to case
    closure input."""


@dataclass
class HumanReviewRequestResult:
    """The review row created (or reused -- see
    HumanReviewRepository.create_review_request()) when a run is routed
    to human review."""

    review: HumanReviewRecord


@dataclass
class ResumeResult:
    """The outcome of one resume_after_human_review() call -- the same
    result whether this call performed a fresh transition or safely
    replayed an already-applied one (see module docstring)."""

    workflow_run: WorkflowRunSnapshot
    review: HumanReviewRecord
    audit_events: list[AuditEvent]


# =====================================================================
# REQUEST HUMAN REVIEW
# Purpose:
# Creates (or, per the duplicate-pending contract, reuses) the durable
# human_reviews row for a run that just reached HUMAN_REVIEW_REQUIRED.
# Called by src/workflow/orchestrator.py immediately after it persists
# the workflow_runs/audit_events state for that outcome -- never
# instead of it. Wired into the orchestrator as of Step 23C-6A, for the
# three genuine Human Review routes (FHIR failure, evidence mismatch, AI
# failure) -- never for the Stage 1 missing-information disposition.
#
# session= (Step 23C-6A): added so the orchestrator can include this
# call in the SAME shared transaction as the workflow_runs/audit_events
# writes for a HUMAN_REVIEW_REQUIRED disposition -- required to
# guarantee the workflow is never left claiming HUMAN_REVIEW_REQUIRED
# with no durable human_reviews row behind it (the task's explicit
# "fail safely" requirement), mirroring exactly the caller-owned-session
# pattern already proven for the Stage 1 disposition
# (src/workflow/orchestrator.py's _persist_stage1_disposition(), Step
# 23C-5C) and for resume_after_human_review() (Step 23C-2B1/2B2) above.
# The underlying repository call already supported session= before this
# change -- only this thin wrapper needed the passthrough added.
# =====================================================================
def request_human_review(
    *,
    trace_id: str,
    case_id: str,
    reason_code: str,
    repository: HumanReviewRepository,
    assigned_department_id: str | None = None,
    assigned_location_id: str | None = None,
    source_component_code: str = "HUMAN_REVIEW_SERVICE",
    created_by: str = "SYSTEM",
    session: Session | None = None,
) -> HumanReviewRequestResult:
    """
    Requests a pending human review for one workflow run. review_id is
    a fresh application-generated UUID4 -- but see
    HumanReviewRepository.create_review_request(): if an identical
    pending request already exists for this trace_id, the EXISTING
    review is returned instead (idempotent success, no second row);
    only the returned HumanReviewRequestResult.review.review_id is
    guaranteed to be correct, not necessarily the one generated here.

    Pass session= to participate in a caller-owned shared transaction
    instead of this call's repository opening/committing its own (see
    module docstring above).
    """
    now = datetime.now(timezone.utc)
    review = HumanReviewRecord(
        review_id=str(uuid.uuid4()),
        trace_id=trace_id,
        case_id=case_id,
        review_status_code=HumanReviewStatus.REQUESTED,
        reason_code=reason_code,
        assigned_department_id=assigned_department_id,
        assigned_location_id=assigned_location_id,
        requested_at_utc=now,
        source_component_code=source_component_code,
        created_at_utc=now,
        created_by=created_by,
        updated_at_utc=now,
        updated_by=created_by,
    )
    persisted_review = repository.create_review_request(review, session=session)
    return HumanReviewRequestResult(review=persisted_review)


# =====================================================================
# CLOSE_CASE INPUT VALIDATION
# Purpose:
# Enforces the approved CASE_CLOSE_* contract (Step 23C-2A/2B2) before
# any database interaction -- deterministic-first: validate, then act.
# =====================================================================
_APPROVED_CLOSE_REASON_CODES = frozenset(
    {
        "CASE_CLOSE_COMPLETED",
        "CASE_CLOSE_REQUEST_WITHDRAWN",
        "CASE_CLOSE_DUPLICATE",
        "CASE_CLOSE_SUPERSEDED",
        "CASE_CLOSE_ADMINISTRATIVE",
        "CASE_CLOSE_OTHER",
    }
)


def _validate_close_case_input(
    close_reason_code: str | None, close_reason_text: str | None
) -> None:
    """Raises InvalidCloseReasonError if close_reason_code is missing,
    unapproved, or (for CASE_CLOSE_OTHER specifically) unaccompanied by
    non-empty explanatory text. No default is ever substituted."""
    if close_reason_code is None:
        raise InvalidCloseReasonError(
            "close_reason_code is required to record a CLOSE_CASE outcome."
        )
    if close_reason_code not in _APPROVED_CLOSE_REASON_CODES:
        raise InvalidCloseReasonError(
            f"close_reason_code {close_reason_code!r} is not an approved "
            "CASE_CLOSE_* reason."
        )
    if close_reason_code == "CASE_CLOSE_OTHER" and not (
        close_reason_text and close_reason_text.strip()
    ):
        raise InvalidCloseReasonError(
            "close_reason_text is required and must be non-empty when "
            "close_reason_code is CASE_CLOSE_OTHER."
        )


# =====================================================================
# OUTCOME -> STATE TRANSITION TABLE
# Purpose:
# The single authoritative mapping from each approved HumanReviewOutcome
# to its Step 23C-2A-locked workflow_runs/case state -- derived
# directly from the approved contracts, nothing invented here.
# =====================================================================
@dataclass(frozen=True)
class _OutcomeTransition:
    workflow_status_code: str
    next_action_code: str
    workflow_terminal: bool  # False only for CONTINUE_WORKFLOW -> PENDING_RESUME
    emit_workflow_completed: bool
    case_status_code: str | None  # None = this outcome does not touch case state


_OUTCOME_TRANSITIONS: dict[HumanReviewOutcome, _OutcomeTransition] = {
    HumanReviewOutcome.CONTINUE_WORKFLOW: _OutcomeTransition(
        workflow_status_code="PENDING_RESUME",
        next_action_code="CONTINUE_PROCESSING",
        workflow_terminal=False,
        emit_workflow_completed=False,
        case_status_code=None,
    ),
    HumanReviewOutcome.REQUEST_MORE_INFORMATION: _OutcomeTransition(
        workflow_status_code="COMPLETED",
        next_action_code="REQUEST_MISSING_INFORMATION",
        workflow_terminal=True,
        emit_workflow_completed=True,
        case_status_code="PENDING_INFORMATION",
    ),
    HumanReviewOutcome.ESCALATE: _OutcomeTransition(
        workflow_status_code="COMPLETED",
        next_action_code="ROUTE_HUMAN_REVIEW",
        workflow_terminal=True,
        emit_workflow_completed=True,
        case_status_code="HUMAN_REVIEW_REQUIRED",
    ),
    HumanReviewOutcome.CLOSE_CASE: _OutcomeTransition(
        workflow_status_code="COMPLETED",
        next_action_code="COMPLETE_WORKFLOW",
        workflow_terminal=True,
        emit_workflow_completed=True,
        case_status_code="CLOSED",
    ),
}


# =====================================================================
# RESUME AFTER HUMAN REVIEW
# Purpose:
# Atomically records a human reviewer's decision and moves the SAME
# workflow_runs row (and, where required, the SAME prior_authorization_
# cases row) to the outcome's approved next state, in one shared
# transaction with the required audit event(s).
#
# Important Notes:
# - review_id identifies the specific review being decided -- this
#   function does not look it up by trace_id, because a trace_id-based
#   pending-only lookup cannot support replaying an already-decided
#   review (see module docstring's REPLAY note). Callers obtain
#   review_id from request_human_review() or from their own prior
#   lookup.
# - decision_at_utc is supplied by the caller, not generated internally
#   (Step 23C-2B2 Section 11): it is reused as human_reviews.
#   completed_at_utc, workflow_runs.completed_at_utc (when terminal),
#   prior_authorization_cases.closed_at_utc (for CLOSE_CASE), and every
#   audit event's occurred_at_utc -- one logical decision, one logical
#   timestamp. A caller replaying the same logical decision must supply
#   the SAME decision_at_utc it used originally, or the audit layer's
#   occurred_at_utc semantic check (Step 23C-2B1) will treat the retry
#   as a genuine conflict, not a safe replay -- this is deliberate, not
#   a limitation to work around.
# - Never generates a new trace_id, never creates a second workflow_runs
#   row -- resumes the existing row via workflow_repository.
#   save_workflow_run(), whose own mutability policy (src/db/
#   repository.py, Task 22) already refuses to change identity fields.
# - The review_outcome_code driving this transition is a caller-supplied
#   HumanReviewOutcome value -- this function never reads or derives it
#   from any AI output.
# =====================================================================
def resume_after_human_review(
    *,
    review_id: str,
    review_outcome_code: HumanReviewOutcome,
    reviewer_actor_type_code: str,
    reviewer_reference: str,
    decision_at_utc: datetime,
    session_factory: Callable[[], Session],
    workflow_repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    case_repository: CaseRepository,
    review_note_text: str | None = None,
    close_reason_code: str | None = None,
    close_reason_text: str | None = None,
    updated_by: str = "SYSTEM",
) -> ResumeResult:
    """
    Records review_outcome_code as review_id's decision and atomically
    transitions the same workflow run (and case, where the outcome
    requires it) to its approved next state, per _OUTCOME_TRANSITIONS.

    Raises ResumeError for an unknown review_id or workflow run, and
    InvalidCloseReasonError for invalid CLOSE_CASE input (checked before
    any database interaction). Raises HumanReviewConflictError or
    AuditEventConflictError -- propagated directly, not wrapped -- if
    any individual write within the transaction genuinely conflicts
    with already-persisted state; the entire transaction rolls back in
    every failure case.
    """
    if review_outcome_code == HumanReviewOutcome.CLOSE_CASE:
        _validate_close_case_input(close_reason_code, close_reason_text)

    transition = _OUTCOME_TRANSITIONS[review_outcome_code]

    session = session_factory()
    try:
        review = human_review_repository.get_review_by_id(review_id, session=session)
        if review is None:
            raise ResumeError(f"No human review found for review_id={review_id!r}.")

        workflow_run = workflow_repository.get_workflow_run(
            review.trace_id, session=session
        )
        if workflow_run is None:
            raise ResumeError(
                f"No workflow run found for trace_id={review.trace_id!r}."
            )

        human_review_repository.record_review_outcome(
            review_id=review_id,
            review_outcome_code=review_outcome_code,
            completed_at_utc=decision_at_utc,
            reviewer_actor_type_code=reviewer_actor_type_code,
            reviewer_reference=reviewer_reference,
            review_note_text=review_note_text,
            updated_by=updated_by,
            session=session,
        )

        updated_run = WorkflowRunSnapshot(
            trace_id=workflow_run.trace_id,
            case_id=workflow_run.case_id,
            workflow_definition_id=workflow_run.workflow_definition_id,
            workflow_status_code=transition.workflow_status_code,
            next_action_code=transition.next_action_code,
            human_review_required=False,
            failure_category_code=workflow_run.failure_category_code,
            processing_department_id=workflow_run.processing_department_id,
            processing_location_id=workflow_run.processing_location_id,
            initiated_by_component_code=workflow_run.initiated_by_component_code,
            started_at_utc=workflow_run.started_at_utc,
            completed_at_utc=(
                decision_at_utc if transition.workflow_terminal else None
            ),
            schema_version=workflow_run.schema_version,
            metadata_json=workflow_run.metadata_json,
            created_at_utc=workflow_run.created_at_utc,
            created_by=workflow_run.created_by,
            updated_at_utc=decision_at_utc,
            updated_by=updated_by,
        )
        workflow_repository.save_workflow_run(updated_run, session=session)

        is_close_case = review_outcome_code == HumanReviewOutcome.CLOSE_CASE
        if transition.case_status_code is not None:
            case_repository.update_case_status(
                case_id=review.case_id,
                case_status_code=transition.case_status_code,
                updated_by=updated_by,
                updated_at_utc=decision_at_utc,
                closed_at_utc=decision_at_utc if is_close_case else None,
                closed_by=reviewer_reference if is_close_case else None,
                close_reason_code=close_reason_code if is_close_case else None,
                close_reason_text=close_reason_text if is_close_case else None,
                session=session,
            )

        events: list[AuditEvent] = []

        human_review_completed_event = AuditEvent(
            event_id=deterministic_human_review_event_id(
                review_id, "HUMAN_REVIEW_COMPLETED"
            ),
            trace_id=review.trace_id,
            case_id=review.case_id,
            event_type_code="HUMAN_REVIEW_COMPLETED",
            event_category_code=AuditEventCategory.HUMAN,
            source_component_code="HUMAN_REVIEW_SERVICE",
            actor_type_code=reviewer_actor_type_code,
            actor_identifier=reviewer_reference,
            result_code="SUCCESS",
            occurred_at_utc=decision_at_utc,
            schema_version=_SCHEMA_VERSION,
            created_at_utc=decision_at_utc,
            created_by=updated_by,
        )
        workflow_repository.append_audit_event(
            human_review_completed_event, session=session
        )
        events.append(human_review_completed_event)

        # CONTINUE_WORKFLOW never reaches here with emit_workflow_completed
        # True -- WORKFLOW_COMPLETED (and WORKFLOW_RESUMED, which this
        # module never emits at all) must not be emitted for it; this run
        # is not terminal yet, Task 24 owns what happens next.
        if transition.emit_workflow_completed:
            workflow_completed_event = AuditEvent(
                event_id=deterministic_human_review_event_id(
                    review_id, "WORKFLOW_COMPLETED"
                ),
                trace_id=review.trace_id,
                case_id=review.case_id,
                event_type_code="WORKFLOW_COMPLETED",
                event_category_code=AuditEventCategory.WORKFLOW,
                workflow_status_code="COMPLETED",
                source_component_code="HUMAN_REVIEW_SERVICE",
                actor_type_code="SYSTEM",
                result_code="SUCCESS",
                occurred_at_utc=decision_at_utc,
                schema_version=_SCHEMA_VERSION,
                created_at_utc=decision_at_utc,
                created_by=updated_by,
            )
            workflow_repository.append_audit_event(
                workflow_completed_event, session=session
            )
            events.append(workflow_completed_event)

        session.commit()

        completed_review = human_review_repository.get_review_by_id(
            review_id, session=session
        )

        return ResumeResult(
            workflow_run=updated_run,
            review=completed_review,
            audit_events=events,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "ResumeError",
    "InvalidCloseReasonError",
    "HumanReviewRequestResult",
    "ResumeResult",
    "request_human_review",
    "resume_after_human_review",
]
