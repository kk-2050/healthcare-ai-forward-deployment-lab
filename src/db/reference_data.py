# File Name: reference_data.py
# Purpose: Loads the stable, approved Phase 1 reference/configuration catalog into SQL Server, idempotently and without overwriting conflicting data.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the one place stable Phase 1 reference/configuration rows are
# defined and loaded -- separate from Alembic schema migrations
# (schema and seed data are separate concerns, per ADR-005's Reference
# Data Policy) and separate from any synthetic business/test fixture
# (a case, a client used only by a test -- see
# tests/test_workflow_orchestrator_integration.py for that).
#
# Every code/value below is copied verbatim from
# docs/database/reference_data.md and docs/database/migration_plan.md
# Section 7.C -- nothing here is invented. Two small, clearly-labeled
# operational choices are not sourced from those documents because
# nothing in them specifies a value: sort_order (case_statuses/
# workflow_statuses -- purely a display-order convenience, matching the
# 10/20/30-spacing convention reference_data.md itself already uses for
# workflow_definition_steps.step_order) and effective_from_utc
# (workflow_definitions -- set to the load time, since no fixed
# effective date is documented).
#
# TABLE ACCESS STRATEGY (read before adding a table here):
# Twelve of the fourteen tables loaded here (reasons, case_statuses,
# workflow_statuses, workflow_actions, event_categories, event_types,
# actor_types, source_components, result_codes, failure_categories,
# human_review_statuses, human_review_outcomes)
# have NO SQLAlchemy ORM class -- only raw Alembic DDL (see
# migrations/versions/c841e86a8516_create_wave_1_database_foundation.py
# and migrations/versions/f2fb22e3a41e_create_human_review_persistence_tables.py,
# and src/db/models.py's Foreign Key Policy docstring, which explains
# why: these reference-master tables were deliberately never given ORM
# classes). This
# loader reads/writes them via parameterized sa.text() statements
# executed through the SAME session/transaction the caller supplies --
# not a second ORM registry, not a second connection. The remaining two
# tables (workflow_definitions, workflow_definition_steps) already have
# real ORM classes (Task 21B) and are loaded through them directly.
#
# TASK 23 PREREQUISITE (do not run before this is satisfied):
# human_review_statuses/human_review_outcomes below require Alembic
# revision f2fb22e3a41e to be applied first -- this loader does not
# check for that (no table in this loader ever has; schema and seed
# data are separate, ordered concerns per ADR-005). Running this
# loader against a database still at b9aba5b07ac8 will raise a raw SQL
# "invalid object name" error for these two tables, not a graceful
# skip -- that is expected, not a bug to work around here.
#
# IDENTIFIER STRATEGY:
# workflow_definition_id/workflow_step_id are application-generated
# surrogate IDs with no fixed value prescribed by the canonical design
# ("exact IDs are generated during seeding" -- reference_data.md
# Section 7). This loader assigns deterministic, human-readable IDs
# derived from each row's business key (e.g. "wfdef_prior_authorization_1_0",
# "wfstep_prior_authorization_1_0_fhir_retrieval") rather than a random
# UUID, so repeated loads are idempotent without needing a separate
# lookup table, and so the IDs are clearly recognizable as prototype
# configuration identifiers, never PHI/PII, well within the 64-character
# column limit.

from dataclasses import dataclass, field
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.db.models import WorkflowDefinitionORM, WorkflowDefinitionStepORM


class ReferenceDataConflictError(Exception):
    """Raised when an existing reference/configuration row's semantic
    fields conflict with its expected Phase 1 definition. The row is
    never overwritten; the whole load is rolled back instead."""


@dataclass
class ReferenceDataLoadReport:
    """What one load_reference_data() call actually did -- which rows
    were newly inserted, and which already matched and were left
    untouched. Never includes a row that was overwritten; this loader
    does not overwrite."""

    inserted: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)


_ACTOR = "SYSTEM"


# =====================================================================
# WORKFLOW DEFINITION / STEP IDENTIFIERS
# =====================================================================
_WORKFLOW_CODE = "PRIOR_AUTHORIZATION"
_WORKFLOW_VERSION_NO = "1.0"


def _deterministic_workflow_definition_id() -> str:
    return f"wfdef_{_WORKFLOW_CODE.lower()}_{_WORKFLOW_VERSION_NO.replace('.', '_')}"


def _deterministic_workflow_step_id(step_code: str) -> str:
    return (
        f"wfstep_{_WORKFLOW_CODE.lower()}_"
        f"{_WORKFLOW_VERSION_NO.replace('.', '_')}_{step_code.lower()}"
    )


