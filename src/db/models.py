# File Name: models.py
# Purpose: Defines the SQLAlchemy ORM tables for the Wave 1/Wave 2 canonical case and workflow schema.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# Wave 1 (Organization, Lifecycle & Core Reference Foundation) added no
# SQLAlchemy ORM classes at all -- its 14 tables exist only as raw,
# hand-authored Alembic DDL (see
# migrations/versions/c841e86a8516_create_wave_1_database_foundation.py).
# Wave 2 (Case & Workflow Schema Expansion) is the first Wave to add
# real SQLAlchemy declarative model classes, for the 6 genuinely new
# tables plus the evolved canonical workflow_runs/audit_events.
#
# FOREIGN KEY POLICY (read before adding a column):
# A SQLAlchemy ForeignKey() is declared ONLY when the referenced table
# also has an ORM class registered on this same Base (i.e. another
# class in this file). Most Wave 1 reference-master tables
# (workflow_statuses, workflow_actions, failure_categories, departments,
# locations, source_components, reasons, event_types, event_categories,
# actor_types, result_codes, case_statuses, clients) have no ORM class
# -- only raw Alembic DDL -- so declaring ForeignKey("workflow_statuses...")
# here would make Base.metadata.create_all() crash with
# NoReferencedTableError (SQLAlchemy cannot resolve a target table that
# no Python object describes). Columns referencing those tables are
# therefore plain typed columns with NO SQLAlchemy-level ForeignKey --
# this mirrors the exact pattern already documented below for
# AuditEventORM.trace_id in the original prototype: "a logical,
# application-level relationship ... not a physical foreign key ... a
# deliberate, documented simplification." The REAL physical SQL Server
# foreign key for every one of these columns is still created by the
# Alembic migration (raw op.create_table + ForeignKeyConstraint, the
# same mechanism Wave 1 used) -- only the Python ORM layer's
# ForeignKey() declaration is omitted, and only where its target table
# has no sibling ORM class here.

from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


