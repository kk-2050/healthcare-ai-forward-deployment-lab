# File Name: test_wave2_schema.py
# Purpose: Tests the Wave 2 canonical SQLAlchemy schema (structure only) using an in-memory SQLite test double.
# Creation Date: 2026-09-18
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the Wave 2 SQLAlchemy model layer (src/db/models.py)
# added/evolved in Task 21B: the six new tables (document_types,
# workflow_definitions, workflow_definition_steps,
# prior_authorization_cases, case_diagnoses, case_documents) and the
# canonical workflow_runs/audit_events shape. Every test runs against
# an in-memory SQLite engine -- a TEST DOUBLE only, used here to check
# table/column/constraint STRUCTURE, never SQL Server compatibility.
# Real SQL Server compatibility is confirmed only when the Wave 2
# migration is actually executed and validated against a live SQL
# Server instance, which has not happened yet.
#
# Wave 1's 14 tables (reasons, countries, clients, ...) have no
# SQLAlchemy ORM class at all -- they exist only as raw Alembic DDL
# (see migrations/versions/c841e86a8516_...py) -- so this file does not
# and cannot test them via Base.metadata; test_wave2_regression_no_wave1_table_name_collisions
# below only confirms Wave 2's new ORM classes do not accidentally
# reintroduce a Wave 1 table name.

import pytest
from pydantic_core import PydanticUndefined
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect

from src.db.base import Base
from src.db.models import (  # noqa: F401 -- imported so they register on Base.metadata
    AuditEventORM,
    CaseDiagnosisORM,
    CaseDocumentORM,
    DocumentTypeORM,
    PriorAuthorizationCaseORM,
    WorkflowDefinitionORM,
    WorkflowDefinitionStepORM,
    WorkflowRunORM,
)
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot

_WAVE_2_TABLES = {
    "document_types",
    "workflow_definitions",
    "workflow_definition_steps",
    "prior_authorization_cases",
    "case_diagnoses",
    "case_documents",
    "workflow_runs",
    "audit_events",
}

# The 14 tables physically created by the Wave 1 migration -- raw
# Alembic DDL only, no ORM class. Confirmed directly from
# migrations/versions/c841e86a8516_create_wave_1_database_foundation.py.
_WAVE_1_TABLES = {
    "reasons",
    "countries",
    "clients",
    "locations",
    "departments",
    "case_statuses",
    "workflow_statuses",
    "workflow_actions",
    "event_categories",
    "event_types",
    "actor_types",
    "source_components",
    "result_codes",
    "failure_categories",
}


