# File Name: test_human_review_schema.py
# Purpose: Tests the Task 23 HumanReviewORM SQLAlchemy schema (structure only) using an in-memory SQLite test double.
# Creation Date: 2026-09-22
# Author: K.Kashiwagi
#
# Module Explanation:
# This file protects the approved Task 23 HumanReviewORM model
# (src/db/models.py) -- the same in-memory-SQLite, structure-only
# testing style already used by tests/test_wave2_schema.py, kept as a
# separate file because human_reviews is a Wave 4 table pulled forward
# for Task 23, never a Wave 2 table (see the Task 23 migration's own
# docstring on the Wave-pull-forward precedent) -- mislabeling it as
# Wave 2 would be exactly the kind of Wave-boundary inaccuracy this
# project has been careful to avoid throughout.
#
# Like tests/test_wave2_schema.py, this file builds its in-memory
# engine from an explicit `tables=[...]` list, not an unrestricted
# Base.metadata.create_all(engine) -- Base is a single registry shared
# by every ORM class in src/db/models.py, so an unrestricted call would
# reflect whatever else is defined there, not just the tables this file
# actually needs.
#
# Real SQL Server compatibility is confirmed only when the Task 23
# migration (f2fb22e3a41e) is actually applied and validated against a
# live SQL Server instance, which has not happened yet.

from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect

from src.db.base import Base
from src.db.models import (  # noqa: F401 -- imported so they register on Base.metadata
    HumanReviewORM,
    PriorAuthorizationCaseORM,
    WorkflowDefinitionORM,
    WorkflowRunORM,
)

# The minimal ORM-mapped dependency chain HumanReviewORM's own
# ForeignKey() declarations need to materialize in an isolated engine:
# HumanReviewORM -> workflow_runs, prior_authorization_cases;
# WorkflowRunORM (in turn) -> workflow_definitions, prior_authorization_cases.
# Confirmed directly from src/db/models.py -- not assumed.
_HUMAN_REVIEW_DEPENDENCY_CLASSES = (
    WorkflowDefinitionORM,
    PriorAuthorizationCaseORM,
    WorkflowRunORM,
    HumanReviewORM,
)


