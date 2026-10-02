# File Name: human_review_repository.py
# Purpose: Implements the repository for creating human review requests and recording their outcomes.
# Creation Date: 2026-09-21
# Author: K.Kashiwagi
#
# Module Explanation:
# A small, focused repository -- deliberately separate from
# AuditRepository (src/db/repository.py) -- for exactly one
# responsibility: persisting HumanReviewRecord rows. Kept separate
# rather than folded into AuditRepository because human-review
# persistence has its own conflict/idempotency policy (see
# HumanReviewConflictError below) that does not apply to workflow_runs/
# audit_events, and because a focused repository is easier to review
# and test in isolation. This module contains no LangGraph routing
# logic and no business decision-making -- it only reads and writes
# human_reviews rows exactly as instructed by its caller.

from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import HumanReviewORM
from src.models.human_review import HumanReviewRecord, HumanReviewStatus


class PersistenceError(Exception):
    """Raised when a repository read/write operation fails. Mirrors
    src/db/repository.py's exception of the same name and role -- never
    carries raw database driver text, which could contain configuration
    details."""


class HumanReviewConflictError(Exception):
    """
    Raised whenever an attempted write conflicts with a review's
    existing, already-recorded state. Covers three distinct situations
    (Step 23C-2A's locked Phase 1 contracts), never a single narrower
    one:

    1. A review that is already COMPLETED is never silently
       overwritten -- recording the exact same outcome again is an
       idempotent no-op (see record_review_outcome()); only a
       DIFFERENT outcome for an already-completed review raises this.
    2. A review that is CANCELLED is terminal -- any decision attempt
       against it raises this; a cancelled review is never resurrected
       into COMPLETED.
    3. A new review request whose material fields (case_id, reason_code,
       assigned_department_id, assigned_location_id) differ from an
       already-pending review for the same trace_id raises this (see
       create_review_request()) -- an identical duplicate request is
       instead treated as idempotent success, never a second competing
       pending row.
    """