# =====================================================================
# DOCUMENT TYPES TABLE (pulled forward from Wave 3 into Wave 2)
# Purpose:
# Controlled supporting-document types used by completeness checks.
#
# Why:
# case_documents.document_type_code (this Wave) is a required (NOT
# NULL) reference to this table. document_types is a zero-dependency
# reference master, so -- exactly like case_statuses being pulled
# forward into Wave 1 for prior_authorization_cases' sake -- it is
# pulled forward into Wave 2 here, schema only. This does NOT seed any
# reference/business rows; reference-data loading remains a separate,
# still-OPEN decision (see docs/database/migration_plan.md Section 16).
# =====================================================================
class DocumentTypeORM(Base):
    """A controlled document-type reference row."""

    __tablename__ = "document_types"

    document_type_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_type_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # No physical FK: reasons has no ORM class (Wave 1, raw DDL only).
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# WORKFLOW DEFINITIONS TABLE
# Purpose:
# Versioned workflow definition used to identify exactly which
# orchestration design processed a run.
# =====================================================================
class WorkflowDefinitionORM(Base):
    """One versioned workflow definition (e.g. PRIOR_AUTHORIZATION 1.0)."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_code", "version_no", name="uq_workflow_definitions_code_version"
        ),
    )

    workflow_definition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version_no: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    effective_from_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_to_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# WORKFLOW DEFINITION STEPS TABLE
# Purpose:
# Ordered steps belonging to a versioned workflow definition. step_code
# is the stable, persisted contract that a future LangGraph-node-to-step
# mapping resolves to (see ADR-007) -- never a Python function name.
# =====================================================================
class WorkflowDefinitionStepORM(Base):
    """One ordered step within a versioned workflow definition."""

    __tablename__ = "workflow_definition_steps"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id",
            "step_code",
            name="uq_workflow_definition_steps_definition_step_code",
        ),
    )

    workflow_step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_definitions.workflow_definition_id"),
        nullable=False,
    )
    step_code: Mapped[str] = mapped_column(String(64), nullable=False)
    step_name: Mapped[str] = mapped_column(String(150), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # No physical FK: source_components has no ORM class (Wave 1, raw DDL only).
    source_component_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# PRIOR AUTHORIZATION CASES TABLE
# Purpose:
# Persistent case-level business record for the synthetic
# prior-authorization prototype -- the Case Master every workflow run,
# diagnosis, and document row ultimately belongs to.
# =====================================================================
class PriorAuthorizationCaseORM(Base):
    """One synthetic prior-authorization case."""

    __tablename__ = "prior_authorization_cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # No physical FK: clients has no ORM class (Wave 1, raw DDL only).
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # No physical FK: case_statuses has no ORM class (Wave 1, raw DDL only).
    case_status_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="OPEN"
    )
    member_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_service_code: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_date: Mapped[date] = mapped_column(nullable=False)
    source_component_code: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    close_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    clinical_notes_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    metadata_json: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# CASE DIAGNOSES TABLE
# Purpose:
# Diagnosis-code rows associated with a case.
# =====================================================================
class CaseDiagnosisORM(Base):
    """One diagnosis-code row belonging to a case."""

    __tablename__ = "case_diagnoses"

    case_diagnosis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prior_authorization_cases.case_id"),
        nullable=False,
    )
    diagnosis_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_component_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# CASE DOCUMENTS TABLE
# Purpose:
# Metadata/evidence reference for supporting documents associated with
# a case -- never the document's raw content.
# =====================================================================
class CaseDocumentORM(Base):
    """One supporting-document reference row belonging to a case."""

    __tablename__ = "case_documents"

    case_document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prior_authorization_cases.case_id"),
        nullable=False,
    )
    document_type_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("document_types.document_type_code"),
        nullable=False,
    )
    document_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    received_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_component_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# WORKFLOW RUNS TABLE (canonical -- evolved in place from the Wave 0/1
# prototype shape)
# Purpose:
# Stores the current state of one workflow run, identified by
# trace_id -- one row per trace_id, updated in place as the run
# progresses. This is the canonical Wave 2 shape (23 columns; see
# docs/database/data_dictionary.md `workflow_runs`), replacing the
# 7-column Task 18A prototype shape.
#
# Why:
# A reviewer or dashboard needs to look up "what is the current status
# of this run?" without replaying every audit event. This table is the
# small, current-state counterpart to the append-only audit_events
# table below.
#
# Important Notes:
# - trace_id is the primary key: see AuditRepository.save_workflow_run()
#   in src/db/repository.py, which updates the existing row for a
#   trace_id instead of inserting a second one.
# - trace_id is application-generated (UUID4), created once per run,
#   never regenerated mid-run -- see ADR-007.
# - This table does NOT persist the full PriorAuthorizationCase, raw
#   FHIR content, or raw AI output -- see src/models/audit.py for the
#   exact, minimal fields this row is allowed to carry.
# - The composite UNIQUE(trace_id, case_id) that would let audit_events
#   carry a composite FK back to this table is Wave 6 relational
#   hardening (see docs/database/migration_plan.md Section 5.B) and is
#   intentionally not added here.
# =====================================================================
class WorkflowRunORM(Base):
    """One row per workflow run trace, holding its current canonical snapshot."""

    __tablename__ = "workflow_runs"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prior_authorization_cases.case_id"),
        nullable=False,
    )
    workflow_definition_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_definitions.workflow_definition_id"),
        nullable=False,
    )
    # No physical FK: workflow_statuses has no ORM class (Wave 1, raw DDL only).
    workflow_status_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="PROCESSING"
    )
    next_action_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_department_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    processing_location_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    initiated_by_component_code: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    started_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    metadata_json: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delete_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_reason_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)


# =====================================================================
# AUDIT EVENTS TABLE (canonical -- evolved in place from the Wave 0/1
# prototype shape)
# Purpose:
# Stores one append-only row per audit event, for every workflow trace.
# This is the canonical Wave 2 shape (19 columns; see
# docs/database/data_dictionary.md `audit_events`), replacing the
# 9-column Task 18A prototype shape.
#
# Why:
# Unlike workflow_runs (current state only), this table is meant to
# grow: every meaningful step gets its own row, in occurred_at_utc
# order, so a reviewer can see the full sequence of what happened for
# one trace_id.
#
# Important Notes:
# - trace_id/case_id are ordinary (non-composite) foreign keys here.
#   The composite FK pair -- (trace_id, case_id) -> workflow_runs and
#   (event_type_code, event_category_code) -> event_types -- that would
#   cross-validate case/category consistency is Wave 6 relational
#   hardening (see docs/database/migration_plan.md Section 5.B) and is
#   intentionally not added here.
# - workflow_step_id references workflow_definition_steps.workflow_step_id,
#   never a Python LangGraph node name or free-text step description --
#   see ADR-007.
# - No large generic JSON/blob payload column exists here beyond the
#   small, allowlisted metadata_json extension field.
# - event_id is the primary key: AuditRepository.append_audit_event()
#   must fail, not silently overwrite, if the same event_id is used
#   twice.
# - Append-only by design: no updated_at_utc/updated_by/is_deleted/
#   deleted_* columns exist on this table.
# - trace_id is indexed (not just a plain column) so
#   list_audit_events(trace_id) stays efficient as this table grows.
# =====================================================================
class AuditEventORM(Base):
    """One append-only row per audit event."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_trace_id", "trace_id"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_runs.trace_id"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prior_authorization_cases.case_id"),
        nullable=False,
    )
    # No physical FK: event_types has no ORM class (Wave 1, raw DDL only).
    event_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # No physical FK: event_categories has no ORM class (Wave 1, raw DDL only).
    event_category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_step_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("workflow_definition_steps.workflow_step_id"),
        nullable=True,
    )
    source_component_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_code: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_event_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("audit_events.event_id"),
        nullable=True,
    )
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    metadata_json: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