def make_human_review_test_engine():
    """Builds a throwaway in-memory SQLite engine containing only
    HumanReviewORM and the ORM-mapped tables its own declared
    ForeignKey() columns require -- not the full shared Base.metadata
    (see module docstring and tests/test_wave2_schema.py's own
    make_test_engine() for why an unrestricted create_all() would be
    wrong here)."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[cls.__table__ for cls in _HUMAN_REVIEW_DEPENDENCY_CLASSES]
    )
    return engine


# =====================================================================
# MODEL IDENTITY
# =====================================================================
def test_human_review_orm_tablename_is_human_reviews():
    """Verify HumanReviewORM declares the exact canonical table name
    used by the Task 23 migration (f2fb22e3a41e)."""
    assert HumanReviewORM.__tablename__ == "human_reviews"


def test_human_review_orm_is_registered_on_base_metadata():
    """Verify HumanReviewORM's table is registered on the shared Base
    under the exact name "human_reviews", and that it is the same
    table object the model itself declares -- not a stale/duplicate
    registration."""
    assert "human_reviews" in Base.metadata.tables
    assert Base.metadata.tables["human_reviews"] is HumanReviewORM.__table__


# =====================================================================
# TABLE CREATION
# =====================================================================
def test_human_reviews_table_is_created_in_isolated_engine():
    """Verify human_reviews physically creates in an engine restricted
    to HumanReviewORM's own ORM-mapped dependency chain -- proving the
    model is self-consistent without relying on the full, shared
    Base.metadata (e.g. Wave 2 or any other wave's tables)."""
    engine = make_human_review_test_engine()
    tables = set(sa_inspect(engine).get_table_names())

    assert "human_reviews" in tables
    assert tables == {
        "workflow_definitions",
        "prior_authorization_cases",
        "workflow_runs",
        "human_reviews",
    }


# =====================================================================
# PRIMARY KEY
# =====================================================================
def test_human_reviews_primary_key():
    """Verify human_reviews' primary key matches the Task 23 migration
    and canonical model exactly."""
    engine = make_human_review_test_engine()
    pk = sa_inspect(engine).get_pk_constraint("human_reviews")

    assert pk["constrained_columns"] == ["review_id"]


# =====================================================================
# IMPORTANT COLUMNS
# Purpose:
# Verifies the columns HumanReviewRecord/human_review_repository.py
# actually depend on are present with the approved nullability --
# read directly from src/db/models.py's HumanReviewORM, not assumed
# from this test's own expectations.
# =====================================================================
def test_human_reviews_has_the_approved_important_columns():
    """Verify the approved HumanReviewORM columns exist with the
    correct nullability, matching src/db/models.py exactly."""
    engine = make_human_review_test_engine()
    columns = {c["name"]: c for c in sa_inspect(engine).get_columns("human_reviews")}

    expected_not_nullable = {
        "review_id",
        "trace_id",
        "case_id",
        "review_status_code",
        "reason_code",
        "requested_at_utc",
        "source_component_code",
        "created_at_utc",
        "created_by",
        "updated_at_utc",
        "updated_by",
        "is_deleted",
    }
    expected_nullable = {
        "review_outcome_code",
        "assigned_department_id",
        "assigned_location_id",
        "started_at_utc",
        "completed_at_utc",
        "reviewer_actor_type_code",
        "reviewer_reference",
        "review_note_text",
        "metadata_json",
        "deleted_at_utc",
        "deleted_by",
        "delete_reason_code",
        "delete_reason_text",
    }

    assert expected_not_nullable <= columns.keys()
    assert expected_nullable <= columns.keys()
    for name in expected_not_nullable:
        assert columns[name]["nullable"] is False, name
    for name in expected_nullable:
        assert columns[name]["nullable"] is True, name

    # review_status_code and review_outcome_code are never an
    # approval/denial value -- see HumanReviewOutcome
    # (src/models/human_review.py) and the model's own module
    # docstring. This is schema coverage only; it does not assert
    # business logic, only that no such column exists.
    assert not ({"approval", "denial", "medical_necessity"} & columns.keys())


# =====================================================================
# FOREIGN KEYS
# Purpose:
# Distinguishes the database migration's physical FKs (9 total, per
# f2fb22e3a41e -- to workflow_runs, prior_authorization_cases,
# human_review_statuses, human_review_outcomes, reasons (x2, including
# delete_reason_code), departments, locations, actor_types,
# source_components) from the ORM-declared FKs, which the project's
# Foreign Key Policy (src/db/models.py module docstring) intentionally
# limits to targets that also have an ORM class in this Base's
# metadata. Only trace_id and case_id qualify -- confirmed directly by
# reading HumanReviewORM, not assumed.
# =====================================================================
def test_human_reviews_orm_declared_foreign_keys():
    """Verify HumanReviewORM declares real ForeignKey() constraints
    only for trace_id -> workflow_runs and case_id ->
    prior_authorization_cases -- the two targets that also have an ORM
    class in this Base's metadata, per the project's Foreign Key
    Policy."""
    engine = make_human_review_test_engine()
    fks = sa_inspect(engine).get_foreign_keys("human_reviews")

    resolved = {
        (tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in fks
    }

    assert resolved == {
        (("trace_id",), "workflow_runs"),
        (("case_id",), "prior_authorization_cases"),
    }


def test_human_reviews_reference_master_columns_have_no_orm_fk():
    """Verify review_status_code/review_outcome_code/reason_code/
    assigned_department_id/assigned_location_id/reviewer_actor_type_code/
    source_component_code -- every column whose target is a Wave 1
    raw-DDL table or a no-ORM-class reference master
    (human_review_statuses/human_review_outcomes) -- correctly has NO
    ORM-declared ForeignKey(), per the Foreign Key Policy. The Task 23
    migration still enforces these physically in real SQL Server; this
    test only confirms the ORM layer's intentional, documented
    limitation, not the full physical schema (which requires
    f2fb22e3a41e to be applied to be verified for real)."""
    engine = make_human_review_test_engine()
    fks = sa_inspect(engine).get_foreign_keys("human_reviews")
    fk_columns = {column for fk in fks for column in fk["constrained_columns"]}

    no_orm_fk_columns = {
        "review_status_code",
        "review_outcome_code",
        "reason_code",
        "assigned_department_id",
        "assigned_location_id",
        "reviewer_actor_type_code",
        "source_component_code",
    }

    assert not (no_orm_fk_columns & fk_columns)


# =====================================================================
# HUMAN REVIEW COMPLETION INVARIANT
# Purpose:
# The same-row CHECK constraint synchronizing completed_at_utc/
# review_outcome_code nullability is explicitly Wave 6 relational
# hardening, deferred by the Task 23 migration's own docstring -- it
# does not exist yet, at either the ORM or the physical-migration
# level. This test asserts that absence is the current, correct,
# documented state, rather than silently assuming or inventing the
# constraint.
# =====================================================================
def test_human_reviews_has_no_completion_check_constraint_yet():
    """Verify no CHECK constraint exists yet linking completed_at_utc
    and review_outcome_code -- confirmed deferred to Wave 6 by the
    Task 23 migration's own docstring, not yet implemented at the ORM
    or physical-schema level."""
    engine = make_human_review_test_engine()
    checks = sa_inspect(engine).get_check_constraints("human_reviews")

    assert checks == []
