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
                    # created_at_utc/created_by are immutable after creation
                    # (see docs/database/data_model.md Section 4) and are
                    # therefore never overwritten here.
                    existing.case_id = snapshot.case_id
                    existing.workflow_definition_id = snapshot.workflow_definition_id
                    existing.workflow_status_code = snapshot.workflow_status_code
                    existing.next_action_code = snapshot.next_action_code
                    existing.human_review_required = snapshot.human_review_required
                    existing.failure_category_code = snapshot.failure_category_code
                    existing.processing_department_id = snapshot.processing_department_id
                    existing.processing_location_id = snapshot.processing_location_id
                    existing.initiated_by_component_code = (
                        snapshot.initiated_by_component_code
                    )
                    existing.started_at_utc = snapshot.started_at_utc
                    existing.completed_at_utc = snapshot.completed_at_utc
                    existing.schema_version = snapshot.schema_version
                    existing.metadata_json = snapshot.metadata_json
                    existing.updated_at_utc = snapshot.updated_at_utc
                    existing.updated_by = snapshot.updated_by
                    existing.is_deleted = snapshot.is_deleted
                    existing.deleted_at_utc = snapshot.deleted_at_utc
                    existing.deleted_by = snapshot.deleted_by
                    existing.delete_reason_code = snapshot.delete_reason_code
                    existing.delete_reason_text = snapshot.delete_reason_text

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
