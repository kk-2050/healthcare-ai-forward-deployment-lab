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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.ai.contracts import AIAnalysisFailureType
from src.ai.provider import AIAnalysisProvider
from src.db.case_repository import CaseRepository
from src.db.human_review_repository import HumanReviewRepository
from src.db.repository import AuditRepository, deterministic_human_review_event_id
from src.integrations.fhir_client import FHIRStyleClient
from src.integrations.fhir_models import FHIRIntegrationFailureType
from src.models.ai import AIProcessingRequirements
from src.models.audit import AuditEvent, AuditEventCategory, WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.evidence import EvidenceMismatchReason
from src.models.rules import CompletenessRequirements
from src.workflow.graph import build_case_workflow_graph
from src.workflow.human_review_service import request_human_review
from src.workflow.state import CaseWorkflowState, WorkflowStatus
from src.workflow.step_mapping import (
    STEP_CODE_AI_ANALYSIS,
    STEP_CODE_AI_ROUTING,
    STEP_CODE_COMPLETE,
    STEP_CODE_COMPLETENESS_CHECK,
    STEP_CODE_EVIDENCE_CONSISTENCY,
    STEP_CODE_FHIR_RETRIEVAL,
    STEP_CODE_HUMAN_REVIEW,
    STEP_CODE_REQUEST_MISSING_INFORMATION,
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
    # MISSING_INFORMATION_REQUESTED (Step 23C-5C, ADR-008): the Stage 1
    # deterministic missing-information disposition also collapses to
    # COMPLETED -- "this workflow run reached its current terminal
    # disposition," not "the case is closed." next_action_code (see
    # _WORKFLOW_STATUS_TO_NEXT_ACTION_CODE below) is what actually
    # distinguishes it from an ordinary complete run.
    WorkflowStatus.MISSING_INFORMATION_REQUESTED: "COMPLETED",
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
    case_repository: CaseRepository | None = None,
    human_review_repository: HumanReviewRepository | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> WorkflowRunResult:
    """
    Runs one case through the LangGraph workflow and persists its
    lifecycle. Returns the run's identity, final state, and the audit
    events written for it. Raises OrchestratorError if graph execution
    fails unsafely; a PersistenceError from the repository is never
    caught here, so a failed write always surfaces to the caller.

    case_repository/session_factory (Step 23C-5C) are required only when
    a run reaches the Stage 1 MISSING_INFORMATION_REQUESTED disposition
    -- that disposition's workflow_runs/prior_authorization_cases/audit
    writes must commit atomically (see _persist_stage1_disposition()
    below), the same caller-owned-session pattern already proven in
    src/workflow/human_review_service.py. human_review_repository/
    session_factory (Step 23C-6A) are required only when a run reaches
    the genuine HUMAN_REVIEW_REQUIRED disposition (FHIR failure,
    evidence mismatch, or AI failure -- never the Stage 1 disposition) --
    that disposition's workflow_runs/audit_events writes and its durable
    human_reviews request must also commit atomically (see
    _persist_human_review_required_disposition() below), so the workflow
    is never left claiming HUMAN_REVIEW_REQUIRED with no durable review
    request behind it. Callers whose cases never reach either
    disposition (e.g. the ordinary complete path) do not need to supply
    any of case_repository/human_review_repository/session_factory.
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
    workflow_status = final_state["workflow_status"]
    workflow_status_code = _WORKFLOW_STATUS_TO_CODE[workflow_status]
    failure_category_code = _resolve_failure_category_code(final_state)
    next_action_code = _resolve_next_action_code(workflow_status)
    run_completed_at_utc = (
        completed_at_utc if workflow_status_code in _TERMINAL_WORKFLOW_STATUS_CODES else None
    )

    step_events = _build_step_audit_events(
        trace_id=trace_id,
        case_id=case.case_id,
        final_state=final_state,
        occurred_at_utc=completed_at_utc,
        created_by=created_by,
        step_code_to_workflow_step_id=step_code_to_workflow_step_id,
    )

    if workflow_status == WorkflowStatus.MISSING_INFORMATION_REQUESTED:
        # Stage 1 disposition (Step 23C-5C, ADR-008): workflow_runs +
        # prior_authorization_cases.PENDING_INFORMATION + this run's
        # final audit events (including WORKFLOW_COMPLETED) must commit
        # atomically -- narrowly scoped to this one disposition, not a
        # redesign of every orchestrator persistence path.
        if case_repository is None or session_factory is None:
            raise OrchestratorError(
                "case_repository and session_factory are required to "
                "persist a MISSING_INFORMATION_REQUESTED disposition "
                "atomically (Step 23C-5C)."
            )
        _persist_stage1_disposition(
            repository=repository,
            case_repository=case_repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            workflow_status_code=workflow_status_code,
            next_action_code=next_action_code,
            completed_at_utc=run_completed_at_utc,
            updated_at_utc=completed_at_utc,
            step_events=step_events,
        )
    elif workflow_status == WorkflowStatus.HUMAN_REVIEW_REQUIRED:
        # Genuine Human Review route (Step 23C-6A): FHIR failure,
        # evidence mismatch, or AI failure -- never the Stage 1
        # disposition (that no longer reaches HUMAN_REVIEW_REQUIRED at
        # all, since Step 23C-5C). workflow_runs + this run's final
        # audit events (including HUMAN_REVIEW_REQUIRED) + the durable
        # human_reviews request must commit atomically, so the workflow
        # is never left claiming HUMAN_REVIEW_REQUIRED with no durable
        # review request behind it.
        if human_review_repository is None or session_factory is None:
            raise OrchestratorError(
                "human_review_repository and session_factory are required "
                "to persist a HUMAN_REVIEW_REQUIRED disposition atomically "
                "(Step 23C-6A)."
            )
        human_review_reason_code = _resolve_human_review_reason_code(final_state)
        if human_review_reason_code is None or not human_review_reason_code.strip():
            raise OrchestratorError(
                "reason_code is required to persist a HUMAN_REVIEW_REQUIRED "
                "disposition, but none was resolved for this run."
            )
        _persist_human_review_required_disposition(
            repository=repository,
            human_review_repository=human_review_repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            failure_category_code=failure_category_code,
            next_action_code=next_action_code,
            updated_at_utc=completed_at_utc,
            step_events=step_events,
            reason_code=human_review_reason_code,
        )
    else:
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
            completed_at_utc=run_completed_at_utc,
            updated_at_utc=completed_at_utc,
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
    session: Session | None = None,
) -> None:
    """Updates the workflow_runs row with the run's outcome. Identity
    fields (case_id, workflow_definition_id, initiated_by_component_code,
    started_at_utc, created_at_utc, created_by) are supplied unchanged
    from what save_workflow_run() first inserted -- the repository's
    own update-branch mutability policy (src/db/repository.py) is what
    actually enforces they are never overwritten.

    Pass session= to participate in a caller-owned shared transaction
    (see _persist_stage1_disposition() below) instead of this repository
    call opening/committing its own -- identical in spirit to
    AuditRepository's own session= support."""
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
        ),
        session=session,
    )


