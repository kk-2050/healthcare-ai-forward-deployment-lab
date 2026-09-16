# File Name: repository.py
# Purpose: Implements the repository for saving/retrieving workflow run snapshots and appending/listing audit events.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from collections.abc import Callable

from sqlalchemy import select
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
# - Every write opens its own session and runs inside its own
#   transaction. On failure, that transaction is explicitly rolled
#   back and a PersistenceError is raised -- the caller never receives
#   a fabricated "success", and raw SQLAlchemy/driver exception text is
#   never included in the raised PersistenceError, since it could
#   contain configuration details.
# - Because a fresh session is opened for every call, one failed call
#   never leaves the repository itself unusable for the next call.
# - append_audit_event() never overwrites an existing event_id; a
#   duplicate is a deterministic failure (PersistenceError), not a
#   silent no-op or overwrite.
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

    def save_workflow_run(self, snapshot: WorkflowRunSnapshot) -> None:
        """
        Saves a workflow run snapshot.

        Inserts a new row for a trace_id that has not been saved
        before, or updates the existing row for the same trace_id.
        Never creates a duplicate row for the same trace_id.
        """
        with self._session_factory() as session:
            try:
                existing = session.get(WorkflowRunORM, snapshot.trace_id)

                if existing is None:
                    session.add(
                        WorkflowRunORM(
                            trace_id=snapshot.trace_id,
                            case_id=snapshot.case_id,
                            workflow_status=snapshot.workflow_status,
                            human_review_required=snapshot.human_review_required,
                            failure_category=snapshot.failure_category,
                            created_at_utc=snapshot.created_at_utc,
                            updated_at_utc=snapshot.updated_at_utc,
                        )
                    )
                else:
                    existing.case_id = snapshot.case_id
                    existing.workflow_status = snapshot.workflow_status
                    existing.human_review_required = snapshot.human_review_required
                    existing.failure_category = snapshot.failure_category
                    existing.updated_at_utc = snapshot.updated_at_utc

                session.commit()
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceError("Failed to save workflow run.") from error

    def get_workflow_run(self, trace_id: str) -> WorkflowRunSnapshot | None:
        """
        Retrieves the workflow run snapshot for one trace_id.

        Returns None if no snapshot has been saved for that trace_id --
        never a fabricated result.
        """
        with self._session_factory() as session:
            try:
                row = session.get(WorkflowRunORM, trace_id)
            except SQLAlchemyError as error:
                raise PersistenceError("Failed to retrieve workflow run.") from error

        if row is None:
            return None

        return WorkflowRunSnapshot(
            trace_id=row.trace_id,
            case_id=row.case_id,
            workflow_status=row.workflow_status,
            human_review_required=row.human_review_required,
            failure_category=row.failure_category,
            created_at_utc=row.created_at_utc,
            updated_at_utc=row.updated_at_utc,
        )

    def append_audit_event(self, event: AuditEvent) -> None:
        """
        Appends one audit event.

        Fails deterministically (PersistenceError) if event_id already
        exists -- audit events are append-only and are never silently
        overwritten.
        """
        with self._session_factory() as session:
            try:
                session.add(
                    AuditEventORM(
                        event_id=event.event_id,
                        trace_id=event.trace_id,
                        case_id=event.case_id,
                        event_type=event.event_type,
                        event_category=event.event_category.value,
                        workflow_status=event.workflow_status,
                        processing_step=event.processing_step,
                        failure_category=event.failure_category,
                        occurred_at_utc=event.occurred_at_utc,
                    )
                )
                session.commit()
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceError(
                    "Failed to append audit event (it may already exist)."
                ) from error

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
                event_type=row.event_type,
                event_category=row.event_category,
                workflow_status=row.workflow_status,
                processing_step=row.processing_step,
                failure_category=row.failure_category,
                occurred_at_utc=row.occurred_at_utc,
            )
            for row in rows
        ]
