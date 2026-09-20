# File Name: b9aba5b07ac8_create_wave_2_canonical_case_workflow_.py
# Purpose: Wave 2 (Case & Workflow Schema Expansion) -- second physical Alembic revision, hand-authored against the canonical database documentation.
# Creation Date: 2026-09-18
# Author: K.Kashiwagi
"""create wave 2 canonical case workflow schema

Revision ID: b9aba5b07ac8
Revises: c841e86a8516
Create Date: 2026-09-18 16:46:30.393622

Scope (see docs/database/data_model.md Section 16, "Wave 2 -- Case &
Workflow Schema Expansion: Cases, diagnoses, documents, workflow
definitions/steps, target workflow_runs, target audit_events"):

    workflow_definitions, workflow_definition_steps,
    prior_authorization_cases, case_diagnoses, case_documents,
    workflow_runs (canonical replacement), audit_events (canonical
    replacement)

Plus `document_types`, pulled forward from Wave 3 into this revision --
see "Wave boundary conflict" below.

Wave boundary conflict (reported and resolved before implementation,
not silently decided): `case_documents.document_type_code` is a
required (NOT NULL) foreign key to `document_types`, but the executed
Wave 1 revision's own docstring explicitly scoped `document_types` to
"Wave 3 for requirements/document vocab", and data_model.md Section 16
agrees. `document_types` is a zero-dependency reference master with no
other Wave 3 table hard-depending on it being created after Wave 2.
Per data_model.md Section 16's own definition ("Wave = dependency-aware
implementation batch") and the direct precedent already used in Wave 1
itself (`case_statuses` was pulled forward into Wave 1 because Wave 2's
`prior_authorization_cases` required it), `document_types` is pulled
forward into this Wave 2 revision, schema only -- zero rows. This does
NOT resolve or touch the separate, still-OPEN reference-data-loading
decision (docs/database/migration_plan.md Section 16).

Controlled prototype rebuild (see
docs/decisions/ADR-006-first-revision-and-brownfield-strategy.md,
"Wave 2 Controlled Rebuild"): the existing `dbo.workflow_runs` and
`dbo.audit_events` tables are the pre-Alembic Task 18A/18B prototype
shape (7 and 9 columns respectively), holding only disposable synthetic
Task 18B rows. This revision DROPS both prototype tables and CREATES
their canonical Wave 2 shape (23 and 19 columns respectively, per
docs/database/data_dictionary.md) under the same table names. This is
a deliberate, approved, structural rebuild -- not an in-place ALTER,
and not a data migration of the old synthetic rows (which are
disposable and not carried forward, per ADR-006).

ORM layer note (src/db/models.py): WorkflowRunORM/AuditEventORM were
evolved in place to this same canonical shape, in the same migration
task, so exactly one authoritative SQLAlchemy mapping exists per
physical table. This migration's DDL is still hand-authored
independently of those ORM classes (matching the Wave 1 precedent and
ADR-005's Autogenerate Policy), not generated from them.

Wave 1/Wave 6 boundary (same responsibility principle established in
the Wave 1 revision -- see its module docstring): this revision creates
primary keys, ordinary/self-referencing foreign keys, column
definitions, and the business-key UNIQUE constraints that define core
row identity (`workflow_definitions(workflow_code, version_no)`,
`workflow_definition_steps(workflow_definition_id, step_code)`). It
does NOT create: the composite FK pair that would cross-validate
`audit_events(trace_id, case_id)` against `workflow_runs` or
`audit_events(event_type_code, event_category_code)` against
`event_types` (requires a UNIQUE(trace_id, case_id) on `workflow_runs`
and the already-deferred `event_types` composite UNIQUE -- both Wave 6,
per docs/database/migration_plan.md Section 5.B); the case-close/
logical-delete lifecycle CHECK constraints; any ISJSON CHECK constraint
on a metadata_json column; the filtered UNIQUE enforcing "at most one
active primary diagnosis" on `case_diagnoses` (a conditional/hardening
constraint, not row identity); or any secondary (non-identity) index
from docs/database/constraints_and_indexes.md Section 5 (e.g.
`prior_authorization_cases(client_id, case_status_code, is_deleted)`,
`workflow_runs(case_id, started_at_utc)`,
`audit_events(case_id, occurred_at_utc)`). All of these remain
Wave 6 deliverables. The single exception is `ix_audit_events_trace_id`
on the recreated canonical `audit_events` table: this index already
existed on the pre-Wave prototype table since Task 18A (before Wave
numbering existed at all), so it is preserved for continuity during the
rebuild rather than treated as new Wave 2 or Wave 6 scope.

This revision does NOT insert any reference/seed data (schema and
seed-data loading are separate concerns per ADR-005's Reference Data
Policy) and does NOT include any Wave 3+ table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = "b9aba5b07ac8"
down_revision: Union[str, Sequence[str], None] = "c841e86a8516"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# SHARED COLUMN / CONSTRAINT HELPERS
# Purpose:
# Every Wave 2 non-audit table carries the same nine standard
# lifecycle/control fields (docs/database/constraints_and_indexes.md
# Sec 1) -- audit_events is the sole, documented exception (append-only:
# only created_at_utc/created_by). Mirrors the Wave 1 revision's
# _control_columns()/_delete_reason_fk() helpers exactly.
# =====================================================================
def _control_columns() -> list[sa.Column]:
    """The nine standard control fields shared by every non-audit Wave 2 table."""
    return [
        sa.Column("created_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("created_by", mssql.NVARCHAR(128), nullable=False),
        sa.Column("updated_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("updated_by", mssql.NVARCHAR(128), nullable=False),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("deleted_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column("deleted_by", mssql.NVARCHAR(128), nullable=True),
        sa.Column("delete_reason_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("delete_reason_text", mssql.NVARCHAR(1000), nullable=True),
    ]


def _delete_reason_fk(table_name: str) -> sa.ForeignKeyConstraint:
    """Ordinary, single-column FK from delete_reason_code to reasons.reason_code.

    Identical role to the Wave 1 revision's helper of the same name --
    a required ordinary FK establishing a real documented relationship,
    not Wave 6 hardening, so it is kept here in Wave 2.
    """
    return sa.ForeignKeyConstraint(
        ["delete_reason_code"],
        ["reasons.reason_code"],
        name=f"fk_{table_name}_delete_reason_code_reasons",
        ondelete="NO ACTION",
    )


# =====================================================================
# UPGRADE
# Purpose:
# Creates the Wave 2 case/workflow schema, in dependency-safe order,
# and performs the ADR-006-approved controlled rebuild of
# workflow_runs/audit_events into their canonical shape.
# =====================================================================
def upgrade() -> None:
    """Creates the Wave 2 -- Case & Workflow Schema Expansion schema."""

    # ---- document_types (pulled forward from Wave 3; see module docstring) ----
    op.create_table(
        "document_types",
        sa.Column("document_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("document_type_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("document_type_code", name="pk_document_types"),
        _delete_reason_fk("document_types"),
    )

    # ---- workflow_definitions ------------------------------------------------
    op.create_table(
        "workflow_definitions",
        sa.Column("workflow_definition_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("version_no", mssql.NVARCHAR(32), nullable=False),
        sa.Column("workflow_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("description", mssql.NVARCHAR(1000), nullable=True),
        sa.Column("effective_from_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("effective_to_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "workflow_definition_id", name="pk_workflow_definitions"
        ),
        sa.UniqueConstraint(
            "workflow_code",
            "version_no",
            name="uq_workflow_definitions_code_version",
        ),
        _delete_reason_fk("workflow_definitions"),
    )

    # ---- workflow_definition_steps --------------------------------------------
    op.create_table(
        "workflow_definition_steps",
        sa.Column("workflow_step_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_definition_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("step_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("step_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_optional", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "workflow_step_id", name="pk_workflow_definition_steps"
        ),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "step_code",
            name="uq_workflow_definition_steps_definition_step_code",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id"],
            ["workflow_definitions.workflow_definition_id"],
            name="fk_workflow_definition_steps_workflow_definition_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_workflow_definition_steps_source_component_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("workflow_definition_steps"),
    )

    # ---- prior_authorization_cases --------------------------------------------
    op.create_table(
        "prior_authorization_cases",
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("client_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("department_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("location_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "case_status_code",
            mssql.NVARCHAR(64),
            nullable=False,
            server_default=sa.text("'OPEN'"),
        ),
        sa.Column("member_id", mssql.NVARCHAR(128), nullable=False),
        sa.Column("provider_id", mssql.NVARCHAR(128), nullable=False),
        sa.Column("requested_service_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("opened_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("closed_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column("closed_by", mssql.NVARCHAR(128), nullable=True),
        sa.Column("close_reason_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("close_reason_text", mssql.NVARCHAR(1000), nullable=True),
        sa.Column(
            "clinical_notes_present",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "schema_version",
            mssql.NVARCHAR(32),
            nullable=False,
            server_default=sa.text("'1'"),
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("case_id", name="pk_prior_authorization_cases"),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name="fk_prior_authorization_cases_client_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.department_id"],
            name="fk_prior_authorization_cases_department_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.location_id"],
            name="fk_prior_authorization_cases_location_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["case_status_code"],
            ["case_statuses.case_status_code"],
            name="fk_prior_authorization_cases_case_status_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_prior_authorization_cases_source_component_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["close_reason_code"],
            ["reasons.reason_code"],
            name="fk_prior_authorization_cases_close_reason_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("prior_authorization_cases"),
    )

    # ---- case_diagnoses ---------------------------------------------------
    op.create_table(
        "case_diagnoses",
        sa.Column("case_diagnosis_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("diagnosis_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "sequence_no", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("case_diagnosis_id", name="pk_case_diagnoses"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["prior_authorization_cases.case_id"],
            name="fk_case_diagnoses_case_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_case_diagnoses_source_component_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("case_diagnoses"),
    )

    # ---- case_documents -----------------------------------------------------
    op.create_table(
        "case_documents",
        sa.Column("case_document_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("document_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("document_reference", mssql.NVARCHAR(200), nullable=False),
        sa.Column("received_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_available", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("case_document_id", name="pk_case_documents"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["prior_authorization_cases.case_id"],
            name="fk_case_documents_case_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["document_type_code"],
            ["document_types.document_type_code"],
            name="fk_case_documents_document_type_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_case_documents_source_component_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("case_documents"),
    )

    # ---- workflow_runs: controlled rebuild (prototype -> canonical) -----------
    # Drops the Task 18A/18B prototype shape (7 columns, no physical FKs)
    # and creates the canonical Wave 2 shape (23 columns). Per ADR-006,
    # the prototype's synthetic rows are disposable and are not migrated.
    op.drop_table("workflow_runs")
    op.create_table(
        "workflow_runs",
        sa.Column("trace_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_definition_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column(
            "workflow_status_code",
            mssql.NVARCHAR(64),
            nullable=False,
            server_default=sa.text("'PROCESSING'"),
        ),
        sa.Column("next_action_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("failure_category_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("processing_department_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("processing_location_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("initiated_by_component_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("started_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("completed_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column(
            "schema_version",
            mssql.NVARCHAR(32),
            nullable=False,
            server_default=sa.text("'1'"),
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("trace_id", name="pk_workflow_runs"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["prior_authorization_cases.case_id"],
            name="fk_workflow_runs_case_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id"],
            ["workflow_definitions.workflow_definition_id"],
            name="fk_workflow_runs_workflow_definition_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_status_code"],
            ["workflow_statuses.workflow_status_code"],
            name="fk_workflow_runs_workflow_status_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["next_action_code"],
            ["workflow_actions.workflow_action_code"],
            name="fk_workflow_runs_next_action_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["failure_category_code"],
            ["failure_categories.failure_category_code"],
            name="fk_workflow_runs_failure_category_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["processing_department_id"],
            ["departments.department_id"],
            name="fk_workflow_runs_processing_department_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["processing_location_id"],
            ["locations.location_id"],
            name="fk_workflow_runs_processing_location_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by_component_code"],
            ["source_components.source_component_code"],
            name="fk_workflow_runs_initiated_by_component_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("workflow_runs"),
    )

    # ---- audit_events: controlled rebuild (prototype -> canonical) ------------
    # Drops the Task 18A/18B prototype shape (9 columns, no physical FKs)
    # and creates the canonical Wave 2 shape (19 columns, append-only --
    # no updated_*/is_deleted/deleted_*/delete_reason_* columns). Per
    # ADR-006, the prototype's synthetic rows are disposable and are not
    # migrated.
    op.drop_table("audit_events")
    op.create_table(
        "audit_events",
        sa.Column("event_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("trace_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("event_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("event_category_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_status_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("workflow_step_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("actor_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("actor_identifier", mssql.NVARCHAR(128), nullable=True),
        sa.Column("result_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("failure_category_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("reason_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("related_event_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("occurred_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column(
            "schema_version",
            mssql.NVARCHAR(32),
            nullable=False,
            server_default=sa.text("'1'"),
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        sa.Column("created_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("created_by", mssql.NVARCHAR(128), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["workflow_runs.trace_id"],
            name="fk_audit_events_trace_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["prior_authorization_cases.case_id"],
            name="fk_audit_events_case_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["event_type_code"],
            ["event_types.event_type_code"],
            name="fk_audit_events_event_type_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["event_category_code"],
            ["event_categories.event_category_code"],
            name="fk_audit_events_event_category_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_status_code"],
            ["workflow_statuses.workflow_status_code"],
            name="fk_audit_events_workflow_status_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id"],
            ["workflow_definition_steps.workflow_step_id"],
            name="fk_audit_events_workflow_step_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_audit_events_source_component_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["actor_type_code"],
            ["actor_types.actor_type_code"],
            name="fk_audit_events_actor_type_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["result_code"],
            ["result_codes.result_code"],
            name="fk_audit_events_result_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["failure_category_code"],
            ["failure_categories.failure_category_code"],
            name="fk_audit_events_failure_category_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            ["reasons.reason_code"],
            name="fk_audit_events_reason_code",
            ondelete="NO ACTION",
        ),
        # Self-referencing FK supporting immutable correction chains
        # (a correction is a new event that points back at the event it
        # corrects -- never an update/delete of the original). Ordinary
        # self-referencing FK, same treatment as departments.parent_department_id
        # in Wave 1 -- not Wave 6 hardening.
        sa.ForeignKeyConstraint(
            ["related_event_id"],
            ["audit_events.event_id"],
            name="fk_audit_events_related_event_id",
            ondelete="NO ACTION",
        ),
        # Preserved from the pre-Wave Task 18A prototype (not new Wave 2
        # or Wave 6 scope) -- see module docstring.
        sa.Index("ix_audit_events_trace_id", "trace_id"),
    )


# =====================================================================
# DOWNGRADE
# Purpose:
# Reverses this revision back to the exact Wave 1 physical state:
# drops every Wave 2 table, then recreates workflow_runs/audit_events
# in their original Task 18A/18B prototype shape (empty).
#
# Important Notes:
# - This is a purely structural downgrade. It does not and cannot
#   restore either the Wave 2 canonical rows or the original prototype's
#   synthetic Task 18B rows -- both were already gone (the prototype
#   rows deliberately, per ADR-006's controlled rebuild; the Wave 2
#   rows because Wave 2 never seeds/inserts any row itself).
# - The recreated prototype tables intentionally use generic
#   sa.String/sa.DateTime/sa.Boolean (not the mssql.NVARCHAR/DATETIME2
#   types used elsewhere in this file) to faithfully reproduce what
#   Base.metadata.create_all() originally produced for them in Task
#   18A/18B -- not this project's later Alembic-era type convention.
# =====================================================================
def downgrade() -> None:
    """Reverses Wave 2, restoring the original prototype workflow_runs/audit_events shape."""
    op.drop_table("audit_events")
    op.drop_table("workflow_runs")
    op.drop_table("case_documents")
    op.drop_table("case_diagnoses")
    op.drop_table("prior_authorization_cases")
    op.drop_table("workflow_definition_steps")
    op.drop_table("workflow_definitions")
    op.drop_table("document_types")

    op.create_table(
        "workflow_runs",
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("workflow_status", sa.String(64), nullable=False),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("failure_category", sa.String(64), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_category", sa.String(64), nullable=False),
        sa.Column("workflow_status", sa.String(64), nullable=True),
        sa.Column("processing_step", sa.String(128), nullable=True),
        sa.Column("failure_category", sa.String(64), nullable=True),
        sa.Column("occurred_at_utc", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_audit_events_trace_id", "audit_events", ["trace_id"], unique=False
    )
