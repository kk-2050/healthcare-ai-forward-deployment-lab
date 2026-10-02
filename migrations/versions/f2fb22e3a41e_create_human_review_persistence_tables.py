# File Name: f2fb22e3a41e_create_human_review_persistence_tables.py
# Purpose: Task 23 -- third physical Alembic revision, adding the canonical Human-in-the-Loop persistence tables (pulled forward from Wave 4), hand-authored against the canonical database documentation.
# Creation Date: 2026-09-21
# Author: K.Kashiwagi
"""create human review persistence tables

Revision ID: f2fb22e3a41e
Revises: b9aba5b07ac8
Create Date: 2026-09-21 15:40:56.454305

Scope (see docs/database/data_model.md Section 16, "Wave 4 --
Integration, AI & Human-in-the-Loop Persistence: Integration execution,
AI run/tasks, human review"):

    human_review_statuses, human_review_outcomes, human_reviews

Wave boundary conflict (reported and resolved before implementation,
not silently decided): Task 23 (Human-in-the-Loop persistence +
pause/resume) needs `human_reviews` to exist, but the canonical design
scopes it to Wave 4, and no Wave 4 table has been built yet. Every
other FK dependency `human_reviews` needs (`workflow_runs`,
`prior_authorization_cases`, `reasons` including its HUMAN_REVIEW
domain rows, `departments`, `locations`, `actor_types` including
HUMAN_REVIEWER, `source_components`) already physically exists (Waves
1-2) and is already loaded (Task 22's reference-data loader). Per the
same "pull the zero-dependency prerequisite forward" precedent already
used twice in this project (`case_statuses` -> Wave 1 for
`prior_authorization_cases`; `document_types` -> Wave 2 for
`case_documents`), this revision pulls forward exactly the three
tables `human_reviews` itself needs -- its own two dedicated reference
masters -- and nothing else from Wave 4. `integration_executions`,
`ai_analysis_runs`, `ai_analysis_tasks`, and `ai_task_types` are NOT
included here; nothing in Task 23 requires them, and pulling them in
would be unjustified scope creep.

This revision creates schema only. It does NOT insert any reference/
seed data (schema and seed-data loading are separate concerns per
ADR-005's Reference Data Policy -- loading the `human_review_statuses`/
`human_review_outcomes` rows themselves is a separate, later,
explicitly-approved step using the existing src/db/reference_data.py
loader) and does NOT include any other Wave 3+ table.

Wave-now/Wave-6 boundary (same responsibility principle established in
the Wave 1/Wave 2 revisions): this revision creates primary keys,
ordinary foreign keys, and column definitions/types/nullability/
defaults -- the identity and structure a valid human_reviews /
human_review_statuses / human_review_outcomes row requires. It does
NOT create: the two secondary indexes cataloged in
docs/database/constraints_and_indexes.md Section 5
(`human_reviews(trace_id, review_status_code)`,
`human_reviews(assigned_department_id, review_status_code)`), or the
same-row CHECK constraint keeping `completed_at_utc`/
`review_outcome_code` nullability synchronized (Section 4's
"Human-review completion pair" -- the same lifecycle-CHECK category
already deferred to Wave 6 for every other table in this project).
`human_reviews` has no documented business-key UNIQUE constraint, so
none is created here.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = "f2fb22e3a41e"
down_revision: Union[str, Sequence[str], None] = "b9aba5b07ac8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# SHARED COLUMN / CONSTRAINT HELPERS
# Purpose:
# Every non-audit table in this project carries the same nine standard
# lifecycle/control fields (docs/database/constraints_and_indexes.md
# Sec 1). Mirrors the Wave 1/Wave 2 revisions' identically-named helpers
# exactly.
# =====================================================================
def _control_columns() -> list[sa.Column]:
    """The nine standard control fields shared by every non-audit table."""
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

    Identical role to the Wave 1/Wave 2 revisions' helper of the same
    name -- a required ordinary FK establishing a real documented
    relationship, not Wave 6 hardening, so it is kept here.
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
# Creates the Human-in-the-Loop persistence schema, in dependency-safe
# order: the two reference masters first, then human_reviews itself
# (which FKs to both of them plus workflow_runs/prior_authorization_cases,
# already created by Waves 1-2).
# =====================================================================
def upgrade() -> None:
    """Creates human_review_statuses, human_review_outcomes, and human_reviews."""

    # ---- human_review_statuses (reference_data.md Section 17) ----
    op.create_table(
        "human_review_statuses",
        sa.Column("review_status_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("review_status_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "review_status_code", name="pk_human_review_statuses"
        ),
        _delete_reason_fk("human_review_statuses"),
    )

    # ---- human_review_outcomes (reference_data.md Section 18) ----
    # "No autonomous clinical approval/denial outcome is defined" --
    # reference_data.md Section 18's own note, preserved here as a
    # schema-level reminder of why no such column/value exists.
    op.create_table(
        "human_review_outcomes",
        sa.Column("review_outcome_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("review_outcome_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "returns_to_workflow",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "closes_case", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "review_outcome_code", name="pk_human_review_outcomes"
        ),
        _delete_reason_fk("human_review_outcomes"),
    )

    # ---- human_reviews (data_dictionary.md `human_reviews`) ----
    op.create_table(
        "human_reviews",
        sa.Column("review_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("trace_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column(
            "review_status_code",
            mssql.NVARCHAR(64),
            nullable=False,
            server_default=sa.text("'REQUESTED'"),
        ),
        sa.Column("review_outcome_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("reason_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("assigned_department_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("assigned_location_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("requested_at_utc", mssql.DATETIME2(precision=3), nullable=False),
        sa.Column("started_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column("completed_at_utc", mssql.DATETIME2(precision=3), nullable=True),
        sa.Column("reviewer_actor_type_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("reviewer_reference", mssql.NVARCHAR(128), nullable=True),
        sa.Column("review_note_text", mssql.NVARCHAR(2000), nullable=True),
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("review_id", name="pk_human_reviews"),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["workflow_runs.trace_id"],
            name="fk_human_reviews_trace_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["prior_authorization_cases.case_id"],
            name="fk_human_reviews_case_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["review_status_code"],
            ["human_review_statuses.review_status_code"],
            name="fk_human_reviews_review_status_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["review_outcome_code"],
            ["human_review_outcomes.review_outcome_code"],
            name="fk_human_reviews_review_outcome_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["reason_code"],
            ["reasons.reason_code"],
            name="fk_human_reviews_reason_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_department_id"],
            ["departments.department_id"],
            name="fk_human_reviews_assigned_department_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_location_id"],
            ["locations.location_id"],
            name="fk_human_reviews_assigned_location_id",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_actor_type_code"],
            ["actor_types.actor_type_code"],
            name="fk_human_reviews_reviewer_actor_type_code",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["source_component_code"],
            ["source_components.source_component_code"],
            name="fk_human_reviews_source_component_code",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("human_reviews"),
    )


# =====================================================================
# DOWNGRADE
# Purpose:
# Drops the Human-in-the-Loop persistence tables in exact reverse
# dependency order.
#
# Important Notes:
# - Purely structural (empty tables being dropped) -- safely reversible
#   because this revision is additive with no seed data. It does not
#   claim to restore any data.
# - Never touches workflow_runs, prior_authorization_cases, or any
#   Wave 1/Wave 2 table.
# =====================================================================
def downgrade() -> None:
    """Drops human_reviews, human_review_outcomes, and human_review_statuses."""
    op.drop_table("human_reviews")
    op.drop_table("human_review_outcomes")
    op.drop_table("human_review_statuses")