def make_test_engine():
    """Builds a throwaway in-memory SQLite engine and creates every table
    declared on Base -- structural validation only, see module docstring."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


# =====================================================================
# TABLE INVENTORY
# =====================================================================
def test_wave2_metadata_contains_all_expected_tables():
    """Verify Base.metadata creates exactly the 8 Wave 2 tables (6 new
    + canonical workflow_runs/audit_events) -- no more, no less."""
    engine = make_test_engine()
    tables = set(sa_inspect(engine).get_table_names())

    assert tables == _WAVE_2_TABLES


def test_wave2_regression_no_wave1_table_name_collisions():
    """Verify none of the new Wave 2 ORM classes accidentally declare a
    table name already physically owned by the Wave 1 migration."""
    engine = make_test_engine()
    tables = set(sa_inspect(engine).get_table_names())

    assert not (tables & _WAVE_1_TABLES)


# =====================================================================
# PRIMARY KEY VALIDATION
# =====================================================================
@pytest.mark.parametrize(
    "table_name,expected_pk",
    [
        ("document_types", ["document_type_code"]),
        ("workflow_definitions", ["workflow_definition_id"]),
        ("workflow_definition_steps", ["workflow_step_id"]),
        ("prior_authorization_cases", ["case_id"]),
        ("case_diagnoses", ["case_diagnosis_id"]),
        ("case_documents", ["case_document_id"]),
        ("workflow_runs", ["trace_id"]),
        ("audit_events", ["event_id"]),
    ],
)
def test_wave2_primary_keys(table_name, expected_pk):
    """Verify each Wave 2 table's primary key matches the canonical
    data dictionary exactly."""
    engine = make_test_engine()
    pk = sa_inspect(engine).get_pk_constraint(table_name)

    assert pk["constrained_columns"] == expected_pk


# =====================================================================
# FOREIGN KEY VALIDATION
# =====================================================================
# Ordinary/self-referencing FKs this revision creates -- only the ones
# whose target table also has a Wave 2 ORM class (see src/db/models.py
# module docstring's Foreign Key Policy). FKs to Wave 1-only tables
# (e.g. prior_authorization_cases.client_id -> clients) are physical
# in the real database but intentionally have no SQLAlchemy-level
# ForeignKey() here, so they are not exercised by this offline test.
_EXPECTED_FKS = [
    ("workflow_definition_steps", "workflow_definition_id", "workflow_definitions"),
    ("case_diagnoses", "case_id", "prior_authorization_cases"),
    ("case_documents", "case_id", "prior_authorization_cases"),
    ("case_documents", "document_type_code", "document_types"),
    ("workflow_runs", "case_id", "prior_authorization_cases"),
    ("workflow_runs", "workflow_definition_id", "workflow_definitions"),
    ("audit_events", "trace_id", "workflow_runs"),
    ("audit_events", "case_id", "prior_authorization_cases"),
    ("audit_events", "workflow_step_id", "workflow_definition_steps"),
    ("audit_events", "related_event_id", "audit_events"),
]


def test_wave2_foreign_keys():
    """Verify every Wave-2-internal ordinary/self-referencing FK
    (i.e. FKs whose target table also has a Wave 2 ORM class) is
    present with the correct referenced table."""
    engine = make_test_engine()
    inspector = sa_inspect(engine)

    found = []
    missing = []
    for table_name, column, referred_table in _EXPECTED_FKS:
        fks = inspector.get_foreign_keys(table_name)
        match = any(
            column in fk["constrained_columns"] and fk["referred_table"] == referred_table
            for fk in fks
        )
        (found if match else missing).append(f"{table_name}.{column}->{referred_table}")

    assert missing == []
    assert len(found) == len(_EXPECTED_FKS)


# =====================================================================
# BUSINESS-KEY UNIQUE CONSTRAINT VALIDATION
# =====================================================================
def test_wave2_workflow_definitions_unique_constraint():
    """Verify workflow_definitions(workflow_code, version_no) is unique
    -- the business-key identity for a workflow definition."""
    engine = make_test_engine()
    uniques = sa_inspect(engine).get_unique_constraints("workflow_definitions")

    assert any(
        set(u["column_names"]) == {"workflow_code", "version_no"} for u in uniques
    )


def test_wave2_workflow_definition_steps_unique_constraint():
    """Verify workflow_definition_steps(workflow_definition_id, step_code)
    is unique -- a step_code is only unique within its own definition."""
    engine = make_test_engine()
    uniques = sa_inspect(engine).get_unique_constraints("workflow_definition_steps")

    assert any(
        set(u["column_names"]) == {"workflow_definition_id", "step_code"}
        for u in uniques
    )


# =====================================================================
# NULLABLE / NON-NULLABLE CONTRACT
# =====================================================================
@pytest.mark.parametrize(
    "table_name,column,expected_nullable",
    [
        ("workflow_runs", "workflow_definition_id", False),
        ("workflow_runs", "next_action_code", True),
        ("workflow_runs", "human_review_required", False),
        ("workflow_runs", "completed_at_utc", True),
        ("audit_events", "event_type_code", False),
        ("audit_events", "event_category_code", False),
        ("audit_events", "workflow_step_id", True),
        ("audit_events", "actor_identifier", True),
        ("prior_authorization_cases", "client_id", False),
        ("prior_authorization_cases", "department_id", True),
        ("case_documents", "document_type_code", False),
    ],
)
def test_wave2_nullability_contract(table_name, column, expected_nullable):
    """Verify a sample of required vs. optional columns match the
    canonical data dictionary's null_allowed column exactly."""
    engine = make_test_engine()
    columns = {c["name"]: c for c in sa_inspect(engine).get_columns(table_name)}

    assert columns[column]["nullable"] is expected_nullable


# =====================================================================
# TRACE_ID SCHEMA EXPECTATIONS (ADR-007)
# =====================================================================
def test_workflow_run_snapshot_trace_id_has_no_default():
    """Verify WorkflowRunSnapshot never auto-generates trace_id -- per
    ADR-007, trace_id must be supplied by the caller (the future
    orchestration boundary), never fabricated by this model, never a
    SQL Server identity value."""
    field = WorkflowRunSnapshot.model_fields["trace_id"]

    assert field.default is PydanticUndefined
    assert field.default_factory is None


def test_workflow_runs_trace_id_is_primary_key_not_identity():
    """Verify trace_id is a plain string primary key, not a
    database-generated identity/autoincrement column -- application
    (UUID4)-generated identity, per ADR-007. SQLite has no server-side
    "identity" concept to assert against directly; the structural
    guarantee this project relies on is that trace_id's column type is
    a plain string, never an Integer autoincrement column."""
    engine = make_test_engine()
    columns = {c["name"]: c for c in sa_inspect(engine).get_columns("workflow_runs")}

    assert "INTEGER" not in str(columns["trace_id"]["type"]).upper()


