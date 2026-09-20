# File Name: orchestrator.py
# Purpose: Implements the application orchestration boundary that wires the LangGraph prior-authorization workflow to canonical SQL persistence.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the one place in the project that: generates a trace_id,
# invokes the LangGraph workflow, and persists the run's lifecycle
# (workflow_runs) and meaningful activity (audit_events) through the
# existing AuditRepository. See docs/decisions/ADR-007 for the
# identity/traceability rules this module implements.
#
# Scope boundary (Task 22): this module does NOT implement Human-in-the-
# Loop resume, a reviewer decision endpoint, or workflow_step_id
# resolution against real workflow_definition_steps rows (none exist
# yet -- reference-data loading remains a separate, OPEN decision). It
# leaves the same trace_id/run identity available so a future task can
# resume a HUMAN_REVIEW_REQUIRED run.

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.ai.contracts import AIAnalysisFailureType
from src.ai.provider import AIAnalysisProvider
from src.db.repository import AuditRepository
from src.integrations.fhir_client import FHIRStyleClient
from src.integrations.fhir_models import FHIRIntegrationFailureType
from src.models.ai import AIProcessingRequirements
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.evidence import EvidenceMismatchReason
from src.models.rules import CompletenessRequirements
from src.workflow.graph import build_case_workflow_graph
from src.workflow.state import CaseWorkflowState, WorkflowStatus
from src.workflow.step_mapping import (
    STEP_CODE_AI_ANALYSIS,
    STEP_CODE_AI_ROUTING,
    STEP_CODE_COMPLETE,
    STEP_CODE_COMPLETENESS_CHECK,
    STEP_CODE_EVIDENCE_CONSISTENCY,
    STEP_CODE_FHIR_RETRIEVAL,
    STEP_CODE_HUMAN_REVIEW,
)

_SCHEMA_VERSION = "1"

# =====================================================================
# CODE-TRANSLATION TABLES
# Purpose:
# Maps Python enum values already used elsewhere in this project onto
# the exact reference-data codes documented in
# docs/database/reference_data.md and docs/database/migration_plan.md
# Section 7.C -- every value here is copied from those already-approved
# sources, none invented here.
# =====================================================================
_WORKFLOW_STATUS_TO_CODE: dict[WorkflowStatus, str] = {
    WorkflowStatus.PROCESSING: "PROCESSING",
    WorkflowStatus.HUMAN_REVIEW_REQUIRED: "HUMAN_REVIEW_REQUIRED",
    WorkflowStatus.COMPLETE: "COMPLETED",
    # AI_ANALYSIS_COMPLETE is not itself a workflow_status_code (see
    # reference_data.md Section 4); the run's canonical status is
    # COMPLETED, with the AI-assisted path distinguished via audit
    # events, not via a second terminal status.
    WorkflowStatus.AI_ANALYSIS_COMPLETE: "COMPLETED",
    # AI_ANALYSIS_REQUIRED is a transient in-graph marker, never the
    # final state graph.invoke() returns -- mapped defensively rather
    # than left to crash if that assumption is ever violated.
    WorkflowStatus.AI_ANALYSIS_REQUIRED: "PROCESSING",
}

_TERMINAL_WORKFLOW_STATUS_CODES = {"COMPLETED", "FAILED"}

_FHIR_FAILURE_TO_FAILURE_CATEGORY_CODE: dict[FHIRIntegrationFailureType, str] = {
    FHIRIntegrationFailureType.HTTP_ERROR: "FHIR_HTTP_ERROR",
    FHIRIntegrationFailureType.MALFORMED_JSON: "FHIR_MALFORMED_JSON",
    FHIRIntegrationFailureType.INVALID_SCHEMA: "FHIR_INVALID_SCHEMA",
    FHIRIntegrationFailureType.UNSUPPORTED_RESOURCE_TYPE: "FHIR_UNSUPPORTED_RESOURCE_TYPE",
    FHIRIntegrationFailureType.MISSING_SERVICE_REQUEST: "FHIR_MISSING_SERVICE_REQUEST",
    FHIRIntegrationFailureType.BROKEN_CONDITION_REFERENCE: "FHIR_BROKEN_CONDITION_REFERENCE",
}