# =====================================================================
# HUMAN REVIEW REPOSITORY
# Purpose:
# Creates human-review requests, retrieves the pending one for a
# workflow run, and records a human reviewer's outcome -- exactly the
# three operations Task 23's pause/resume boundary needs.
#
# Why:
# Kept as small and focused as AuditRepository: no LangGraph state, no
# routing decisions, no AI calls -- persistence only. The injected
# session_factory pattern is identical to AuditRepository's, so this
# repository works against any configured engine (real SQL Server or an
# isolated offline SQLite engine in tests) with no code change.
#
# Important Notes:
# - create_review_request() detects a duplicate pending request for the
#   same trace_id (Step 23C-2A's locked contract): an identical request
#   (same case_id/reason_code/assigned_department_id/
#   assigned_location_id) returns the EXISTING pending review
#   (idempotent success, no second row); a materially different one
#   raises HumanReviewConflictError (never overwritten, never a second
#   competing pending row). review_id colliding with an unrelated,
#   already-persisted review still fails deterministically
#   (PersistenceError).
# - record_review_outcome() is the ONLY place review_outcome_code is
#   ever set. It takes the outcome as a plain HumanReviewOutcome value
#   supplied by the caller -- never derives it from AI output. Callers
#   are responsible for ensuring the value actually came from a human
#   (a synthetic reviewer identity in tests, a real reviewer via the
#   future Streamlit UI) -- this repository has no way to verify that
#   itself, the same way AuditRepository cannot verify who called it.
# - CALLER-OWNED TRANSACTIONS (Step 23C-2A/2B1): write methods accept
#   an optional session= parameter, identical in spirit to
#   AuditRepository's (src/db/repository.py) -- see that module's class
#   docstring for the full behavior. By default (session omitted) every
#   write still opens its own session/transaction and commits or rolls
#   back within that single call, exactly as before.
# =====================================================================
class HumanReviewRepository:
    """Repository for human-review request/outcome persistence."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def _resolve_session(self, session: Session | None) -> tuple[Session, bool]:
        """Returns (session, owns_session) -- identical pattern to
        AuditRepository._resolve_session() (src/db/repository.py)."""
        if session is not None:
            return session, False
        return self._session_factory(), True

    def create_review_request(
        self, review: HumanReviewRecord, *, session: Session | None = None
    ) -> HumanReviewRecord:
        """
        Creates a new pending review request, or reuses an existing one.

        Duplicate-pending contract (Step 23C-2A, locked): if a pending
        (REQUESTED/IN_PROGRESS) review already exists for
        review.trace_id --
        - with the SAME case_id/reason_code/assigned_department_id/
          assigned_location_id: this is idempotent success -- the
          EXISTING review is returned unchanged, no second row is
          created.
        - with any DIFFERENT one of those fields: raises
          HumanReviewConflictError -- never overwritten, never a second
          competing pending row.
        A COMPLETED or CANCELLED review for the same trace_id does NOT
        block creating a genuinely new one (only REQUESTED/IN_PROGRESS
        count as "pending" here).

        Also fails deterministically (PersistenceError) if
        review.review_id already collides with an unrelated,
        already-persisted review -- never a silent overwrite.

        Returns the review that now represents this request (either the
        newly created one, or the pre-existing one it was matched
        against) -- callers must use the returned review's review_id,
        not necessarily the one they passed in.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                existing_by_id = active_session.get(HumanReviewORM, review.review_id)
                if existing_by_id is not None:
                    raise PersistenceError(
                        "Failed to create review request (review_id already exists)."
                    )

                pending = (
                    active_session.query(HumanReviewORM)
                    .filter(HumanReviewORM.trace_id == review.trace_id)
                    .filter(
                        HumanReviewORM.review_status_code.in_(
                            [
                                HumanReviewStatus.REQUESTED.value,
                                HumanReviewStatus.IN_PROGRESS.value,
                            ]
                        )
                    )
                    .order_by(HumanReviewORM.requested_at_utc)
                    .first()
                )
                if pending is not None:
                    same_request = (
                        pending.case_id == review.case_id
                        and pending.reason_code == review.reason_code
                        and pending.assigned_department_id
                        == review.assigned_department_id
                        and pending.assigned_location_id
                        == review.assigned_location_id
                    )
                    if not same_request:
                        raise HumanReviewConflictError(
                            f"A pending human review already exists for "
                            f"trace_id={review.trace_id!r} with different request "
                            "details; refusing to create a second, competing "
                            "pending review."
                        )
                    # Identical duplicate request -- idempotent success.
                    if owns_session:
                        active_session.commit()
                    return _to_record(pending)

                active_session.add(
                    HumanReviewORM(
                        review_id=review.review_id,
                        trace_id=review.trace_id,
                        case_id=review.case_id,
                        review_status_code=review.review_status_code.value,
                        review_outcome_code=(
                            review.review_outcome_code.value
                            if review.review_outcome_code is not None
                            else None
                        ),
                        reason_code=review.reason_code,
                        assigned_department_id=review.assigned_department_id,
                        assigned_location_id=review.assigned_location_id,
                        requested_at_utc=review.requested_at_utc,
                        started_at_utc=review.started_at_utc,
                        completed_at_utc=review.completed_at_utc,
                        reviewer_actor_type_code=review.reviewer_actor_type_code,
                        reviewer_reference=review.reviewer_reference,
                        review_note_text=review.review_note_text,
                        source_component_code=review.source_component_code,
                        metadata_json=review.metadata_json,
                        created_at_utc=review.created_at_utc,
                        created_by=review.created_by,
                        updated_at_utc=review.updated_at_utc,
                        updated_by=review.updated_by,
                        is_deleted=review.is_deleted,
                        deleted_at_utc=review.deleted_at_utc,
                        deleted_by=review.deleted_by,
                        delete_reason_code=review.delete_reason_code,
                        delete_reason_text=review.delete_reason_text,
                    )
                )
                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
                return review
            except (PersistenceError, HumanReviewConflictError):
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError(
                    "Failed to create review request."
                ) from error
        finally:
            if owns_session:
                active_session.close()

    def get_pending_review_by_trace_id(self, trace_id: str) -> HumanReviewRecord | None:
        """
        Retrieves the pending (REQUESTED or IN_PROGRESS) review for one
        trace_id, or None if no pending review exists.

        Never returns an already-COMPLETED or CANCELLED review -- those
        are no longer "pending".
        """
        with self._session_factory() as session:
            try:
                rows = (
                    session.query(HumanReviewORM)
                    .filter(HumanReviewORM.trace_id == trace_id)
                    .filter(
                        HumanReviewORM.review_status_code.in_(
                            [
                                HumanReviewStatus.REQUESTED.value,
                                HumanReviewStatus.IN_PROGRESS.value,
                            ]
                        )
                    )
                    .order_by(HumanReviewORM.requested_at_utc)
                    .all()
                )
            except SQLAlchemyError as error:
                raise PersistenceError(
                    "Failed to retrieve pending review."
                ) from error

        if not rows:
            return None

        return _to_record(rows[0])

    def get_review_by_id(
        self, review_id: str, *, session: Session | None = None
    ) -> HumanReviewRecord | None:
        """Retrieves one review by its review_id, regardless of status.

        Pass session= to read within a caller-owned shared transaction
        (e.g. as part of an atomic decision transition -- see
        src/workflow/human_review_service.py) instead of this
        repository opening its own read-only session.
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            row = active_session.get(HumanReviewORM, review_id)
        except SQLAlchemyError as error:
            raise PersistenceError("Failed to retrieve review.") from error
        finally:
            if owns_session:
                active_session.close()

        if row is None:
            return None
        return _to_record(row)

    def get_completed_review_by_trace_id(self, trace_id: str) -> HumanReviewRecord | None:
        """
        Retrieves the most recently completed review for one trace_id,
        or None if none has been completed yet.

        Used by the resume boundary's idempotent-repeat check
        (src/workflow/human_review_service.py) -- a repeated resume
        request needs to compare its requested outcome against what was
        already recorded, without this repository exposing its session
        internals to callers.
        """
        with self._session_factory() as session:
            try:
                row = (
                    session.query(HumanReviewORM)
                    .filter(HumanReviewORM.trace_id == trace_id)
                    .filter(
                        HumanReviewORM.review_status_code
                        == HumanReviewStatus.COMPLETED.value
                    )
                    .order_by(HumanReviewORM.completed_at_utc.desc())
                    .first()
                )
            except SQLAlchemyError as error:
                raise PersistenceError(
                    "Failed to retrieve completed review."
                ) from error

        if row is None:
            return None
        return _to_record(row)

    def record_review_outcome(
        self,
        *,
        review_id: str,
        review_outcome_code,
        completed_at_utc,
        reviewer_actor_type_code: str,
        reviewer_reference: str,
        updated_by: str,
        review_note_text: str | None = None,
        started_at_utc=None,
        session: Session | None = None,
    ) -> None:
        """
        Records a human reviewer's outcome for one review.

        Idempotency/conflict policy (mirrors src/db/reference_data.py's
        insert-if-missing/verify-or-fail pattern, applied here to a
        single row's final state instead of a whole reference table):
        - If the review is still pending (REQUESTED/IN_PROGRESS), this
          records the outcome and marks it COMPLETED.
        - If the review is already COMPLETED with the EXACT SAME
          outcome code, this is a no-op (idempotent) -- a repeated
          resume request never creates a duplicate decision.
        - If the review is already COMPLETED with a DIFFERENT outcome,
          this raises HumanReviewConflictError and changes nothing --
          a recorded human decision is never silently overwritten.
        - If the review is CANCELLED, this raises
          HumanReviewConflictError and changes nothing -- a cancelled
          review is terminal and is never resurrected into COMPLETED,
          regardless of what outcome is supplied.
        - If no review exists with that review_id, raises
          PersistenceError.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                existing = active_session.get(HumanReviewORM, review_id)
                if existing is None:
                    raise PersistenceError(
                        "Failed to record review outcome (review_id not found)."
                    )

                outcome_value = (
                    review_outcome_code.value
                    if hasattr(review_outcome_code, "value")
                    else review_outcome_code
                )

                if existing.review_status_code == HumanReviewStatus.CANCELLED.value:
                    raise HumanReviewConflictError(
                        f"Review {review_id} is CANCELLED; a cancelled review can "
                        "never be completed or resurrected."
                    )

                if existing.review_status_code == HumanReviewStatus.COMPLETED.value:
                    if existing.review_outcome_code == outcome_value:
                        # Idempotent repeat -- same outcome already recorded.
                        if owns_session:
                            active_session.commit()
                        return
                    raise HumanReviewConflictError(
                        f"Review {review_id} is already COMPLETED with outcome "
                        f"{existing.review_outcome_code!r}; cannot record a "
                        f"different outcome {outcome_value!r}."
                    )

                existing.review_status_code = HumanReviewStatus.COMPLETED.value
                existing.review_outcome_code = outcome_value
                existing.completed_at_utc = completed_at_utc
                existing.reviewer_actor_type_code = reviewer_actor_type_code
                existing.reviewer_reference = reviewer_reference
                existing.review_note_text = review_note_text
                if started_at_utc is not None:
                    existing.started_at_utc = started_at_utc
                existing.updated_at_utc = completed_at_utc
                existing.updated_by = updated_by

                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
            except (PersistenceError, HumanReviewConflictError):
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError(
                    "Failed to record review outcome."
                ) from error
        finally:
            if owns_session:
                active_session.close()


def _to_record(row: HumanReviewORM) -> HumanReviewRecord:
    """Converts one HumanReviewORM row into the canonical HumanReviewRecord."""
    return HumanReviewRecord(
        review_id=row.review_id,
        trace_id=row.trace_id,
        case_id=row.case_id,
        review_status_code=HumanReviewStatus(row.review_status_code),
        review_outcome_code=(
            None if row.review_outcome_code is None else row.review_outcome_code
        ),
        reason_code=row.reason_code,
        assigned_department_id=row.assigned_department_id,
        assigned_location_id=row.assigned_location_id,
        requested_at_utc=row.requested_at_utc,
        started_at_utc=row.started_at_utc,
        completed_at_utc=row.completed_at_utc,
        reviewer_actor_type_code=row.reviewer_actor_type_code,
        reviewer_reference=row.reviewer_reference,
        review_note_text=row.review_note_text,
        source_component_code=row.source_component_code,
        metadata_json=row.metadata_json,
        created_at_utc=row.created_at_utc,
        created_by=row.created_by,
        updated_at_utc=row.updated_at_utc,
        updated_by=row.updated_by,
        is_deleted=row.is_deleted,
        deleted_at_utc=row.deleted_at_utc,
        deleted_by=row.deleted_by,
        delete_reason_code=row.delete_reason_code,
        delete_reason_text=row.delete_reason_text,
    )
