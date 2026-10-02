# File Name: repository.py
# Purpose: Implements the repository for saving/retrieving workflow run snapshots, appending/listing audit events, and race-safely claiming/reverting a workflow run for same-run/same-trace resume.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import AuditEventORM, WorkflowRunORM
from src.models.audit import AuditEvent, WorkflowRunSnapshot


# =====================================================================
# PERSISTENCE ERROR
# Purpose:
# A small, safe exception raised when a repository read/write
# operation fails.
#
# Why:
# Callers need a single, predictable exception type to catch -- one
# that never carries a raw database driver message, which could
# contain a server name, database name, or other configuration detail
# from the underlying connection.
# =====================================================================
class PersistenceError(Exception):
    """Raised when a repository read/write operation fails."""


# =====================================================================
# AUDIT EVENT CONFLICT ERROR
# Purpose:
# Raised when an audit event replay (same deterministic event_id) is
# attempted with different semantics than the already-persisted event.
#
# Why:
# append_audit_event() must distinguish a safe, idempotent replay of
# the exact same logical event (e.g. a retry after a partial-failure
# rollback -- see Step 23C-2A) from a genuine identity collision that
# would silently corrupt the append-only audit trail if allowed through
# as a no-op. No existing exception represents this distinction, so
# this one is introduced -- mirroring the existing
# HumanReviewConflictError / ReferenceDataConflictError naming pattern
# already used elsewhere in this project for the same kind of
# "existing row disagrees with what's being written" condition.
# =====================================================================
class AuditEventConflictError(Exception):
    """Raised when a deterministic audit event_id already exists with
    different semantic content than the event being appended. An
    identical replay is never an error (see append_audit_event()); only
    a genuine mismatch raises this."""