# =====================================================================
# RAW-SQL (NON-ORM) TABLE DEFINITIONS
# Purpose:
# Column lists (business/semantic columns only -- control columns are
# added uniformly by the loader) and expected rows for the ten Wave 1
# tables with no ORM class. Sourced from the Wave 1 migration's actual
# column definitions and docs/database/reference_data.md's proposed
# values.
# =====================================================================
_TABLE_COLUMNS: dict[str, list[str]] = {
    "reasons": [
        "reason_code",
        "reason_type_code",
        "reason_name",
        "description",
        "requires_text",
        "is_active",
    ],
    "case_statuses": [
        "case_status_code",
        "case_status_name",
        "description",
        "is_terminal",
        "sort_order",
        "is_active",
    ],
    "workflow_statuses": [
        "workflow_status_code",
        "workflow_status_name",
        "description",
        "is_terminal",
        "requires_human_review",
        "sort_order",
        "is_active",
    ],
    "workflow_actions": [
        "workflow_action_code",
        "workflow_action_name",
        "description",
        "requires_human",
        "is_terminal",
        "is_active",
    ],
    "event_categories": [
        "event_category_code",
        "event_category_name",
        "description",
        "is_active",
    ],
    "event_types": [
        "event_type_code",
        "event_category_code",
        "event_type_name",
        "description",
        "is_active",
    ],
    "actor_types": [
        "actor_type_code",
        "actor_type_name",
        "description",
        "is_human",
        "is_active",
    ],
    "source_components": [
        "source_component_code",
        "component_name",
        "component_type_code",
        "description",
        "version_label",
        "is_active",
    ],
    "result_codes": [
        "result_code",
        "result_name",
        "description",
        "is_success",
        "is_active",
    ],
    "failure_categories": [
        "failure_category_code",
        "failure_category_name",
        "description",
        "is_retryable",
        "requires_human_review_default",
        "is_active",
    ],
    "human_review_statuses": [
        "review_status_code",
        "review_status_name",
        "description",
        "is_terminal",
        "is_active",
    ],
    "human_review_outcomes": [
        "review_outcome_code",
        "review_outcome_name",
        "description",
        "returns_to_workflow",
        "closes_case",
        "is_active",
    ],
}

_TABLE_PK: dict[str, str] = {
    "reasons": "reason_code",
    "case_statuses": "case_status_code",
    "workflow_statuses": "workflow_status_code",
    "workflow_actions": "workflow_action_code",
    "event_categories": "event_category_code",
    "event_types": "event_type_code",
    "actor_types": "actor_type_code",
    "source_components": "source_component_code",
    "result_codes": "result_code",
    "failure_categories": "failure_category_code",
    "human_review_statuses": "review_status_code",
    "human_review_outcomes": "review_outcome_code",
}