# =====================================================================
# STAGE 1 ATOMIC DISPOSITION PERSISTENCE
# Purpose:
# Persists the Stage 1 MISSING_INFORMATION_REQUESTED disposition's three
# logically-related writes -- workflow_runs, prior_authorization_cases
# (PENDING_INFORMATION), and this run's final audit events (including
# WORKFLOW_COMPLETED) -- in one shared, caller-owned transaction, so a
# failure partway through never leaves contradictory partial state (Step
# 23C-5B §9 / Step 23C-5C §6). Narrowly scoped to this one disposition;
# every other disposition keeps the existing independent-commit
# persistence in run_prior_authorization_workflow() above unchanged.
# =====================================================================
def _persist_stage1_disposition(
    *,
    repository: AuditRepository,
    case_repository: CaseRepository,
    session_factory: Callable[[], Session],
    trace_id: str,
    case_id: str,
    workflow_definition_id: str,
    initiated_by_component_code: str,
    started_at_utc: datetime,
    created_by: str,
    workflow_status_code: str,
    next_action_code: str | None,
    completed_at_utc: datetime | None,
    updated_at_utc: datetime,
    step_events: list[AuditEvent],
) -> None:
    """Opens one session and commits the Stage 1 workflow_runs update,
    the case's PENDING_INFORMATION status update, and this run's final
    audit events together -- or rolls all of them back together."""
    session = session_factory()
    try:
        _persist_final_run(
            repository=repository,
            trace_id=trace_id,
            case_id=case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            workflow_status_code=workflow_status_code,
            human_review_required=False,
            failure_category_code=None,
            next_action_code=next_action_code,
            completed_at_utc=completed_at_utc,
            updated_at_utc=updated_at_utc,
            session=session,
        )
        case_repository.update_case_status(
            case_id=case_id,
            case_status_code="PENDING_INFORMATION",
            updated_by=created_by,
            updated_at_utc=updated_at_utc,
            session=session,
        )
        for event in step_events:
            repository.append_audit_event(event, session=session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =====================================================================
# HUMAN REVIEW REQUIRED ATOMIC DISPOSITION PERSISTENCE
# Purpose:
# Persists a genuine HUMAN_REVIEW_REQUIRED disposition's three
# logically-related writes -- workflow_runs, this run's final audit
# events (including HUMAN_REVIEW_REQUIRED), and the durable
# human_reviews request created via request_human_review() -- in one
# shared, caller-owned transaction (Step 23C-6A), the same pattern
# already proven for the Stage 1 disposition
# (_persist_stage1_disposition() above) and for
# resume_after_human_review() (src/workflow/human_review_service.py).
# Guarantees the workflow is never left claiming HUMAN_REVIEW_REQUIRED
# with no durable review request behind it: any failure in this block
# rolls back the workflow_runs/audit writes together with the failed
# review-request write, never leaving contradictory partial state.
# Only for the three genuine Human Review routes (FHIR failure,
# evidence mismatch, AI failure) -- never for Stage 1.
# =====================================================================
def _persist_human_review_required_disposition(
    *,
    repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    session_factory: Callable[[], Session],
    trace_id: str,
    case_id: str,
    workflow_definition_id: str,
    initiated_by_component_code: str,
    started_at_utc: datetime,
    created_by: str,
    failure_category_code: str | None,
    next_action_code: str | None,
    updated_at_utc: datetime,
    step_events: list[AuditEvent],
    reason_code: str,
) -> None:
    """Opens one session and commits the HUMAN_REVIEW_REQUIRED
    workflow_runs update, this run's final audit events, and the
    durable human_reviews request together -- or rolls all of them back
    together."""
    session = session_factory()
    try:
        _persist_final_run(
            repository=repository,
            trace_id=trace_id,
            case_id=case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            workflow_status_code="HUMAN_REVIEW_REQUIRED",
            human_review_required=True,
            failure_category_code=failure_category_code,
            next_action_code=next_action_code,
            completed_at_utc=None,
            updated_at_utc=updated_at_utc,
            session=session,
        )
        for event in step_events:
            repository.append_audit_event(event, session=session)
        request_human_review(
            trace_id=trace_id,
            case_id=case_id,
            reason_code=reason_code,
            repository=human_review_repository,
            created_by=created_by,
            session=session,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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


# Keyed by the Python-level WorkflowStatus, not the already-collapsed
# workflow_status_code: COMPLETE, AI_ANALYSIS_COMPLETE, and (Step
# 23C-5C) MISSING_INFORMATION_REQUESTED all persist as the same
# workflow_status_code=COMPLETED (see _WORKFLOW_STATUS_TO_CODE above),
# but need different next_action_code values -- the DB status alone
# cannot distinguish them.
_WORKFLOW_STATUS_TO_NEXT_ACTION_CODE: dict[WorkflowStatus, str] = {
    WorkflowStatus.COMPLETE: "COMPLETE_WORKFLOW",
    WorkflowStatus.AI_ANALYSIS_COMPLETE: "COMPLETE_WORKFLOW",
    WorkflowStatus.MISSING_INFORMATION_REQUESTED: "REQUEST_MISSING_INFORMATION",
    WorkflowStatus.HUMAN_REVIEW_REQUIRED: "ROUTE_HUMAN_REVIEW",
}


def _resolve_next_action_code(workflow_status: WorkflowStatus) -> str | None:
    """Maps the run's final Python-level WorkflowStatus to the matching
    workflow_actions code (docs/database/reference_data.md Section 5)."""
    return _WORKFLOW_STATUS_TO_NEXT_ACTION_CODE.get(workflow_status)


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
    event_id: str | None = None,
) -> AuditEvent:
    """Small helper so every audit event this module creates supplies
    the same actor/schema-version conventions consistently.

    event_id (Step 24B-4A): optional explicit override. Every existing
    call site omits it, so AuditEvent's own default_factory generates a
    fresh random UUID4 exactly as before this change -- zero behavior
    change for WORKFLOW_STARTED, WORKFLOW_FAILED, or any event built by
    _build_step_audit_events(). Only
    _continue_claimed_workflow_processing()'s WORKFLOW_RESUMED event
    supplies it explicitly: that one event's event_id is
    deterministically DERIVED from the authorizing review_id and its
    event type (see that function) -- resume-episode defense-in-depth
    only, not a new AuditEvent schema field and not a recoverable,
    persisted review_id linkage (AuditEvent still has no review_id
    column) -- mirroring the existing precedent already established in
    src/workflow/human_review_service.py for
    HUMAN_REVIEW_COMPLETED/WORKFLOW_COMPLETED."""
    event_kwargs = dict(
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
    if event_id is not None:
        event_kwargs["event_id"] = event_id
    return AuditEvent(**event_kwargs)


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
        WorkflowStatus.MISSING_INFORMATION_REQUESTED,
    ):
        # Step 23C-5C: MISSING_INFORMATION_REQUESTED's WORKFLOW_COMPLETED
        # event is attributed to the Stage 1 disposition step, not the
        # ordinary COMPLETE step -- this event does not claim the case is
        # closed (see docs/architecture.md §7.1); only the workflow run
        # reached a disposition.
        completed_step_code = (
            STEP_CODE_REQUEST_MISSING_INFORMATION
            if workflow_status == WorkflowStatus.MISSING_INFORMATION_REQUESTED
            else STEP_CODE_COMPLETE
        )
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
                workflow_step_id=step_id(completed_step_code),
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


# =====================================================================
# RESUME CLAIM COMPENSATION (Step 24B-4A)
# Purpose:
# Reverts an already-claimed workflow run back to PENDING_RESUME/
# CONTINUE_PROCESSING when continuation could not even begin -- before
# graph.invoke() was ever called -- using the SAME race-safe
# conditional-UPDATE primitive the claim itself uses (never a blind
# read-then-write via save_workflow_run()). If the row is no longer in
# the exact PROCESSING/NULL state this invocation's own successful
# claim left it in, this function does NOT overwrite whatever that
# state now is -- it raises, chaining the original setup error, so the
# caller sees both what failed and that compensation could not safely
# proceed. The run's actual current state is left completely untouched
# in that case.
# =====================================================================
def _revert_resume_claim(
    *,
    repository: AuditRepository,
    existing_run: WorkflowRunSnapshot,
    updated_by: str,
    original_error: Exception,
) -> None:
    reverted_at_utc = datetime.now(timezone.utc)
    reverted = repository.claim_workflow_run_for_resume(
        existing_run.trace_id,
        expected_status="PROCESSING",
        expected_next_action=None,
        new_status="PENDING_RESUME",
        new_next_action="CONTINUE_PROCESSING",
        updated_at_utc=reverted_at_utc,
        updated_by=updated_by,
    )
    if not reverted:
        raise OrchestratorError(
            f"Workflow continuation setup failed for trace_id="
            f"{existing_run.trace_id!r}, and the resume claim could not "
            "be safely reverted -- the run's state has changed since it "
            "was claimed. The run's current state was NOT overwritten; "
            "manual investigation is required."
        ) from original_error


# =====================================================================
# RESUMED RUN ATOMIC TERMINAL DISPOSITION PERSISTENCE (Step 24B-4A)
# Purpose:
# Persists a resumed run's ordinary COMPLETED/FAILED workflow_runs
# update together with its final audit events (including
# WORKFLOW_RESUMED) in one shared, caller-owned transaction -- the same
# pattern already proven by _persist_stage1_disposition()/
# _persist_human_review_required_disposition() above.
#
# Why this differs from the ordinary (non-resumed) COMPLETED/FAILED
# path in run_prior_authorization_workflow(), which persists
# workflow_runs and then each audit event as independent writes: a
# resumed run's WORKFLOW_RESUMED event and the disposition it led to
# are two facts about the SAME authorized continuation episode, and
# must never be left split by a partial failure -- WORKFLOW_RESUMED
# recorded with no disposition, or a disposition with no record that a
# resume actually happened, would both be misleading audit states.
# =====================================================================
def _persist_resumed_terminal_disposition(
    *,
    repository: AuditRepository,
    session_factory: Callable[[], Session],
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
    step_events: list[AuditEvent],
) -> None:
    """Opens one session and commits the resumed run's workflow_runs
    update and its final audit events together -- or rolls both back
    together."""
    session = session_factory()
    try:
        _persist_final_run(
            repository=repository,
            trace_id=trace_id,
            case_id=case_id,
            workflow_definition_id=workflow_definition_id,
            initiated_by_component_code=initiated_by_component_code,
            started_at_utc=started_at_utc,
            created_by=created_by,
            workflow_status_code=workflow_status_code,
            human_review_required=human_review_required,
            failure_category_code=failure_category_code,
            next_action_code=next_action_code,
            completed_at_utc=completed_at_utc,
            updated_at_utc=updated_at_utc,
            session=session,
        )
        for event in step_events:
            repository.append_audit_event(event, session=session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =====================================================================
# SAME-RUN/SAME-TRACE RESUME CONTINUATION (Step 24B-4A)
# Purpose:
# Continues an already-claimed workflow run's automated processing
# using the SAME trace_id -- Task 24's approved Option A architecture
# (SAME-RUN/SAME-TRACE APPLICATION-LEVEL CONTINUATION; see
# docs/decisions/ADR-007 and the Task 24A/24B-1 design lock). This is
# NOT LangGraph checkpoint-native resume: no durable clinical state is
# reconstructed here. The caller re-supplies the case and processing
# requirements; only the SAME trace_id and workflow_runs row are
# reused.
#
# Public entry point:
# _continue_claimed_workflow_processing() below is an INTERNAL helper:
# it is not exported in this module's __all__ and is not part of the
# supported public application API. Callers must not bypass
# resume_workflow() (src/workflow/resume_service.py) by invoking this
# helper directly -- resume_workflow() is the sole supported
# application-level end-to-end continuation entry point. It owns the
# actual authorization boundary (eligibility validation, the Human
# Review CONTINUE_WORKFLOW check, case-identity validation, and the
# atomic resume claim, all via validate_and_claim_resume()) before this
# helper ever runs.
#
# Why this helper's own precondition check is not itself an
# authorization boundary:
# The fresh-read check below verifies the run is in PROCESSING with
# next_action_code=NULL and belongs to the supplied case -- but
# PROCESSING/NULL is not unique to a post-Human-Review resume; an
# ordinary initial workflow run legitimately passes through that same
# state. This check exists as a race/staleness guard (the run's state
# could change between when it was claimed and when this helper
# actually executes), never as a substitute for having gone through
# validate_and_claim_resume() first.
# =====================================================================
def _continue_claimed_workflow_processing(
    *,
    trace_id: str,
    review_id: str,
    case: PriorAuthorizationCase,
    completeness_requirements: CompletenessRequirements,
    ai_processing_requirements: AIProcessingRequirements,
    ai_provider: AIAnalysisProvider,
    fhir_client: FHIRStyleClient,
    repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    case_repository: CaseRepository,
    session_factory: Callable[[], Session],
    step_code_to_workflow_step_id: dict[str, str] | None = None,
    updated_by: str = "SYSTEM",
) -> WorkflowRunResult:
    """
    Internal helper -- not a public orchestration entry point (see
    section comment above). Continues an ALREADY-CLAIMED workflow run
    using the SAME trace_id.

    review_id identifies the Human Review decision that authorized this
    resume episode. It is used only to derive WORKFLOW_RESUMED's
    event_id (see _make_event()) -- it is never persisted as a new
    column anywhere; AuditEvent still has no review_id field.

    Re-reads the current workflow_runs row and verifies it is genuinely
    still in the exact claimed state (PROCESSING/NULL, matching
    case_id) rather than trusting any earlier snapshot the caller might
    hold (e.g. resume_service.ResumeEligibilityResult.workflow_run) --
    that snapshot can go stale between when the claim succeeded and
    when this helper actually runs. If the precondition does not hold,
    this helper does NOT invoke the graph and does NOT attempt any
    compensating write -- it has no way to know it legitimately owns
    whatever state the row is actually in, so a blind revert here could
    destroy state this invocation never created.

    Raises OrchestratorError if: the run cannot be found; the
    precondition above does not hold; setup before graph invocation
    fails (the claim is reverted first -- no WORKFLOW_RESUMED is
    recorded -- and OrchestratorError is raised only if that reversion
    itself cannot safely proceed, always chaining the original setup
    error); or graph invocation itself fails unsafely (WORKFLOW_RESUMED
    + WORKFLOW_FAILED are persisted together first, then this raises).
    A PersistenceError from any repository is never caught here, so a
    failed write always surfaces to the caller.
    """
    existing_run = repository.get_workflow_run(trace_id)
    if existing_run is None:
        raise OrchestratorError(
            f"No workflow run found for trace_id={trace_id!r}; cannot "
            "continue processing."
        )
    if existing_run.workflow_status_code != "PROCESSING":
        raise OrchestratorError(
            f"Cannot continue processing trace_id={trace_id!r}: "
            f"workflow_status_code is "
            f"{existing_run.workflow_status_code!r}, expected PROCESSING "
            "(the run must already be claimed)."
        )
    if existing_run.next_action_code is not None:
        raise OrchestratorError(
            f"Cannot continue processing trace_id={trace_id!r}: "
            f"next_action_code is {existing_run.next_action_code!r}, "
            "expected None (the run must already be claimed)."
        )
    if existing_run.case_id != case.case_id:
        raise OrchestratorError(
            f"Cannot continue processing trace_id={trace_id!r}: supplied "
            f"case_id {case.case_id!r} does not match the workflow run's "
            f"case_id {existing_run.case_id!r}."
        )

    try:
        graph = build_case_workflow_graph(ai_provider, fhir_client)
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
    except Exception as setup_error:
        _revert_resume_claim(
            repository=repository,
            existing_run=existing_run,
            updated_by=updated_by,
            original_error=setup_error,
        )
        raise

    resumed_at_utc = datetime.now(timezone.utc)
    resumed_event_id = deterministic_human_review_event_id(
        review_id, "WORKFLOW_RESUMED"
    )
    try:
        final_state: CaseWorkflowState = graph.invoke(initial_state)
    except Exception as error:
        failed_at_utc = datetime.now(timezone.utc)
        resumed_event = _make_event(
            trace_id=trace_id,
            case_id=case.case_id,
            event_type_code="WORKFLOW_RESUMED",
            event_category_code=AuditEventCategory.WORKFLOW,
            source_component_code="LANGGRAPH",
            result_code="SUCCESS",
            occurred_at_utc=resumed_at_utc,
            created_by=updated_by,
            event_id=resumed_event_id,
        )
        failure_event = _make_event(
            trace_id=trace_id,
            case_id=case.case_id,
            event_type_code="WORKFLOW_FAILED",
            event_category_code=AuditEventCategory.WORKFLOW,
            source_component_code=existing_run.initiated_by_component_code,
            result_code="FAILED",
            occurred_at_utc=failed_at_utc,
            created_by=updated_by,
        )
        _persist_resumed_terminal_disposition(
            repository=repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=existing_run.workflow_definition_id,
            initiated_by_component_code=existing_run.initiated_by_component_code,
            started_at_utc=existing_run.started_at_utc,
            created_by=existing_run.created_by,
            workflow_status_code="FAILED",
            human_review_required=False,
            failure_category_code=None,
            next_action_code=None,
            completed_at_utc=failed_at_utc,
            updated_at_utc=failed_at_utc,
            step_events=[resumed_event, failure_event],
        )
        raise OrchestratorError(
            "Workflow continuation failed unsafely; run marked FAILED."
        ) from error

    completed_at_utc = datetime.now(timezone.utc)
    workflow_status = final_state["workflow_status"]
    workflow_status_code = _WORKFLOW_STATUS_TO_CODE[workflow_status]
    failure_category_code = _resolve_failure_category_code(final_state)
    next_action_code = _resolve_next_action_code(workflow_status)
    run_completed_at_utc = (
        completed_at_utc
        if workflow_status_code in _TERMINAL_WORKFLOW_STATUS_CODES
        else None
    )

    step_events = _build_step_audit_events(
        trace_id=trace_id,
        case_id=case.case_id,
        final_state=final_state,
        occurred_at_utc=completed_at_utc,
        created_by=updated_by,
        step_code_to_workflow_step_id=step_code_to_workflow_step_id or {},
    )
    resumed_event = _make_event(
        trace_id=trace_id,
        case_id=case.case_id,
        event_type_code="WORKFLOW_RESUMED",
        event_category_code=AuditEventCategory.WORKFLOW,
        source_component_code="LANGGRAPH",
        result_code="SUCCESS",
        occurred_at_utc=resumed_at_utc,
        created_by=updated_by,
        event_id=resumed_event_id,
    )
    step_events = [resumed_event] + step_events

    if workflow_status == WorkflowStatus.MISSING_INFORMATION_REQUESTED:
        _persist_stage1_disposition(
            repository=repository,
            case_repository=case_repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=existing_run.workflow_definition_id,
            initiated_by_component_code=existing_run.initiated_by_component_code,
            started_at_utc=existing_run.started_at_utc,
            created_by=existing_run.created_by,
            workflow_status_code=workflow_status_code,
            next_action_code=next_action_code,
            completed_at_utc=run_completed_at_utc,
            updated_at_utc=completed_at_utc,
            step_events=step_events,
        )
    elif workflow_status == WorkflowStatus.HUMAN_REVIEW_REQUIRED:
        human_review_reason_code = _resolve_human_review_reason_code(final_state)
        if human_review_reason_code is None or not human_review_reason_code.strip():
            raise OrchestratorError(
                "reason_code is required to persist a HUMAN_REVIEW_REQUIRED "
                "disposition, but none was resolved for this resumed run."
            )
        _persist_human_review_required_disposition(
            repository=repository,
            human_review_repository=human_review_repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=existing_run.workflow_definition_id,
            initiated_by_component_code=existing_run.initiated_by_component_code,
            started_at_utc=existing_run.started_at_utc,
            created_by=existing_run.created_by,
            failure_category_code=failure_category_code,
            next_action_code=next_action_code,
            updated_at_utc=completed_at_utc,
            step_events=step_events,
            reason_code=human_review_reason_code,
        )
    else:
        _persist_resumed_terminal_disposition(
            repository=repository,
            session_factory=session_factory,
            trace_id=trace_id,
            case_id=case.case_id,
            workflow_definition_id=existing_run.workflow_definition_id,
            initiated_by_component_code=existing_run.initiated_by_component_code,
            started_at_utc=existing_run.started_at_utc,
            created_by=existing_run.created_by,
            workflow_status_code=workflow_status_code,
            human_review_required=final_state["human_review_required"],
            failure_category_code=failure_category_code,
            next_action_code=next_action_code,
            completed_at_utc=run_completed_at_utc,
            updated_at_utc=completed_at_utc,
            step_events=step_events,
        )

    return WorkflowRunResult(
        trace_id=trace_id, final_state=final_state, audit_events=step_events
    )


__all__ = [
    "OrchestratorError",
    "WorkflowRunResult",
    "run_prior_authorization_workflow",
]