# =====================================================================
# DETERMINISTIC HUMAN REVIEW AUDIT EVENT ID
# Purpose:
# Computes a stable audit_events.event_id for one Human Review decision
# transition, so recording the same logical event twice (e.g. a safe
# retry after a partial-failure rollback) reuses the same event_id
# instead of a fresh random one each time -- required for
# append_audit_event()'s idempotent-replay behavior below.
#
# Why:
# Same category as reference_data.py's deterministic
# workflow_definition_id/workflow_step_id values -- an ordinary
# deterministic technical identifier, not secret configuration. UUID5
# (not raw string concatenation) keeps the result a fixed 36-character
# value regardless of how long review_id/event_type_code are, so a
# future longer event_type_code can never make event_id brittle against
# the column's String(64) limit.
#
# Important Notes:
# - Same review_id + same event_type_code always produce the same
#   event_id.
# - A different review_id or event_type_code always produces a
#   different event_id (UUID5 namespace hashing).
# - No schema change required -- audit_events.event_id is already a
#   plain String(64) primary key with no database-side generation.
# - A caller retrying the SAME logical Human Review transition (e.g.
#   after a partial-failure rollback -- see append_audit_event() below)
#   must reuse the transition's original occurred_at_utc, not generate
#   a fresh "now" for the retry -- occurred_at_utc is part of the
#   event's semantic identity (see _AUDIT_EVENT_SEMANTIC_FIELDS below),
#   not incidental retry metadata.
# =====================================================================
def deterministic_human_review_event_id(review_id: str, event_type_code: str) -> str:
    """Computes the deterministic event_id for one (review_id,
    event_type_code) Human Review audit event transition."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"human-review:{review_id}:{event_type_code}",
        )
    )


# Fields compared to decide whether a replayed audit event (same
# event_id) is an identical, safe replay or a genuine semantic
# conflict.
#
# occurred_at_utc IS included: per docs/database/data_dictionary.md's
# audit_events row for this column ("When the event actually
# occurred"), it is documented as a BUSINESS field, not CONTROL
# metadata -- it is part of what happened, not incidental
# record-keeping. A caller replaying the same logical transition must
# therefore supply the SAME occurred_at_utc it used originally (see the
# note on deterministic_human_review_event_id() above); a different
# occurred_at_utc for the same event_id is treated as a genuine
# conflict, not a safe replay.
#
# created_at_utc/created_by/schema_version are EXCLUDED: these are
# CONTROL/provenance fields (when/by whom the ROW was written, and the
# schema revision), not part of the event's own meaning -- a retry
# naturally writes its row at a different literal "now" even when
# replaying the identical logical event, so comparing them would make
# every legitimate retry look like a conflict.
#
# metadata_json IS included: a different structured payload could
# represent a genuinely different event even with the same
# type/trace/case/occurred_at_utc.
_AUDIT_EVENT_SEMANTIC_FIELDS = (
    "event_type_code",
    "trace_id",
    "case_id",
    "event_category_code",
    "workflow_status_code",
    "workflow_step_id",
    "source_component_code",
    "actor_type_code",
    "actor_identifier",
    "result_code",
    "failure_category_code",
    "reason_code",
    "related_event_id",
    "occurred_at_utc",
    "metadata_json",
)


def _audit_event_semantic_values(event: AuditEvent) -> dict:
    """The comparable semantic field values for one AuditEvent, with
    event_category_code normalized to its plain string value."""
    values = {field: getattr(event, field) for field in _AUDIT_EVENT_SEMANTIC_FIELDS}
    values["event_category_code"] = event.event_category_code.value
    return values


def _round_to_datetime2_precision(value: datetime, precision: int = 3) -> datetime:
    """Rounds a naive UTC datetime to the precision real SQL Server
    actually persists for this project's *_at_utc columns
    (mssql.DATETIME2(precision=3) -- see docs/database/data_dictionary.md
    and every relevant migration), so a Python value that carries more
    precision than the database can store compares equal to what the
    database actually rounds it to.

    Step 23C-2D3A1 verified this rule directly against real SQL Server
    (a table-free `SELECT CAST(... AS DATETIME2(3))`, five cases,
    including an exact half-millisecond tie and a day boundary):
    DATETIME2(3) rounds to the nearest millisecond, ties away from zero
    (NOT banker's/round-half-to-even, and NOT truncation) -- e.g.
    .1585 -> .159, not .158. This function reproduces that exact rule so
    it stays correct even at a tie, not just in the common case.

    Only called on an already timezone-naive, already-UTC value (see
    _normalize_for_comparison() below) -- this function does no
    timezone handling itself.
    """
    unit = 10 ** (6 - precision)  # 1000 microseconds per millisecond
    rounded_microsecond = ((value.microsecond + unit // 2) // unit) * unit
    if rounded_microsecond >= 1_000_000:
        # Carry into the next second (and, via ordinary datetime
        # arithmetic, correctly cascades into minute/hour/day/month/year
        # boundaries exactly as SQL Server itself does -- verified
        # directly for both a second and a day rollover).
        return value.replace(microsecond=0) + timedelta(seconds=1)
    return value.replace(microsecond=rounded_microsecond)


def _normalize_for_comparison(value):
    """Normalizes one value for semantic equality comparison between an
    already-persisted row and a freshly-supplied AuditEvent.

    Two distinct, independent normalizations are applied to a datetime,
    for two distinct reasons:

    1. SQLite (the offline test double used throughout this project's
       tests) does not preserve timezone-awareness through a plain
       DateTime column, so occurred_at_utc read back from the database
       can differ from the in-memory value only in tzinfo, even though
       both represent the exact same UTC instant. Mirrors
       src/db/reference_data.py's _normalize() helper, applied here to
       datetimes specifically; this project's own convention is that
       every *_at_utc value is already UTC (see
       docs/database/data_dictionary.md), so stripping tzinfo after
       converting to UTC is a safe, meaning-preserving normalization,
       not a semantic change.

    2. Real SQL Server's mssql.DATETIME2(precision=3) columns cannot
       preserve Python's microsecond precision -- a freshly-supplied
       occurred_at_utc (e.g. from datetime.now(timezone.utc), which
       carries microsecond precision) is rounded to the nearest
       millisecond the moment it is first persisted (Step 23C-2D3A1's
       confirmed defect: a legitimate replay using the ORIGINAL
       occurred_at_utc value would otherwise false-conflict against the
       already-rounded persisted value). Rounding BOTH sides of the
       comparison to the same DATETIME2(3) precision here -- via
       _round_to_datetime2_precision() -- makes the comparison agree
       with what the database itself considers the same instant. This
       does not weaken occurred_at_utc's status as a semantic field: a
       genuinely different persisted millisecond value still compares
       unequal and still raises AuditEventConflictError (see that
       function's tests) -- only the sub-millisecond precision SQL
       Server itself cannot store is neutralized, not an arbitrary
       tolerance.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return _round_to_datetime2_precision(value)
    return value


# =====================================================================
# AUDIT REPOSITORY
# Purpose:
# Reads and writes workflow run snapshots and audit events using an
# injected SQLAlchemy session factory.
#
# Why:
# The repository never creates its own database engine or session
# factory -- see src/db/engine.py for engine construction. Taking a
# session_factory as a constructor argument keeps this class usable
# with any configured engine (a real SQL Server engine in Task 18B, an
# in-memory SQLite engine in these offline tests) without any change to
# repository code.
#
# Important Notes:
# - By default, every write opens its own session and runs inside its
#   own transaction. On failure, that transaction is explicitly rolled
#   back and a PersistenceError is raised -- the caller never receives
#   a fabricated "success", and raw SQLAlchemy/driver exception text is
#   never included in the raised PersistenceError, since it could
#   contain configuration details.
# - Because a fresh session is opened for every call by default, one
#   failed call never leaves the repository itself unusable for the
#   next call.
# - CALLER-OWNED TRANSACTIONS (Step 23C-2A/2B1): write methods accept
#   an optional session= parameter. When supplied, the method uses it
#   directly, flushes (never commits, never rolls back, never closes
#   it) so a write failure surfaces immediately, and leaves
#   commit/rollback/close entirely to the caller -- this is what lets a
#   Human Review decision, its workflow_runs update, and its required
#   audit event(s) participate in one shared transaction (see
#   src/db/human_review_repository.py). When session is omitted
#   (every existing caller, unchanged), behavior is exactly as before.
# - append_audit_event() never overwrites an existing event_id with
#   different semantics -- see AuditEventConflictError above. An
#   identical replay (same event_id, same semantic fields) is an
#   idempotent no-op, not an error.
# - list_audit_events() always returns events ordered by
#   occurred_at_utc, with event_id as a stable tiebreaker, never
#   relying on unspecified database row order.
# - This repository uses SQLAlchemy ORM operations only -- no SQL
#   string is ever built by concatenating or interpolating a
#   trace_id/case_id/event_type/status value.
# =====================================================================
class AuditRepository:
    """Repository for workflow run snapshots and audit events."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def _resolve_session(self, session: Session | None) -> tuple[Session, bool]:
        """Returns (session, owns_session). A caller-supplied session is
        reused as-is (owns_session=False); otherwise a new one is opened
        from this repository's session_factory (owns_session=True) --
        the caller in that case gets exactly today's existing
        open/commit-or-rollback/close behavior."""
        if session is not None:
            return session, False
        return self._session_factory(), True

    def save_workflow_run(
        self, snapshot: WorkflowRunSnapshot, *, session: Session | None = None
    ) -> None:
        """
        Saves a workflow run snapshot.

        Inserts a new row for a trace_id that has not been saved
        before, or updates the existing row for the same trace_id.
        Never creates a duplicate row for the same trace_id.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                existing = active_session.get(WorkflowRunORM, snapshot.trace_id)

                if existing is None:
                    active_session.add(
                        WorkflowRunORM(
                            trace_id=snapshot.trace_id,
                            case_id=snapshot.case_id,
                            workflow_definition_id=snapshot.workflow_definition_id,
                            workflow_status_code=snapshot.workflow_status_code,
                            next_action_code=snapshot.next_action_code,
                            human_review_required=snapshot.human_review_required,
                            failure_category_code=snapshot.failure_category_code,
                            processing_department_id=snapshot.processing_department_id,
                            processing_location_id=snapshot.processing_location_id,
                            initiated_by_component_code=snapshot.initiated_by_component_code,
                            started_at_utc=snapshot.started_at_utc,
                            completed_at_utc=snapshot.completed_at_utc,
                            schema_version=snapshot.schema_version,
                            metadata_json=snapshot.metadata_json,
                            created_at_utc=snapshot.created_at_utc,
                            created_by=snapshot.created_by,
                            updated_at_utc=snapshot.updated_at_utc,
                            updated_by=snapshot.updated_by,
                            is_deleted=snapshot.is_deleted,
                            deleted_at_utc=snapshot.deleted_at_utc,
                            deleted_by=snapshot.deleted_by,
                            delete_reason_code=snapshot.delete_reason_code,
                            delete_reason_text=snapshot.delete_reason_text,
                        )
                    )
                else:
                    # Run-identity fields are immutable after creation (see
                    # docs/database/data_model.md Section 4 for created_at_utc/
                    # created_by, and Task 22's mutability policy for the
                    # rest): trace_id (the lookup key itself), case_id,
                    # workflow_definition_id, initiated_by_component_code,
                    # started_at_utc, schema_version, created_at_utc, and
                    # created_by are never reassigned on an update -- a run
                    # never changes which case/workflow-definition/component
                    # it belongs to, when it started, or who/when it was
                    # created. Only genuinely mutable, in-progress fields are
                    # updated below.
                    existing.workflow_status_code = snapshot.workflow_status_code
                    existing.next_action_code = snapshot.next_action_code
                    existing.human_review_required = snapshot.human_review_required
                    existing.failure_category_code = snapshot.failure_category_code
                    existing.processing_department_id = snapshot.processing_department_id
                    existing.processing_location_id = snapshot.processing_location_id
                    existing.completed_at_utc = snapshot.completed_at_utc
                    existing.metadata_json = snapshot.metadata_json
                    existing.updated_at_utc = snapshot.updated_at_utc
                    existing.updated_by = snapshot.updated_by
                    existing.is_deleted = snapshot.is_deleted
                    existing.deleted_at_utc = snapshot.deleted_at_utc
                    existing.deleted_by = snapshot.deleted_by
                    existing.delete_reason_code = snapshot.delete_reason_code
                    existing.delete_reason_text = snapshot.delete_reason_text

                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError("Failed to save workflow run.") from error
        finally:
            if owns_session:
                active_session.close()

    def get_workflow_run(
        self, trace_id: str, *, session: Session | None = None
    ) -> WorkflowRunSnapshot | None:
        """
        Retrieves the workflow run snapshot for one trace_id.

        Returns None if no snapshot has been saved for that trace_id --
        never a fabricated result.

        Pass session= to read within a caller-owned shared transaction
        instead of this repository opening its own read-only session.
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            row = active_session.get(WorkflowRunORM, trace_id)
        except SQLAlchemyError as error:
            raise PersistenceError("Failed to retrieve workflow run.") from error
        finally:
            if owns_session:
                active_session.close()

        if row is None:
            return None

        return WorkflowRunSnapshot(
            trace_id=row.trace_id,
            case_id=row.case_id,
            workflow_definition_id=row.workflow_definition_id,
            workflow_status_code=row.workflow_status_code,
            next_action_code=row.next_action_code,
            human_review_required=row.human_review_required,
            failure_category_code=row.failure_category_code,
            processing_department_id=row.processing_department_id,
            processing_location_id=row.processing_location_id,
            initiated_by_component_code=row.initiated_by_component_code,
            started_at_utc=row.started_at_utc,
            completed_at_utc=row.completed_at_utc,
            schema_version=row.schema_version,
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

    def append_audit_event(
        self, event: AuditEvent, *, session: Session | None = None
    ) -> None:
        """
        Appends one audit event.

        If event_id does not yet exist, inserts it. If it already
        exists: an IDENTICAL replay (every field in
        _AUDIT_EVENT_SEMANTIC_FIELDS matches -- see module-level
        constant) is an idempotent no-op, never a duplicate insert and
        never an error -- this is what lets a caller safely retry a
        Human Review decision after a partial-failure rollback without
        losing the audit trail (see Step 23C-2A). A semantic MISMATCH
        raises AuditEventConflictError -- the event is never silently
        overwritten. Comparison happens by reading the existing row
        through the SAME supplied session, never via
        insert-then-catch-PK-violation, since a driver-level integrity
        error can poison the rest of a shared transaction.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                existing = active_session.get(AuditEventORM, event.event_id)

                if existing is not None:
                    new_values = _audit_event_semantic_values(event)
                    mismatches = {
                        field: (getattr(existing, field), new_value)
                        for field, new_value in new_values.items()
                        if _normalize_for_comparison(getattr(existing, field))
                        != _normalize_for_comparison(new_value)
                    }
                    if mismatches:
                        raise AuditEventConflictError(
                            f"Audit event {event.event_id!r} already exists with "
                            f"different semantics: {mismatches}"
                        )
                    # Identical replay -- idempotent success, no duplicate insert.
                    if owns_session:
                        active_session.commit()
                    return

                active_session.add(
                    AuditEventORM(
                        event_id=event.event_id,
                        trace_id=event.trace_id,
                        case_id=event.case_id,
                        event_type_code=event.event_type_code,
                        event_category_code=event.event_category_code.value,
                        workflow_status_code=event.workflow_status_code,
                        workflow_step_id=event.workflow_step_id,
                        source_component_code=event.source_component_code,
                        actor_type_code=event.actor_type_code,
                        actor_identifier=event.actor_identifier,
                        result_code=event.result_code,
                        failure_category_code=event.failure_category_code,
                        reason_code=event.reason_code,
                        related_event_id=event.related_event_id,
                        occurred_at_utc=event.occurred_at_utc,
                        schema_version=event.schema_version,
                        metadata_json=event.metadata_json,
                        created_at_utc=event.created_at_utc,
                        created_by=event.created_by,
                    )
                )
                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
            except AuditEventConflictError:
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError(
                    "Failed to append audit event (it may already exist)."
                ) from error
        finally:
            if owns_session:
                active_session.close()

    # =================================================================
    # ATOMIC RESUME CLAIM / COMPENSATION (Step 24B-2, generalized 24B-4A)
    # Purpose:
    # Race-safely transitions a workflow run's status/next_action via a
    # conditional UPDATE, used for BOTH directions of same-run/
    # same-trace resume:
    # - Claim (default arguments, unchanged since Step 24B-2):
    #   PENDING_RESUME/CONTINUE_PROCESSING -> PROCESSING/NULL.
    # - Compensation (explicit reverse arguments, Step 24B-4A):
    #   PROCESSING/NULL -> PENDING_RESUME/CONTINUE_PROCESSING, used only
    #   when continuation setup fails after a successful claim but
    #   before graph invocation (see
    #   src/workflow/orchestrator.py's _revert_resume_claim()).
    #
    # Why a conditional UPDATE, not read-then-write:
    # Every other write in this repository (save_workflow_run(),
    # append_audit_event()) reads the current row, mutates it in Python,
    # then flushes/commits -- safe for those callers because nothing
    # else races to write the same row at the same moment. A resume
    # claim is different: two concurrent resume requests for the same
    # trace_id could both read PENDING_RESUME before either writes,
    # and both proceed -- silently invoking the graph twice for one
    # trace_id. A single conditional UPDATE ... WHERE <preconditions>
    # closes that window, because SQL Server serializes concurrent
    # UPDATEs to the same row and re-validates the WHERE clause at
    # write time, not merely at an earlier read. The same reasoning
    # applies to compensation: a blind read-then-write revert could
    # overwrite a row that changed for a legitimate reason (e.g. the
    # graph actually started and reached a real disposition) between
    # the claim and the revert attempt -- the conditional UPDATE here
    # refuses instead of overwriting in that case. This is the ONE
    # place in this repository that needs this pattern; every other
    # method's existing read-then-write shape is intentionally left
    # unchanged.
    # =================================================================
    def claim_workflow_run_for_resume(
        self,
        trace_id: str,
        *,
        updated_at_utc: datetime,
        updated_by: str,
        expected_status: str = "PENDING_RESUME",
        expected_next_action: str | None = "CONTINUE_PROCESSING",
        new_status: str = "PROCESSING",
        new_next_action: str | None = None,
        session: Session | None = None,
    ) -> bool:
        """
        Atomically transitions one workflow run's status/next_action.

        Returns True if exactly one row was transitioned (the expected
        status/next_action held at UPDATE time -- new_status/
        new_next_action are now persisted). Returns False if zero rows
        were affected -- the run was not in the expected state (already
        claimed/reverted by a concurrent request, already resumed, or
        never eligible) -- the caller must treat this as a deterministic
        conflict, never retry silently, never invoke the graph, and
        never assume what the row's current state actually is (read it
        fresh if that is needed).

        expected_next_action/new_next_action accept None (compared/set
        as SQL NULL -- SQLAlchemy translates a Column == None comparison
        to IS NULL automatically), so this same method expresses the
        NULL <-> CONTINUE_PROCESSING transition in either direction.

        trace_id is the workflow_runs primary key, so the WHERE clause
        can only ever match zero or one row -- an affected count above
        1 is not reachable through this table's own primary key
        constraint, but is still checked explicitly below rather than
        assumed, so a future schema change could never silently make
        this claim unsafe without this method noticing.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                result = active_session.execute(
                    update(WorkflowRunORM)
                    .where(
                        WorkflowRunORM.trace_id == trace_id,
                        WorkflowRunORM.workflow_status_code == expected_status,
                        WorkflowRunORM.next_action_code == expected_next_action,
                    )
                    .values(
                        workflow_status_code=new_status,
                        next_action_code=new_next_action,
                        updated_at_utc=updated_at_utc,
                        updated_by=updated_by,
                    )
                )
                affected = result.rowcount
                if affected not in (0, 1):
                    raise PersistenceError(
                        "Resume claim/compensation affected an unexpected "
                        f"number of rows ({affected}) for trace_id="
                        f"{trace_id!r}; refusing to treat this as a safe "
                        "transition."
                    )
                claimed = affected == 1
                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
                return claimed
            except PersistenceError:
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError(
                    "Failed to claim/revert workflow run for resume."
                ) from error
        finally:
            if owns_session:
                active_session.close()

    def case_has_workflow_run(self, case_id: str) -> bool:
        """
        Read-only. Returns True if at least one workflow_runs row
        already exists for this case_id.

        Used only by src/workflow/case_intake_service.py (Task 25B) to
        distinguish a genuine duplicate fresh-intake attempt from a
        safe retry after an earlier workflow-start failure -- never
        used by any write path, and never changes any row.
        """
        with self._session_factory() as session:
            try:
                count = session.execute(
                    select(func.count())
                    .select_from(WorkflowRunORM)
                    .where(WorkflowRunORM.case_id == case_id)
                ).scalar_one()
            except SQLAlchemyError as error:
                raise PersistenceError(
                    "Failed to check existing workflow runs for case."
                ) from error
        return count > 0

    def list_audit_events(self, trace_id: str) -> list[AuditEvent]:
        """
        Retrieves every audit event for one trace_id, in deterministic
        chronological order (occurred_at_utc, then event_id as a
        stable tiebreaker).
        """
        with self._session_factory() as session:
            try:
                rows = session.scalars(
                    select(AuditEventORM)
                    .where(AuditEventORM.trace_id == trace_id)
                    .order_by(AuditEventORM.occurred_at_utc, AuditEventORM.event_id)
                ).all()
            except SQLAlchemyError as error:
                raise PersistenceError("Failed to list audit events.") from error

        return [
            AuditEvent(
                event_id=row.event_id,
                trace_id=row.trace_id,
                case_id=row.case_id,
                event_type_code=row.event_type_code,
                event_category_code=row.event_category_code,
                workflow_status_code=row.workflow_status_code,
                workflow_step_id=row.workflow_step_id,
                source_component_code=row.source_component_code,
                actor_type_code=row.actor_type_code,
                actor_identifier=row.actor_identifier,
                result_code=row.result_code,
                failure_category_code=row.failure_category_code,
                reason_code=row.reason_code,
                related_event_id=row.related_event_id,
                occurred_at_utc=row.occurred_at_utc,
                schema_version=row.schema_version,
                metadata_json=row.metadata_json,
                created_at_utc=row.created_at_utc,
                created_by=row.created_by,
            )
            for row in rows
        ]