# Load order matters: event_categories must exist before event_types
# (event_types.event_category_code is a real FK to it). Dict insertion
# order is what _load_raw_tables() below iterates in.
_TABLE_ROWS: dict[str, list[dict]] = {
    # ---- reasons (docs/database/reference_data.md Section 16) ----
    # The EVIDENCE_MISMATCH, HUMAN_REVIEW, and (Step 23C-2C1) CASE_CLOSE
    # domains are loaded -- CASE_CLOSE is now referenced by implemented
    # code (src/workflow/human_review_service.py's CLOSE_CASE
    # close_reason_code validation), so it is no longer excluded on the
    # "nothing currently uses it" basis that previously applied. The
    # DELETE domain remains documented but not yet referenced by any
    # implemented code path, so it is still not loaded here.
    "reasons": [
        {
            "reason_code": "EVIDENCE_MISMATCH_SERVICE_CODE",
            "reason_type_code": "EVIDENCE_MISMATCH",
            "reason_name": "Service Code Mismatch",
            "description": "Requested service code differs",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "EVIDENCE_MISMATCH_DIAGNOSIS_CODE",
            "reason_type_code": "EVIDENCE_MISMATCH",
            "reason_name": "Diagnosis Code Mismatch",
            "description": "Diagnosis code differs",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "EVIDENCE_DOCUMENT_NOT_FOUND",
            "reason_type_code": "EVIDENCE_MISMATCH",
            "reason_name": "Document Not Found",
            "description": "Required/supporting document not found",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "HUMAN_REVIEW_EVIDENCE_MISMATCH",
            "reason_type_code": "HUMAN_REVIEW",
            "reason_name": "Human Review - Evidence Mismatch",
            "description": "Deterministic evidence mismatch",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "HUMAN_REVIEW_FHIR_FAILURE",
            "reason_type_code": "HUMAN_REVIEW",
            "reason_name": "Human Review - FHIR Failure",
            "description": "FHIR/integration failure",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "HUMAN_REVIEW_AI_FAILURE",
            "reason_type_code": "HUMAN_REVIEW",
            "reason_name": "Human Review - AI Failure",
            "description": "AI failure or invalid structured output",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "HUMAN_REVIEW_AMBIGUITY",
            "reason_type_code": "HUMAN_REVIEW",
            "reason_name": "Human Review - Ambiguity",
            "description": "Material ambiguity requires a human",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION",
            "reason_type_code": "HUMAN_REVIEW",
            "reason_name": "Human Review - Unresolved Missing Information",
            "description": (
                "Required information remained unresolved after the "
                "approved, already-authorized information process, or "
                "could not be obtained within the existing authorized "
                "boundary"
            ),
            "requires_text": False,
            "is_active": True,
        },
        # ---- CASE_CLOSE domain (reference_data.md Section 16) ----
        # Step 23C-2C1: now referenced by implemented code
        # (src/workflow/human_review_service.py's CLOSE_CASE
        # close_reason_code validation). reason_name follows the exact
        # "Domain - Title Case" convention already used for the
        # HUMAN_REVIEW_* rows above (not itself a documented column in
        # reference_data.md's 3-column reasons table, same as for those
        # rows). requires_text is True only for CASE_CLOSE_OTHER,
        # directly derived from its own documented meaning ("Other;
        # explanatory text required") -- not an invented flag.
        {
            "reason_code": "CASE_CLOSE_COMPLETED",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Completed",
            "description": "Normal case processing completed",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "CASE_CLOSE_REQUEST_WITHDRAWN",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Request Withdrawn",
            "description": "Request withdrawn",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "CASE_CLOSE_DUPLICATE",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Duplicate",
            "description": "Duplicate case closed",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "CASE_CLOSE_SUPERSEDED",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Superseded",
            "description": "Superseded by another case",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "CASE_CLOSE_ADMINISTRATIVE",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Administrative",
            "description": "Administrative close",
            "requires_text": False,
            "is_active": True,
        },
        {
            "reason_code": "CASE_CLOSE_OTHER",
            "reason_type_code": "CASE_CLOSE",
            "reason_name": "Case Close - Other",
            "description": "Other; explanatory text required",
            "requires_text": True,
            "is_active": True,
        },
    ],
    # ---- case_statuses (reference_data.md Section 3) ----
    "case_statuses": [
        {
            "case_status_code": "OPEN",
            "case_status_name": "Open",
            "description": "Case exists and may be processed",
            "is_terminal": False,
            "sort_order": 10,
            "is_active": True,
        },
        {
            "case_status_code": "IN_PROGRESS",
            "case_status_name": "In Progress",
            "description": "Active workflow processing",
            "is_terminal": False,
            "sort_order": 20,
            "is_active": True,
        },
        {
            "case_status_code": "PENDING_INFORMATION",
            "case_status_name": "Pending Information",
            "description": "Missing required information/documents",
            "is_terminal": False,
            "sort_order": 30,
            "is_active": True,
        },
        {
            "case_status_code": "HUMAN_REVIEW_REQUIRED",
            "case_status_name": "Human Review Required",
            "description": "Automated processing paused for reviewer",
            "is_terminal": False,
            "sort_order": 40,
            "is_active": True,
        },
        {
            "case_status_code": "CLOSED",
            "case_status_name": "Closed",
            "description": "Business case lifecycle ended",
            "is_terminal": True,
            "sort_order": 50,
            "is_active": True,
        },
    ],
    # ---- workflow_statuses (reference_data.md Section 4) ----
    "workflow_statuses": [
        {
            "workflow_status_code": "PROCESSING",
            "workflow_status_name": "Processing",
            "description": "Automated workflow is actively executing",
            "is_terminal": False,
            "requires_human_review": False,
            "sort_order": 10,
            "is_active": True,
        },
        {
            "workflow_status_code": "HUMAN_REVIEW_REQUIRED",
            "workflow_status_name": "Human Review Required",
            "description": "Automated processing is paused pending human review",
            "is_terminal": False,
            "requires_human_review": True,
            "sort_order": 20,
            "is_active": True,
        },
        {
            "workflow_status_code": "PENDING_RESUME",
            "workflow_status_name": "Pending Resume",
            "description": (
                "A human review outcome requiring return to automated "
                "workflow processing has been recorded; actual "
                "post-review automated continuation has not yet started"
            ),
            "is_terminal": False,
            "requires_human_review": False,
            "sort_order": 25,
            "is_active": True,
        },
        {
            "workflow_status_code": "COMPLETED",
            "workflow_status_name": "Completed",
            "description": (
                "This workflow run completed successfully; use "
                "next_action_code for the business next step"
            ),
            "is_terminal": True,
            "requires_human_review": False,
            "sort_order": 30,
            "is_active": True,
        },
        {
            "workflow_status_code": "FAILED",
            "workflow_status_name": "Failed",
            "description": (
                "Terminal technical/workflow failure where safe automated "
                "continuation or successful creation/routing of a "
                "Human-in-the-Loop review task cannot be established"
            ),
            "is_terminal": True,
            "requires_human_review": True,
            "sort_order": 40,
            "is_active": True,
        },
    ],
    # ---- workflow_actions (reference_data.md Section 5) ----
    "workflow_actions": [
        {
            "workflow_action_code": "CONTINUE_PROCESSING",
            "workflow_action_name": "Continue Processing",
            "description": None,
            "requires_human": False,
            "is_terminal": False,
            "is_active": True,
        },
        {
            "workflow_action_code": "REQUEST_MISSING_INFORMATION",
            "workflow_action_name": "Request Missing Information",
            "description": None,
            "requires_human": False,
            "is_terminal": True,
            "is_active": True,
        },
        {
            "workflow_action_code": "ROUTE_HUMAN_REVIEW",
            "workflow_action_name": "Route to Human Review",
            "description": None,
            "requires_human": True,
            "is_terminal": True,
            "is_active": True,
        },
        {
            "workflow_action_code": "COMPLETE_WORKFLOW",
            "workflow_action_name": "Complete Workflow",
            "description": None,
            "requires_human": False,
            "is_terminal": True,
            "is_active": True,
        },
    ],
    # ---- event_categories (reference_data.md Section 10) ----
    "event_categories": [
        {
            "event_category_code": "WORKFLOW",
            "event_category_name": "Workflow",
            "description": None,
            "is_active": True,
        },
        {
            "event_category_code": "FHIR",
            "event_category_name": "FHIR / Integration",
            "description": None,
            "is_active": True,
        },
        {
            "event_category_code": "RULE",
            "event_category_name": "Deterministic Rule",
            "description": None,
            "is_active": True,
        },
        {
            "event_category_code": "AI",
            "event_category_name": "AI",
            "description": None,
            "is_active": True,
        },
        {
            "event_category_code": "HUMAN",
            "event_category_name": "Human Review",
            "description": None,
            "is_active": True,
        },
        {
            "event_category_code": "PERSISTENCE",
            "event_category_name": "Persistence",
            "description": None,
            "is_active": True,
        },
    ],
    # ---- event_types (reference_data.md Section 11) ----
    "event_types": [
        {
            "event_type_code": "WORKFLOW_STARTED",
            "event_category_code": "WORKFLOW",
            "event_type_name": "Workflow Started",
            "description": "Workflow run started",
            "is_active": True,
        },
        # Step 24B-4A: same-run/same-trace application-level resume
        # continuation actually beginning -- never emitted merely
        # because CONTINUE_WORKFLOW was recorded, PENDING_RESUME exists,
        # or the resume claim succeeded; only once graph invocation
        # genuinely begins. Reuses the existing WORKFLOW category and
        # LANGGRAPH source component -- no new category/component/step.
        {
            "event_type_code": "WORKFLOW_RESUMED",
            "event_category_code": "WORKFLOW",
            "event_type_name": "Workflow Resumed",
            "description": (
                "Automated post-review same-run/same-trace continuation "
                "actually began"
            ),
            "is_active": True,
        },
        {
            "event_type_code": "FHIR_RETRIEVAL_STARTED",
            "event_category_code": "FHIR",
            "event_type_name": "FHIR Retrieval Started",
            "description": "FHIR-style retrieval started",
            "is_active": True,
        },
        {
            "event_type_code": "FHIR_RETRIEVAL_SUCCEEDED",
            "event_category_code": "FHIR",
            "event_type_name": "FHIR Retrieval Succeeded",
            "description": "FHIR-style retrieval succeeded",
            "is_active": True,
        },
        {
            "event_type_code": "FHIR_RETRIEVAL_FAILED",
            "event_category_code": "FHIR",
            "event_type_name": "FHIR Retrieval Failed",
            "description": "FHIR-style retrieval failed",
            "is_active": True,
        },
        {
            "event_type_code": "EVIDENCE_CONSISTENCY_CHECKED",
            "event_category_code": "RULE",
            "event_type_name": "Evidence Consistency Checked",
            "description": "Evidence consistency evaluated",
            "is_active": True,
        },
        {
            "event_type_code": "COMPLETENESS_CHECKED",
            "event_category_code": "RULE",
            "event_type_name": "Completeness Checked",
            "description": "Completeness evaluated",
            "is_active": True,
        },
        {
            "event_type_code": "AI_REQUIRED",
            "event_category_code": "AI",
            "event_type_name": "AI Required",
            "description": "Deterministic routing selected AI",
            "is_active": True,
        },
        {
            "event_type_code": "AI_NOT_REQUIRED",
            "event_category_code": "AI",
            "event_type_name": "AI Not Required",
            "description": "Deterministic routing skipped AI",
            "is_active": True,
        },
        {
            "event_type_code": "AI_ANALYSIS_SUCCEEDED",
            "event_category_code": "AI",
            "event_type_name": "AI Analysis Succeeded",
            "description": "Structured AI analysis succeeded",
            "is_active": True,
        },
        {
            "event_type_code": "AI_ANALYSIS_FAILED",
            "event_category_code": "AI",
            "event_type_name": "AI Analysis Failed",
            "description": "AI analysis failed safely",
            "is_active": True,
        },
        {
            "event_type_code": "HUMAN_REVIEW_REQUIRED",
            "event_category_code": "HUMAN",
            "event_type_name": "Human Review Required",
            "description": "Human review was required",
            "is_active": True,
        },
        {
            "event_type_code": "HUMAN_REVIEW_COMPLETED",
            "event_category_code": "HUMAN",
            "event_type_name": "Human Review Completed",
            "description": "Human review completed",
            "is_active": True,
        },
        {
            "event_type_code": "WORKFLOW_COMPLETED",
            "event_category_code": "WORKFLOW",
            "event_type_name": "Workflow Completed",
            "description": "Workflow reached terminal completion",
            "is_active": True,
        },
        {
            "event_type_code": "WORKFLOW_FAILED",
            "event_category_code": "WORKFLOW",
            "event_type_name": "Workflow Failed",
            "description": "Workflow reached a terminal failure state",
            "is_active": True,
        },
        {
            "event_type_code": "AUDIT_CORRECTION_RECORDED",
            "event_category_code": "PERSISTENCE",
            "event_type_name": "Audit Correction Recorded",
            "description": "New event corrects prior immutable event",
            "is_active": True,
        },
    ],
    # ---- actor_types (reference_data.md Section 12) ----
    "actor_types": [
        {
            "actor_type_code": "SYSTEM",
            "actor_type_name": "System",
            "description": None,
            "is_human": False,
            "is_active": True,
        },
        {
            "actor_type_code": "API_CLIENT",
            "actor_type_name": "API Client",
            "description": None,
            "is_human": False,
            "is_active": True,
        },
        {
            "actor_type_code": "AI_SERVICE",
            "actor_type_name": "AI Service",
            "description": None,
            "is_human": False,
            "is_active": True,
        },
        {
            "actor_type_code": "HUMAN_REVIEWER",
            "actor_type_name": "Human Reviewer",
            "description": None,
            "is_human": True,
            "is_active": True,
        },
    ],
    # ---- source_components (reference_data.md Section 13) ----
    "source_components": [
        {
            "source_component_code": "FASTAPI",
            "component_name": "FastAPI",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "LANGGRAPH",
            "component_name": "LangGraph",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "RULE_ENGINE",
            "component_name": "Deterministic Rule Engine",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "FHIR_STYLE_CLIENT",
            "component_name": "FHIR-style Integration Client",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "AI_SERVICE",
            "component_name": "AI Analysis Service",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "AZURE_OPENAI_ADAPTER",
            "component_name": "Azure OpenAI Adapter",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "STREAMLIT",
            "component_name": "Streamlit UI",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "PERSISTENCE",
            "component_name": "Persistence Layer",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
        {
            "source_component_code": "HUMAN_REVIEW_SERVICE",
            "component_name": "Human Review Service",
            "component_type_code": None,
            "description": None,
            "version_label": None,
            "is_active": True,
        },
    ],
    # ---- result_codes (reference_data.md Section 14) ----
    "result_codes": [
        {
            "result_code": "SUCCESS",
            "result_name": "Success",
            "description": None,
            "is_success": True,
            "is_active": True,
        },
        {
            "result_code": "FAILED",
            "result_name": "Failed",
            "description": None,
            "is_success": False,
            "is_active": True,
        },
        {
            "result_code": "COMPLETE",
            "result_name": "Complete",
            "description": None,
            "is_success": True,
            "is_active": True,
        },
        {
            "result_code": "INCOMPLETE",
            "result_name": "Incomplete",
            "description": None,
            "is_success": False,
            "is_active": True,
        },
        {
            "result_code": "MATCH",
            "result_name": "Match",
            "description": None,
            "is_success": True,
            "is_active": True,
        },
        {
            "result_code": "MISMATCH",
            "result_name": "Mismatch",
            "description": None,
            "is_success": False,
            "is_active": True,
        },
        {
            "result_code": "ROUTED",
            "result_name": "Routed",
            "description": None,
            "is_success": True,
            "is_active": True,
        },
        {
            "result_code": "SKIPPED",
            "result_name": "Skipped",
            "description": None,
            "is_success": True,
            "is_active": True,
        },
    ],
    # ---- failure_categories (reference_data.md Section 15) ----
    "failure_categories": [
        {
            "failure_category_code": "FHIR_HTTP_ERROR",
            "failure_category_name": "FHIR HTTP Error",
            "description": None,
            "is_retryable": True,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "FHIR_MALFORMED_JSON",
            "failure_category_name": "FHIR Malformed JSON",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "FHIR_INVALID_SCHEMA",
            "failure_category_name": "FHIR Invalid Schema",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "FHIR_MISSING_SERVICE_REQUEST",
            "failure_category_name": "FHIR Missing Service Request",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "FHIR_BROKEN_CONDITION_REFERENCE",
            "failure_category_name": "FHIR Broken Condition Reference",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "FHIR_UNSUPPORTED_RESOURCE_TYPE",
            "failure_category_name": "FHIR Unsupported Resource Type",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "AI_PROVIDER_FAILED",
            "failure_category_name": "AI Provider Failed",
            "description": None,
            "is_retryable": True,
            "requires_human_review_default": True,
            "is_active": True,
        },
        {
            "failure_category_code": "AI_OUTPUT_INVALID",
            "failure_category_name": "AI Output Invalid",
            "description": None,
            "is_retryable": False,
            "requires_human_review_default": True,
            "is_active": True,
        },
    ],
    # ---- human_review_statuses (reference_data.md Section 17) ----
    # Requires Alembic revision f2fb22e3a41e -- see TASK 23 PREREQUISITE
    # note at the top of this file.
    "human_review_statuses": [
        {
            "review_status_code": "REQUESTED",
            "review_status_name": "Requested",
            "description": None,
            "is_terminal": False,
            "is_active": True,
        },
        {
            "review_status_code": "IN_PROGRESS",
            "review_status_name": "In Progress",
            "description": None,
            "is_terminal": False,
            "is_active": True,
        },
        {
            "review_status_code": "COMPLETED",
            "review_status_name": "Completed",
            "description": None,
            "is_terminal": True,
            "is_active": True,
        },
        {
            "review_status_code": "CANCELLED",
            "review_status_name": "Cancelled",
            "description": None,
            "is_terminal": True,
            "is_active": True,
        },
    ],
    # ---- human_review_outcomes (reference_data.md Section 18) ----
    # "No autonomous clinical approval/denial outcome is defined" --
    # reference_data.md Section 18's own note. Requires f2fb22e3a41e.
    "human_review_outcomes": [
        {
            "review_outcome_code": "CONTINUE_WORKFLOW",
            "review_outcome_name": "Continue Workflow",
            "description": None,
            "returns_to_workflow": True,
            "closes_case": False,
            "is_active": True,
        },
        {
            "review_outcome_code": "REQUEST_MORE_INFORMATION",
            "review_outcome_name": "Request More Information",
            "description": None,
            "returns_to_workflow": False,
            "closes_case": False,
            "is_active": True,
        },
        {
            "review_outcome_code": "ESCALATE",
            "review_outcome_name": "Escalate",
            "description": None,
            "returns_to_workflow": False,
            "closes_case": False,
            "is_active": True,
        },
        {
            "review_outcome_code": "CLOSE_CASE",
            "review_outcome_name": "Close Case",
            "description": None,
            "returns_to_workflow": False,
            "closes_case": True,
            "is_active": True,
        },
    ],
}

# ---- workflow_definition_steps (reference_data.md Section 7) ----
# source_component_code is not prescribed per-step by reference_data.md
# (the field is nullable there); the values below reuse exactly the
# component src/workflow/orchestrator.py's own audit events already
# attribute to that step's activity -- not a new, separately-invented
# assignment. CASE_VALIDATION (no orchestrator event exists for it) is
# assigned FASTAPI, matching requirements.md FR-2 (inbound validation
# happens at the API boundary).
_WORKFLOW_DEFINITION_STEPS = [
    {"step_code": "CASE_VALIDATION", "step_order": 10, "is_optional": False,
     "step_name": "Pydantic/schema validation", "source_component_code": "FASTAPI"},
    {"step_code": "FHIR_RETRIEVAL", "step_order": 20, "is_optional": False,
     "step_name": "Retrieve synthetic FHIR-style evidence",
     "source_component_code": "FHIR_STYLE_CLIENT"},
    {"step_code": "EVIDENCE_CONSISTENCY", "step_order": 30, "is_optional": False,
     "step_name": "Compare case vs. retrieved evidence",
     "source_component_code": "RULE_ENGINE"},
    {"step_code": "COMPLETENESS_CHECK", "step_order": 40, "is_optional": False,
     "step_name": "Deterministic required-information check",
     "source_component_code": "RULE_ENGINE"},
    # Step 23C-5C (ADR-008): the Stage 1 missing-information disposition,
    # reached only when COMPLETENESS_CHECK finds required information
    # missing -- distinct from that check itself and from HUMAN_REVIEW
    # (this is explicitly not a Human Review escalation). step_order=45
    # inserted between the existing 40/50 values without renumbering any
    # already-loaded row, following the same "multiples of ten leave
    # room to insert" convention already used throughout this table.
    {"step_code": "REQUEST_MISSING_INFORMATION", "step_order": 45, "is_optional": True,
     "step_name": "Stage 1 deterministic missing-information disposition",
     "source_component_code": "LANGGRAPH"},
    {"step_code": "AI_ROUTING", "step_order": 50, "is_optional": False,
     "step_name": "Decide whether AI is needed", "source_component_code": "RULE_ENGINE"},
    {"step_code": "AI_ANALYSIS", "step_order": 60, "is_optional": True,
     "step_name": "Structured AI analysis when required",
     "source_component_code": "AI_SERVICE"},
    {"step_code": "HUMAN_REVIEW", "step_order": 70, "is_optional": True,
     "step_name": "Human-in-the-loop path", "source_component_code": "LANGGRAPH"},
    {"step_code": "COMPLETE", "step_order": 80, "is_optional": False,
     "step_name": "Terminal workflow completion", "source_component_code": "LANGGRAPH"},
]


def _normalize(value):
    """Normalizes a value for semantic-field comparison -- SQL Server
    BIT columns may round-trip as bool or int depending on driver, and
    a trailing/leading-whitespace difference should not itself count as
    a conflict for this prototype's purposes."""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return value.strip()
    return value


def _load_raw_table(
    session: Session,
    table_name: str,
    rows: list[dict],
    report: ReferenceDataLoadReport,
    now: datetime,
) -> None:
    pk_column = _TABLE_PK[table_name]
    columns = _TABLE_COLUMNS[table_name]

    for row in rows:
        existing = (
            session.execute(
                sa.text(
                    f"SELECT {', '.join(columns)} FROM {table_name} "
                    f"WHERE {pk_column} = :pk"
                ),
                {"pk": row[pk_column]},
            )
            .mappings()
            .first()
        )

        if existing is None:
            insert_columns = columns + [
                "created_at_utc",
                "created_by",
                "updated_at_utc",
                "updated_by",
                "is_deleted",
            ]
            params = {
                **row,
                "created_at_utc": now,
                "created_by": _ACTOR,
                "updated_at_utc": now,
                "updated_by": _ACTOR,
                "is_deleted": False,
            }
            placeholders = ", ".join(f":{c}" for c in insert_columns)
            session.execute(
                sa.text(
                    f"INSERT INTO {table_name} ({', '.join(insert_columns)}) "
                    f"VALUES ({placeholders})"
                ),
                params,
            )
            report.inserted.append(f"{table_name}:{row[pk_column]}")
            continue

        mismatches = {
            column: (existing[column], row[column])
            for column in columns
            if column != pk_column
            and _normalize(existing[column]) != _normalize(row[column])
        }
        if mismatches:
            raise ReferenceDataConflictError(
                f"{table_name}.{row[pk_column]} conflicts with its expected "
                f"Phase 1 definition: {mismatches}"
            )
        report.already_present.append(f"{table_name}:{row[pk_column]}")


def _load_workflow_definition(
    session: Session, now: datetime, report: ReferenceDataLoadReport
) -> str:
    workflow_definition_id = _deterministic_workflow_definition_id()
    expected = {
        "workflow_code": _WORKFLOW_CODE,
        "version_no": _WORKFLOW_VERSION_NO,
        "workflow_name": "Prior Authorization Phase 1",
        "description": None,
        "is_active": True,
    }

    existing = session.get(WorkflowDefinitionORM, workflow_definition_id)
    if existing is None:
        session.add(
            WorkflowDefinitionORM(
                workflow_definition_id=workflow_definition_id,
                effective_from_utc=now,
                effective_to_utc=None,
                created_at_utc=now,
                created_by=_ACTOR,
                updated_at_utc=now,
                updated_by=_ACTOR,
                is_deleted=False,
                **expected,
            )
        )
        report.inserted.append(f"workflow_definitions:{workflow_definition_id}")
        return workflow_definition_id

    actual = {key: _normalize(getattr(existing, key)) for key in expected}
    normalized_expected = {key: _normalize(value) for key, value in expected.items()}
    if actual != normalized_expected:
        raise ReferenceDataConflictError(
            f"workflow_definitions:{workflow_definition_id} conflicts with its "
            f"expected Phase 1 definition: expected {normalized_expected}, "
            f"found {actual}"
        )
    report.already_present.append(f"workflow_definitions:{workflow_definition_id}")
    return workflow_definition_id


def _load_workflow_definition_steps(
    session: Session,
    workflow_definition_id: str,
    now: datetime,
    report: ReferenceDataLoadReport,
) -> dict[str, str]:
    """Loads the complete 9-step Phase 1 workflow definition (Step
    23C-5C added REQUEST_MISSING_INFORMATION) and returns the resulting
    step_code -> workflow_step_id mapping, ready to pass to
    run_prior_authorization_workflow()'s step_code_to_workflow_step_id
    parameter."""
    step_code_to_id: dict[str, str] = {}

    for step in _WORKFLOW_DEFINITION_STEPS:
        step_code = step["step_code"]
        workflow_step_id = _deterministic_workflow_step_id(step_code)
        step_code_to_id[step_code] = workflow_step_id

        expected = {
            "workflow_definition_id": workflow_definition_id,
            "step_code": step_code,
            "step_name": step["step_name"],
            "step_order": step["step_order"],
            "source_component_code": step["source_component_code"],
            "is_optional": step["is_optional"],
            "is_active": True,
        }

        existing = session.get(WorkflowDefinitionStepORM, workflow_step_id)
        if existing is None:
            session.add(
                WorkflowDefinitionStepORM(
                    workflow_step_id=workflow_step_id,
                    created_at_utc=now,
                    created_by=_ACTOR,
                    updated_at_utc=now,
                    updated_by=_ACTOR,
                    is_deleted=False,
                    **expected,
                )
            )
            report.inserted.append(f"workflow_definition_steps:{workflow_step_id}")
            continue

        actual = {key: _normalize(getattr(existing, key)) for key in expected}
        normalized_expected = {key: _normalize(value) for key, value in expected.items()}
        if actual != normalized_expected:
            raise ReferenceDataConflictError(
                f"workflow_definition_steps:{workflow_step_id} conflicts with "
                f"its expected Phase 1 definition: expected "
                f"{normalized_expected}, found {actual}"
            )
        report.already_present.append(f"workflow_definition_steps:{workflow_step_id}")

    return step_code_to_id


# =====================================================================
# PUBLIC ENTRY POINT
# Purpose:
# Loads the complete stable Phase 1 reference/configuration catalog
# into the given session's transaction: reasons (EVIDENCE_MISMATCH/
# HUMAN_REVIEW/CASE_CLOSE domains -- Step 23C-2C1 added CASE_CLOSE; the
# DELETE domain remains excluded, not yet referenced by any implemented
# code path), case_statuses, workflow_statuses, workflow_actions,
# event_categories, event_types, actor_types, source_components,
# result_codes, failure_categories, human_review_statuses,
# human_review_outcomes (Task 23 -- requires Alembic revision
# f2fb22e3a41e to already be applied), workflow_definitions, and the
# complete 9-step workflow_definition_steps definition (Step 23C-5C
# added REQUEST_MISSING_INFORMATION).
#
# Why a Session parameter, not a connection string:
# Keeping connection/engine creation entirely out of this function
# (see _run_from_cli() below for the one place that builds one, reusing
# the project's existing secure configuration chain) is what makes this
# function unit-testable against an isolated SQLite session, with no
# real SQL Server required.
#
# Important Notes:
# - Idempotent: re-running against a database that already has these
#   exact rows makes no changes and returns them all as
#   already_present.
# - Never overwrites: a row that exists but does not match its
#   expected definition raises ReferenceDataConflictError and rolls
#   back the ENTIRE load -- not just that one row.
# - One explicit transaction: every row in this call commits together,
#   or none do.
# - Loads NO client/department/location/case row, and NO document_types
#   row -- those are synthetic business/test-fixture data or not yet
#   required by any implemented workflow path; see
#   tests/test_workflow_orchestrator_integration.py for the separate,
#   explicitly-distinct fixture that creates them.
# =====================================================================
def load_reference_data(session: Session) -> ReferenceDataLoadReport:
    """
    Loads the complete stable Phase 1 reference/configuration catalog
    into the given session, idempotently. Raises
    ReferenceDataConflictError (and rolls back) if any existing row
    conflicts with its expected definition.
    """
    now = datetime.now(timezone.utc)
    report = ReferenceDataLoadReport()

    try:
        for table_name, rows in _TABLE_ROWS.items():
            _load_raw_table(session, table_name, rows, report, now)

        workflow_definition_id = _load_workflow_definition(session, now, report)
        _load_workflow_definition_steps(session, workflow_definition_id, now, report)

        session.commit()
        return report
    except Exception:
        session.rollback()
        raise


def resolve_step_code_to_workflow_step_id(session: Session) -> dict[str, str]:
    """
    Reads back the already-loaded workflow_definition_steps rows and
    returns the step_code -> workflow_step_id mapping, for callers that
    need it without having just run load_reference_data() in the same
    call (e.g. a test that loaded reference data in an earlier step).
    """
    workflow_definition_id = _deterministic_workflow_definition_id()
    rows = (
        session.query(WorkflowDefinitionStepORM)
        .filter(
            WorkflowDefinitionStepORM.workflow_definition_id == workflow_definition_id
        )
        .all()
    )
    return {row.step_code: row.workflow_step_id for row in rows}


def workflow_definition_id() -> str:
    """The deterministic workflow_definition_id this loader uses for
    the Phase 1 PRIOR_AUTHORIZATION/1.0 workflow definition."""
    return _deterministic_workflow_definition_id()


# =====================================================================
# MINIMAL CLI ENTRY POINT
# Purpose:
# Lets an operator run the loader locally against real SQL Server,
# reusing the exact existing secure configuration chain
# (load_dotenv -> load_database_settings -> create_sql_server_engine) --
# never a second connection-string implementation.
# =====================================================================
def _run_from_cli() -> None:  # pragma: no cover - exercised manually, not by pytest
    from dotenv import load_dotenv
    from sqlalchemy.orm import sessionmaker

    from src.config.database import load_database_settings
    from src.db.engine import create_sql_server_engine

    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    session = sessionmaker(bind=engine)()

    try:
        report = load_reference_data(session)
        print(f"inserted: {len(report.inserted)}")
        for key in report.inserted:
            print(f"  + {key}")
        print(f"already_present: {len(report.already_present)}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    _run_from_cli()