_AI_FAILURE_TO_FAILURE_CATEGORY_CODE: dict[AIAnalysisFailureType, str] = {
    AIAnalysisFailureType.PROVIDER_FAILED: "AI_PROVIDER_FAILED",
    AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED: "AI_OUTPUT_INVALID",
}

_EVIDENCE_MISMATCH_TO_REASON_CODE: dict[EvidenceMismatchReason, str] = {
    EvidenceMismatchReason.SERVICE_CODE_MISMATCH: "EVIDENCE_MISMATCH_SERVICE_CODE",
    EvidenceMismatchReason.DIAGNOSIS_CODE_MISMATCH: "EVIDENCE_MISMATCH_DIAGNOSIS_CODE",
    EvidenceMismatchReason.DOCUMENTATION_NOT_FOUND: "EVIDENCE_DOCUMENT_NOT_FOUND",
}


# =====================================================================
# ORCHESTRATOR FAILURE
# Purpose:
# Raised when the workflow itself fails in a way no existing safe
# fallback (FHIR/AI routing to human review) already covers -- an
# unhandled exception during graph execution.
#
# Why:
# The project rule (Section 10) is that a persistence failure, or an
# unhandled workflow failure, must never be hidden or reported as if
# the run completed/was saved successfully. This exception is how that
# surfaces to the caller.
# =====================================================================
class OrchestratorError(Exception):
    """Raised when workflow execution or its persistence fails unsafely."""


@dataclass
class WorkflowRunResult:
    """The outcome of one orchestrated workflow run: its identity, the
    final LangGraph state, and the audit events persisted for it."""

    trace_id: str
    final_state: CaseWorkflowState
    audit_events: list[AuditEvent] = field(default_factory=list)


