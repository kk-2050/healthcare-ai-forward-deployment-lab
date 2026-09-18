# File Name: c841e86a8516_create_wave_1_database_foundation.py
# Purpose: Wave 1 (Organization, Lifecycle & Core Reference Foundation) — first physical Alembic revision, hand-authored against the canonical database documentation.
# Creation Date: 2026-09-17
# Author: K.Kashiwagi
"""create wave 1 database foundation

Revision ID: c841e86a8516
Revises:
Create Date: 2026-09-17 21:42:48.609832

Scope (see docs/decisions/ADR-006-first-revision-and-brownfield-strategy.md):
This revision creates ONLY the Wave 1 tables determined from
docs/database/data_model.md Section 16 ("Organization masters,
workflow/audit vocabularies, seed data") and
docs/database/migration_plan.md Sections 10-11 (dependency tiers /
Wave boundary review):

    reasons, countries, clients, locations, departments, case_statuses,
    workflow_statuses, workflow_actions,
    event_categories, event_types, actor_types, source_components,
    result_codes, failure_categories

It deliberately does NOT include `workflow_definitions`,
`workflow_definition_steps`, `requirement_types`, `document_types`,
`human_review_statuses`, `human_review_outcomes`, `ai_task_types`, or
`discovery_item_types` -- each of those reference masters is scoped to
a later Wave (Wave 2 for workflow-definition vocab, Wave 3 for
requirements/document vocab, Wave 4 for AI/human-review vocab, Wave 5
for intake vocab) whose Wave description explicitly names that table.
`case_statuses` IS included here: it is a lifecycle reference master
(Wave 1's own name is "Organization, Lifecycle & Core Reference
Foundation") required by Wave 2's `prior_authorization_cases`, treated
the same way `workflow_statuses` already is.

Wave 6 boundary (docs/database/data_model.md Sec 16: "Wave 6 --
Relational Hardening & End-to-End Validation: Composite FKs,
uniqueness, CHECK constraints, indexes, seed validation, JSON
validation, E2E tests"): the Wave 1/Wave 6 line is drawn by the
RESPONSIBILITY of each constraint, not merely its SQL category.
Wave 1 owns core table identity and business invariants: primary keys,
ordinary (including self-referencing) foreign keys needed to establish
the documented table relationships, column
definitions/types/nullability/defaults, AND the business-key UNIQUE
constraints that define what makes a row identity-distinct
(`clients.client_code`, `countries.iso3_code`,
`locations(client_id, location_code)`,
`departments(client_id, department_code)`) -- these are part of what a
valid client/country/location/department record IS, not a later
hardening pass. Wave 6 owns relational hardening, cross-column
validation, JSON validation, secondary (non-identity) indexes,
composite-FK support, and end-to-end constraint validation: the global
logical-delete lifecycle CHECK, the ISJSON CHECK constraints, the
non-identity lookup indexes, and the `event_types` composite UNIQUE
whose only purpose is supporting Wave 2's future `audit_events`
composite FK (`event_type_code` alone is already unique via the PK; the
composite constraint is FK-support hardening, not identity). See the
DEFERRED TO WAVE 6 list in Task 20A's final report for the complete,
traceable set of constraints/indexes intentionally left out of this
revision.

This revision does NOT touch `dbo.workflow_runs` or `dbo.audit_events`
(the existing Task 18B brownfield prototype tables), does NOT insert
any reference/seed data (schema and seed-data loading are separate
concerns per ADR-005's Reference Data Policy), and does NOT include any
Wave 2+ table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = "c841e86a8516"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =====================================================================
# SHARED COLUMN / CONSTRAINT HELPERS
# Purpose:
# Every Wave 1 table (all non-audit persistent tables in the canonical
# model) carries the same nine standard lifecycle/control fields
# (docs/database/constraints_and_indexes.md Sec 1). This helper avoids
# repeating that column list fourteen times while keeping every
# table's actual DDL fully explicit and reviewable below.
#
# Important Notes:
# - Each call returns brand-new sa.Column instances. SQLAlchemy
#   requires a distinct Column object per table; reusing one instance
#   across tables would raise an error.
# - created_at_utc/updated_at_utc have no SQL Server column DEFAULT.
#   The data dictionary's "CURRENT_UTC" default and "Application /
#   workflow clock (UTC)" source both indicate the application supplies
#   these values explicitly on every insert/update -- matching the
#   existing WorkflowRunORM pattern, which also has no server-side
#   default for these fields. This is a deliberate choice, not an
#   omission.
# - The CHECK constraint that enforces is_deleted/deleted_*/
#   delete_reason_code consistency is intentionally NOT created here --
#   see the Wave 6 boundary note in the module docstring above. The
#   columns exist now (Wave 1); their cross-column CHECK enforcement is
#   a Wave 6 deliverable.
# =====================================================================
def _control_columns() -> list[sa.Column]:
    """The nine standard control fields shared by every Wave 1 table."""
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

    Every Wave 1 table except `reasons` itself gets this constraint --
    reasons.delete_reason_code is intentionally NOT a physical FK (see
    the reasons table below), avoiding a self-referencing FK, per
    data_dictionary.md's explicit note on every delete_reason_code row.
    This is a required ordinary FK establishing a real documented
    relationship, not Wave 6 hardening, so it is kept in Wave 1.
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
# Creates the Wave 1 foundation schema, in dependency-safe order, on
# either a fresh empty SQL Server database or the current brownfield
# local database (where it simply adds these new tables alongside the
# untouched `dbo.workflow_runs`/`dbo.audit_events` prototype tables).
#
# Important Notes:
# - This function creates ONLY the 14 tables listed in the module
#   docstring, with ONLY primary keys, ordinary/self-referencing
#   foreign keys, column definitions, and the business-key UNIQUE
#   constraints that define core row identity -- no CHECK constraint,
#   no FK-support/composite UNIQUE constraint, and no secondary index
#   (all deferred to Wave 6; see the module docstring's Wave 6 boundary
#   note and Task 20A's final report for the full list).
# - It never touches workflow_runs or audit_events, never drops
#   anything, never inserts a row, and never creates Wave 2+ objects.
# =====================================================================
def upgrade() -> None:
    """Creates the Wave 1 -- Organization, Lifecycle & Core Reference Foundation schema."""

    # ---- reasons ------------------------------------------------------
    # Created first: every other Wave 1 table's delete_reason_code
    # references it. reasons' own delete_reason_code has NO physical FK
    # (application-validated only) to avoid a self-referencing FK.
    op.create_table(
        "reasons",
        sa.Column("reason_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("reason_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("reason_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "requires_text", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("reason_code", name="pk_reasons"),
    )

    # ---- countries ------------------------------------------------------
    op.create_table(
        "countries",
        sa.Column("country_code", sa.CHAR(2), nullable=False),
        sa.Column("country_name", mssql.NVARCHAR(100), nullable=False),
        sa.Column("iso3_code", sa.CHAR(3), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("country_code", name="pk_countries"),
        sa.UniqueConstraint("iso3_code", name="uq_countries_iso3_code"),
        _delete_reason_fk("countries"),
    )

    # ---- clients ------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column("client_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("client_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("client_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("client_type_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("default_country_code", sa.CHAR(2), nullable=True),
        sa.Column("default_time_zone", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("client_id", name="pk_clients"),
        sa.UniqueConstraint("client_code", name="uq_clients_client_code"),
        sa.ForeignKeyConstraint(
            ["default_country_code"],
            ["countries.country_code"],
            name="fk_clients_default_country_code_countries",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("clients"),
    )

    # ---- locations ------------------------------------------------------
    op.create_table(
        "locations",
        sa.Column("location_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("client_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("location_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("location_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("country_code", sa.CHAR(2), nullable=False),
        sa.Column("state_province", mssql.NVARCHAR(100), nullable=True),
        sa.Column("city", mssql.NVARCHAR(100), nullable=True),
        sa.Column("postal_code", mssql.NVARCHAR(32), nullable=True),
        sa.Column("time_zone", mssql.NVARCHAR(64), nullable=False),
        sa.Column("location_type_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("location_id", name="pk_locations"),
        sa.UniqueConstraint(
            "client_id", "location_code", name="uq_locations_client_id_location_code"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name="fk_locations_client_id_clients",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["country_code"],
            ["countries.country_code"],
            name="fk_locations_country_code_countries",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("locations"),
    )

    # ---- departments ------------------------------------------------------
    op.create_table(
        "departments",
        sa.Column("department_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("client_id", mssql.NVARCHAR(64), nullable=False),
        sa.Column("department_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("department_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("parent_department_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column("primary_location_id", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("metadata_json", mssql.NVARCHAR(None), nullable=True),
        *_control_columns(),
        sa.PrimaryKeyConstraint("department_id", name="pk_departments"),
        sa.UniqueConstraint(
            "client_id",
            "department_code",
            name="uq_departments_client_id_department_code",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name="fk_departments_client_id_clients",
            ondelete="NO ACTION",
        ),
        # Self-referencing FK required by the canonical table
        # relationship (department hierarchy) -- explicitly kept per
        # Correction 2.
        sa.ForeignKeyConstraint(
            ["parent_department_id"],
            ["departments.department_id"],
            name="fk_departments_parent_department_id_departments",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["primary_location_id"],
            ["locations.location_id"],
            name="fk_departments_primary_location_id_locations",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("departments"),
    )

    # ---- case_statuses ------------------------------------------------------
    # Lifecycle reference master (Wave 1's own name is "Organization,
    # Lifecycle & Core Reference Foundation"), required by Wave 2's
    # prior_authorization_cases.case_status_code -- treated the same
    # way workflow_statuses already is.
    op.create_table(
        "case_statuses",
        sa.Column("case_status_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("case_status_name", mssql.NVARCHAR(100), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("case_status_code", name="pk_case_statuses"),
        _delete_reason_fk("case_statuses"),
    )

    # ---- workflow_statuses ------------------------------------------------------
    op.create_table(
        "workflow_statuses",
        sa.Column("workflow_status_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_status_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("workflow_status_code", name="pk_workflow_statuses"),
        _delete_reason_fk("workflow_statuses"),
    )

    # ---- workflow_actions ------------------------------------------------------
    op.create_table(
        "workflow_actions",
        sa.Column("workflow_action_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("workflow_action_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "requires_human", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("workflow_action_code", name="pk_workflow_actions"),
        _delete_reason_fk("workflow_actions"),
    )

    # ---- event_categories ------------------------------------------------------
    op.create_table(
        "event_categories",
        sa.Column("event_category_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("event_category_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("event_category_code", name="pk_event_categories"),
        _delete_reason_fk("event_categories"),
    )

    # ---- event_types ------------------------------------------------------
    # The composite UNIQUE(event_type_code, event_category_code)
    # (constraints_and_indexes.md Sec 5) is deliberately NOT created
    # here: event_type_code alone is already unique via the PK, so this
    # composite constraint's only responsibility is supporting Wave 2's
    # future audit_events composite FK -- Wave 6 composite-FK-support
    # hardening, not Wave 1 row identity. See the module docstring's
    # Wave 6 boundary note.
    op.create_table(
        "event_types",
        sa.Column("event_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("event_category_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("event_type_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("description", mssql.NVARCHAR(700), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("event_type_code", name="pk_event_types"),
        sa.ForeignKeyConstraint(
            ["event_category_code"],
            ["event_categories.event_category_code"],
            name="fk_event_types_event_category_code_event_categories",
            ondelete="NO ACTION",
        ),
        _delete_reason_fk("event_types"),
    )

    # ---- actor_types ------------------------------------------------------
    op.create_table(
        "actor_types",
        sa.Column("actor_type_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("actor_type_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_human", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("actor_type_code", name="pk_actor_types"),
        _delete_reason_fk("actor_types"),
    )

    # ---- source_components ------------------------------------------------------
    op.create_table(
        "source_components",
        sa.Column("source_component_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("component_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("component_type_code", mssql.NVARCHAR(64), nullable=True),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column("version_label", mssql.NVARCHAR(64), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "source_component_code", name="pk_source_components"
        ),
        _delete_reason_fk("source_components"),
    )

    # ---- result_codes ------------------------------------------------------
    op.create_table(
        "result_codes",
        sa.Column("result_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("result_name", mssql.NVARCHAR(150), nullable=False),
        sa.Column("description", mssql.NVARCHAR(500), nullable=True),
        sa.Column(
            "is_success", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint("result_code", name="pk_result_codes"),
        _delete_reason_fk("result_codes"),
    )

    # ---- failure_categories ------------------------------------------------------
    op.create_table(
        "failure_categories",
        sa.Column("failure_category_code", mssql.NVARCHAR(64), nullable=False),
        sa.Column("failure_category_name", mssql.NVARCHAR(200), nullable=False),
        sa.Column("description", mssql.NVARCHAR(700), nullable=True),
        sa.Column(
            "is_retryable", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "requires_human_review_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        *_control_columns(),
        sa.PrimaryKeyConstraint(
            "failure_category_code", name="pk_failure_categories"
        ),
        _delete_reason_fk("failure_categories"),
    )


# =====================================================================
# DOWNGRADE
# Purpose:
# Drops the Wave 1 foundation in exact reverse dependency order.
#
# Important Notes:
# - This is a purely structural downgrade (empty tables being dropped),
#   safely reversible because Wave 1 is additive foundation creation
#   with no real data expected to exist in these tables yet. It does
#   not claim to restore any data.
# - Never touches workflow_runs or audit_events.
# =====================================================================
def downgrade() -> None:
    """Drops the Wave 1 foundation tables in reverse dependency order."""
    op.drop_table("failure_categories")
    op.drop_table("result_codes")
    op.drop_table("source_components")
    op.drop_table("actor_types")
    op.drop_table("event_types")
    op.drop_table("event_categories")
    op.drop_table("workflow_actions")
    op.drop_table("workflow_statuses")
    op.drop_table("case_statuses")
    op.drop_table("departments")
    op.drop_table("locations")
    op.drop_table("clients")
    op.drop_table("countries")
    op.drop_table("reasons")