# =====================================================================
# WORKFLOW DEFINITION / STEP RELATIONSHIP
# =====================================================================
def test_workflow_definition_steps_belong_to_one_definition():
    """Verify a workflow_definition_steps row can be created against a
    real workflow_definitions row and is retrievable -- confirming the
    relationship compiles and round-trips (structure only, no LangGraph
    involved)."""
    from datetime import datetime, timezone

    from sqlalchemy.orm import sessionmaker

    engine = make_test_engine()
    session = sessionmaker(bind=engine)()
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    session.add(
        WorkflowDefinitionORM(
            workflow_definition_id="SYN-WORKFLOW-DEF-001",
            workflow_code="PRIOR_AUTHORIZATION",
            version_no="1.0",
            workflow_name="Prior Authorization Phase 1",
            effective_from_utc=now,
            created_at_utc=now,
            created_by="SYSTEM",
            updated_at_utc=now,
            updated_by="SYSTEM",
        )
    )
    session.add(
        WorkflowDefinitionStepORM(
            workflow_step_id="SYN-STEP-001",
            workflow_definition_id="SYN-WORKFLOW-DEF-001",
            step_code="FHIR_RETRIEVAL",
            step_name="Retrieve synthetic FHIR-style evidence",
            step_order=20,
            created_at_utc=now,
            created_by="SYSTEM",
            updated_at_utc=now,
            updated_by="SYSTEM",
        )
    )
    session.commit()

    step = session.get(WorkflowDefinitionStepORM, "SYN-STEP-001")
    assert step is not None
    assert step.workflow_definition_id == "SYN-WORKFLOW-DEF-001"
    assert step.step_code == "FHIR_RETRIEVAL"
    session.close()


# =====================================================================
# CANONICAL WORKFLOW_RUNS / AUDIT_EVENTS MODEL SHAPE
# =====================================================================
def test_workflow_run_snapshot_has_23_canonical_fields():
    """Verify WorkflowRunSnapshot exposes exactly the 23 canonical
    workflow_runs columns (data_dictionary.md `workflow_runs`)."""
    assert len(WorkflowRunSnapshot.model_fields) == 23


def test_audit_event_has_19_canonical_fields():
    """Verify AuditEvent exposes exactly the 19 canonical audit_events
    columns (data_dictionary.md `audit_events`)."""
    assert len(AuditEvent.model_fields) == 19


def test_audit_event_category_matches_target_vocabulary():
    """Verify AuditEventCategory matches the resolved target
    event_categories vocabulary (migration_plan.md Section 7.B) -- no
    generic ERROR category, functional-domain categories only."""
    assert {member.value for member in AuditEventCategory} == {
        "WORKFLOW",
        "FHIR",
        "RULE",
        "AI",
        "HUMAN",
        "PERSISTENCE",
    }


# =====================================================================
# LIFECYCLE / CONTROL-FIELD METADATA
# =====================================================================
_STANDARD_CONTROL_FIELDS = {
    "is_deleted",
    "created_at_utc",
    "created_by",
    "updated_at_utc",
    "updated_by",
    "deleted_at_utc",
    "deleted_by",
    "delete_reason_code",
    "delete_reason_text",
}


@pytest.mark.parametrize(
    "table_name",
    [
        "document_types",
        "workflow_definitions",
        "workflow_definition_steps",
        "prior_authorization_cases",
        "case_diagnoses",
        "case_documents",
        "workflow_runs",
    ],
)
def test_wave2_non_audit_tables_have_all_nine_control_fields(table_name):
    """Verify every Wave 2 non-audit table carries all nine standard
    control fields (data_model.md Section 4)."""
    engine = make_test_engine()
    columns = {c["name"] for c in sa_inspect(engine).get_columns(table_name)}

    assert _STANDARD_CONTROL_FIELDS.issubset(columns)


def test_audit_events_is_append_only_with_no_lifecycle_fields():
    """Verify audit_events has NEITHER update nor logical-delete control
    fields -- append-only by design (data_dictionary.md `audit_events`
    table note), unlike every other Wave 2 table."""
    engine = make_test_engine()
    columns = {c["name"] for c in sa_inspect(engine).get_columns("audit_events")}

    forbidden = _STANDARD_CONTROL_FIELDS - {"created_at_utc", "created_by"}
    assert not (forbidden & columns)
    assert {"created_at_utc", "created_by"}.issubset(columns)