# =====================================================================
# ORCHESTRATION ENTRY POINT
# Purpose:
# Runs one case through the existing LangGraph workflow and persists
# its lifecycle to the canonical workflow_runs/audit_events tables.
#
# Why:
# This is the single call site responsible for trace_id identity (per
# ADR-007): generated once, here, immediately before graph.invoke(),
# threaded through state, and used for every persistence write for this
# run. No node, no repository method, and no audit event generates its
# own trace_id.
#
# Important Notes:
# - workflow_definition_id, initiated_by_component_code, and created_by
#   must reference rows that already exist in workflow_definitions/
#   source_components -- this function does not create or validate
#   reference data (see docs/database/migration_plan.md Section 16,
#   still OPEN). Callers running against real SQL Server are
#   responsible for supplying values that exist there; offline tests
#   supply synthetic values freely since SQLite does not enforce these
#   FKs.
# - step_code_to_workflow_step_id, if supplied, resolves a stable
#   step_code (src/workflow/step_mapping.py) to the real
#   workflow_definition_steps.workflow_step_id surrogate ID. No
#   workflow_definition_steps rows exist yet in real SQL Server, so by
#   default every audit event's workflow_step_id is None -- this is a
#   known, deliberate limitation until reference-data loading is
#   resolved, not a bug.
# - This function creates the workflow_runs row before invoking the
#   graph (workflow_status_code=PROCESSING), then updates it once with
#   the final outcome -- it never leaves a case with no row at all, and
#   never silently continues if a persistence write fails.
# - HUMAN_REVIEW_REQUIRED is a pause, not completion: completed_at_utc
#   stays None for it (workflow_statuses.HUMAN_REVIEW_REQUIRED.is_terminal
#   = 0), so the same trace_id remains available for a future resume
#   (Task 23). completed_at_utc is set only for COMPLETED/FAILED.
# =====================================================================
def run_prior_authorization_workflow(
    case: PriorAuthorizationCase,
    completeness_requirements: CompletenessRequirements,
    ai_processing_requirements: AIProcessingRequirements,
    ai_provider: AIAnalysisProvider,
    fhir_client: FHIRStyleClient,
    repository: AuditRepository,
    *,
    workflow_definition_id: str,
    initiated_by_component_code: str = "LANGGRAPH",
    created_by: str = "SYSTEM",
    step_code_to_workflow_step_id: dict[str, str] | None = None,
) -> WorkflowRunResult:
    """
    Runs one case through the LangGraph workflow and persists its
    lifecycle. Returns the run's identity, final state, and the audit
    events written for it. Raises OrchestratorError if graph execution
    fails unsafely; a PersistenceError from the repository is never
    caught here, so a failed write always surfaces to the caller.
    """
    trace_id = str(uuid.uuid4())
    started_at_utc = datetime.now(timezone.utc)
    step_code_to_workflow_step_id = step_code_to_workflow_step_id or {}

    initial_state: CaseWorkflowState = {
        "trace_id": trace_id,
        "case": case,
        "fhir_integration_outcome": None,
        "evidence_consistency_result": None,
        "completeness_requirements": completeness_requirements,
        "completeness_result": None,
        "ai_processing_requirements": ai_processing_requirements,
        "ai_routing_result": None,
        "ai_analysis_outcome": None,
        "workflow_status": WorkflowStatus.PROCESSING,
        "human_review_required": False,
        "processing_steps": [],
    }

    # Create the run at orchestration start (Section 7): a PROCESSING
    # row exists before the graph ever runs, so an unexpected crash
    # still leaves an honest, auditable record rather than nothing.
    repository.save_workflow_run(
        WorkflowRunSnapshot(
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=workflow_definition_id,
            workflow_status_code="PROCESSING",
            human_review_required=False,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_at_utc=started_at_utc,
            created_by=created_by,
            updated_at_utc=started_at_utc,
            updated_by=created_by,
        )
    )
    started_event = _make_event(
        trace_id=trace_id,
        case_id=case.case_id,
        event_type_code="WORKFLOW_STARTED",
        event_category_code=AuditEventCategory.WORKFLOW,
        source_component_code=initiated_by_component_code,
        result_code="SUCCESS",
        occurred_at_utc=started_at_utc,
        created_by=created_by,
    )
    repository.append_audit_event(started_event)
    audit_events: list[AuditEvent] = [started_event]

    graph = build_case_workflow_graph(ai_provider, fhir_client)

    try:
        final_state: CaseWorkflowState = graph.invoke(initial_state)
    except Exception as error:
        failed_at_utc = datetime.now(timezone.utc)
        _persist_final_run(
            repository=repository,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            workflow_status_code="FAILED",
            human_review_required=False,
            failure_category_code=None,
            next_action_code=None,
            completed_at_utc=failed_at_utc,
            updated_at_utc=failed_at_utc,
        )
        failure_event = _make_event(
            trace_id=trace_id,
            case_id=case.case_id,
            event_type_code="WORKFLOW_FAILED",
            event_category_code=AuditEventCategory.WORKFLOW,
            source_component_code=initiated_by_component_code,
            result_code="FAILED",
            occurred_at_utc=failed_at_utc,
            created_by=created_by,
        )
        repository.append_audit_event(failure_event)
        audit_events.append(failure_event)
        raise OrchestratorError(
            "Workflow execution failed unsafely; run marked FAILED."
        ) from error

    completed_at_utc = datetime.now(timezone.utc)
    workflow_status_code = _WORKFLOW_STATUS_TO_CODE[final_state["workflow_status"]]
    failure_category_code = _resolve_failure_category_code(final_state)
    next_action_code = _resolve_next_action_code(workflow_status_code)

    _persist_final_run(
        repository=repository,
        trace_id=trace_id,
        case_id=case.case_id,
        workflow_definition_id=workflow_definition_id,
        initiated_by_component_code=initiated_by_component_code,
        started_at_utc=started_at_utc,
        created_by=created_by,
        workflow_status_code=workflow_status_code,
        human_review_required=final_state["human_review_required"],
        failure_category_code=failure_category_code,
        next_action_code=next_action_code,
        completed_at_utc=(
            completed_at_utc
            if workflow_status_code in _TERMINAL_WORKFLOW_STATUS_CODES
            else None
        ),
        updated_at_utc=completed_at_utc,
    )

    step_events = _build_step_audit_events(
        trace_id=trace_id,
        case_id=case.case_id,
        final_state=final_state,
        occurred_at_utc=completed_at_utc,
        created_by=created_by,
        step_code_to_workflow_step_id=step_code_to_workflow_step_id,
    )
    for event in step_events:
        repository.append_audit_event(event)
    audit_events.extend(step_events)

    return WorkflowRunResult(
        trace_id=trace_id, final_state=final_state, audit_events=audit_events
    )


def _persist_final_run(
    *,
    repository: AuditRepository,
    trace_id: str,
    case_id: str,
    workflow_definition_id: str,
    initiated_by_component_code: str,
    started_at_utc: datetime,
    created_by: str,
    workflow_status_code: str,
    human_review_required: bool,
    failure_category_code: str | None,
    next_action_code: str | None,
    completed_at_utc: datetime | None,
    updated_at_utc: datetime,
) -> None:
    """Updates the workflow_runs row with the run's outcome. Identity
    fields (case_id, workflow_definition_id, initiated_by_component_code,
    started_at_utc, created_at_utc, created_by) are supplied unchanged
    from what save_workflow_run() first inserted -- the repository's
    own update-branch mutability policy (src/db/repository.py) is what
    actually enforces they are never overwritten."""
    repository.save_workflow_run(
        WorkflowRunSnapshot(
            trace_id=trace_id,
            case_id=case_id,
            workflow_definition_id=workflow_definition_id,
            workflow_status_code=workflow_status_code,
            next_action_code=next_action_code,
            human_review_required=human_review_required,
            failure_category_code=failure_category_code,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            created_at_utc=started_at_utc,
            created_by=created_by,
            updated_at_utc=updated_at_utc,
            updated_by=created_by,
        )
    )


def _resolve_failure_category_code(final_state: CaseWorkflowState) -> str | None:
    """
    Resolves the technical failure_category_code (if any) from the
    final state's FHIR/AI outcomes -- None when the run's routing was a
    business-facts decision (evidence mismatch, missing information),
    not a technical failure. See docs/database/data_model.md's
    Failure-vs-Reason distinction: a business routing reason belongs on
    the corresponding audit event's reason_code, never here.
    """
    fhir_outcome = final_state.get("fhir_integration_outcome")
    if fhir_outcome is not None and not fhir_outcome.success:
        return _FHIR_FAILURE_TO_FAILURE_CATEGORY_CODE[fhir_outcome.failure_type]

    ai_outcome = final_state.get("ai_analysis_outcome")
    if ai_outcome is not None and not ai_outcome.success:
        return _AI_FAILURE_TO_FAILURE_CATEGORY_CODE[ai_outcome.failure_type]

    return None


def _resolve_next_action_code(workflow_status_code: str) -> str | None:
    """Maps the run's final status to the matching workflow_actions
    code (docs/database/reference_data.md Section 5)."""
    if workflow_status_code == "COMPLETED":
        return "COMPLETE_WORKFLOW"
    if workflow_status_code == "HUMAN_REVIEW_REQUIRED":
        return "ROUTE_HUMAN_REVIEW"
    return None


def _make_event(
    *,
    trace_id: str,
    case_id: str,
    event_type_code: str,
    event_category_code: AuditEventCategory,
    source_component_code: str,
    result_code: str,
    occurred_at_utc: datetime,
    created_by: str,
    workflow_status_code: str | None = None,
    workflow_step_id: str | None = None,
    failure_category_code: str | None = None,
    reason_code: str | None = None,
    metadata_json: str | None = None,
) -> AuditEvent:
    """Small helper so every audit event this module creates supplies
    the same actor/schema-version conventions consistently."""
    return AuditEvent(
        trace_id=trace_id,
        case_id=case_id,
        event_type_code=event_type_code,
        event_category_code=event_category_code,
        workflow_status_code=workflow_status_code,
        workflow_step_id=workflow_step_id,
        source_component_code=source_component_code,
        actor_type_code="SYSTEM",
        result_code=result_code,
        failure_category_code=failure_category_code,
        reason_code=reason_code,
        occurred_at_utc=occurred_at_utc,
        schema_version=_SCHEMA_VERSION,
        metadata_json=metadata_json,
        created_at_utc=occurred_at_utc,
        created_by=created_by,
    )


# =====================================================================
# STEP AUDIT EVENTS
# Purpose:
# Builds exactly the meaningful audit events for one completed run, by
# inspecting the final state's already-computed results -- never by
# logging every Python function call. Event/category codes are taken
# verbatim from docs/database/reference_data.md Sections 10-11.
# =====================================================================
def _build_step_audit_events(
    *,
    trace_id: str,
    case_id: str,
    final_state: CaseWorkflowState,
    occurred_at_utc: datetime,
    created_by: str,
    step_code_to_workflow_step_id: dict[str, str],
) -> list[AuditEvent]:
    def step_id(step_code: str) -> str | None:
        return step_code_to_workflow_step_id.get(step_code)

    events: list[AuditEvent] = []

    fhir_outcome = final_state.get("fhir_integration_outcome")
    if fhir_outcome is not None:
        if fhir_outcome.success:
            events.append(
                _make_event(
                    trace_id=trace_id,
                    case_id=case_id,
                    event_type_code="FHIR_RETRIEVAL_SUCCEEDED",
                    event_category_code=AuditEventCategory.FHIR,
                    source_component_code="FHIR_STYLE_CLIENT",
                    result_code="SUCCESS",
                    occurred_at_utc=occurred_at_utc,
                    created_by=created_by,
                    workflow_step_id=step_id(STEP_CODE_FHIR_RETRIEVAL),
                )
            )
        else:
            events.append(
                _make_event(
                    trace_id=trace_id,
                    case_id=case_id,
                    event_type_code="FHIR_RETRIEVAL_FAILED",
                    event_category_code=AuditEventCategory.FHIR,
                    source_component_code="FHIR_STYLE_CLIENT",
                    result_code="FAILED",
                    occurred_at_utc=occurred_at_utc,
                    created_by=created_by,
                    workflow_step_id=step_id(STEP_CODE_FHIR_RETRIEVAL),
                    failure_category_code=_FHIR_FAILURE_TO_FAILURE_CATEGORY_CODE[
                        fhir_outcome.failure_type
                    ],
                )
            )

    consistency_result = final_state.get("evidence_consistency_result")
    if consistency_result is not None:
        reason_code = None
        if consistency_result.mismatch_reasons:
            reason_code = _EVIDENCE_MISMATCH_TO_REASON_CODE[
                consistency_result.mismatch_reasons[0]
            ]
        events.append(
            _make_event(
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="EVIDENCE_CONSISTENCY_CHECKED",
                event_category_code=AuditEventCategory.RULE,
                source_component_code="RULE_ENGINE",
                result_code="MATCH" if consistency_result.is_consistent else "MISMATCH",
                occurred_at_utc=occurred_at_utc,
                created_by=created_by,
                workflow_step_id=step_id(STEP_CODE_EVIDENCE_CONSISTENCY),
                reason_code=reason_code,
            )
        )

    completeness_result = final_state.get("completeness_result")
    if completeness_result is not None:
        events.append(
            _make_event(
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="COMPLETENESS_CHECKED",
                event_category_code=AuditEventCategory.RULE,
                source_component_code="RULE_ENGINE",
                result_code=(
                    "COMPLETE" if completeness_result.is_complete else "INCOMPLETE"
                ),
                occurred_at_utc=occurred_at_utc,
                created_by=created_by,
                workflow_step_id=step_id(STEP_CODE_COMPLETENESS_CHECK),
            )
        )

    ai_routing_result = final_state.get("ai_routing_result")
    if ai_routing_result is not None:
        events.append(
            _make_event(
                trace_id=trace_id,
                case_id=case_id,
                event_type_code=(
                    "AI_REQUIRED" if ai_routing_result.ai_required else "AI_NOT_REQUIRED"
                ),
                event_category_code=AuditEventCategory.AI,
                source_component_code="RULE_ENGINE",
                result_code="ROUTED" if ai_routing_result.ai_required else "SKIPPED",
                occurred_at_utc=occurred_at_utc,
                created_by=created_by,
                workflow_step_id=step_id(STEP_CODE_AI_ROUTING),
            )
        )

    ai_outcome = final_state.get("ai_analysis_outcome")
    if ai_outcome is not None:
        if ai_outcome.success:
            events.append(
                _make_event(
                    trace_id=trace_id,
                    case_id=case_id,
                    event_type_code="AI_ANALYSIS_SUCCEEDED",
                    event_category_code=AuditEventCategory.AI,
                    source_component_code="AI_SERVICE",
                    result_code="SUCCESS",
                    occurred_at_utc=occurred_at_utc,
                    created_by=created_by,
                    workflow_step_id=step_id(STEP_CODE_AI_ANALYSIS),
                )
            )
        else:
            events.append(
                _make_event(
                    trace_id=trace_id,
                    case_id=case_id,
                    event_type_code="AI_ANALYSIS_FAILED",
                    event_category_code=AuditEventCategory.AI,
                    source_component_code="AI_SERVICE",
                    result_code="FAILED",
                    occurred_at_utc=occurred_at_utc,
                    created_by=created_by,
                    workflow_step_id=step_id(STEP_CODE_AI_ANALYSIS),
                    failure_category_code=_AI_FAILURE_TO_FAILURE_CATEGORY_CODE[
                        ai_outcome.failure_type
                    ],
                )
            )

    workflow_status = final_state["workflow_status"]
    if workflow_status == WorkflowStatus.HUMAN_REVIEW_REQUIRED:
        events.append(
            _make_event(
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="HUMAN_REVIEW_REQUIRED",
                event_category_code=AuditEventCategory.HUMAN,
                source_component_code="LANGGRAPH",
                result_code="ROUTED",
                occurred_at_utc=occurred_at_utc,
                created_by=created_by,
                workflow_step_id=step_id(STEP_CODE_HUMAN_REVIEW),
                workflow_status_code="HUMAN_REVIEW_REQUIRED",
                reason_code=_resolve_human_review_reason_code(final_state),
            )
        )
    elif workflow_status in (
        WorkflowStatus.COMPLETE,
        WorkflowStatus.AI_ANALYSIS_COMPLETE,
    ):
        events.append(
            _make_event(
                trace_id=trace_id,
                case_id=case_id,
                event_type_code="WORKFLOW_COMPLETED",
                event_category_code=AuditEventCategory.WORKFLOW,
                source_component_code="LANGGRAPH",
                result_code="SUCCESS",
                occurred_at_utc=occurred_at_utc,
                created_by=created_by,
                workflow_step_id=step_id(STEP_CODE_COMPLETE),
                workflow_status_code="COMPLETED",
            )
        )

    return events


def _resolve_human_review_reason_code(final_state: CaseWorkflowState) -> str | None:
    """
    Resolves the reasons.reason_code explaining why a run was routed to
    human review, per docs/database/reference_data.md Section 16. No
    catalog reason exists yet for plain missing-information routing, so
    that case is left None rather than inventing a code.
    """
    fhir_outcome = final_state.get("fhir_integration_outcome")
    if fhir_outcome is not None and not fhir_outcome.success:
        return "HUMAN_REVIEW_FHIR_FAILURE"

    consistency_result = final_state.get("evidence_consistency_result")
    if consistency_result is not None and not consistency_result.is_consistent:
        return "HUMAN_REVIEW_EVIDENCE_MISMATCH"

    ai_outcome = final_state.get("ai_analysis_outcome")
    if ai_outcome is not None and not ai_outcome.success:
        return "HUMAN_REVIEW_AI_FAILURE"

    return None


__all__ = [
    "OrchestratorError",
    "WorkflowRunResult",
    "run_prior_authorization_workflow",
]
