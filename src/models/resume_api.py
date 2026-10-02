# File Name: resume_api.py
# Purpose: Defines the request/response contract models for the same-run/same-trace workflow resume API endpoint.
# Creation Date: 2026-09-29
# Author: K.Kashiwagi
#
# Module Explanation:
# Defines exactly what POST /workflows/{trace_id}/resume accepts
# (ResumeWorkflowRequest) and returns (ResumeWorkflowResponse). Mirrors
# src/models/human_review_api.py's existing convention: reuse the
# project's already-canonical models (PriorAuthorizationCase,
# CompletenessRequirements, AIProcessingRequirements,
# WorkflowRunSnapshot, AuditEvent) instead of redefining similar fields
# here, so there is one single source of truth for what each of these
# looks like across the API and the rest of the project.
#
# Important Notes:
# - trace_id is deliberately NOT a field on ResumeWorkflowRequest -- it
#   identifies the existing workflow run being resumed and belongs in
#   the URL path (see src/api/app.py's route), never in the request
#   body, so the SAME-RUN/SAME-TRACE contract (Task 24A/24B-1) is
#   visible in the URL itself: this call can never create a new run.
# - This is a request/response transport contract only. All resume
#   business logic (eligibility validation, the Human Review
#   CONTINUE_WORKFLOW check, case-identity validation, the atomic
#   resume claim, and the actual continuation) lives entirely in
#   src/workflow/resume_service.py's resume_workflow() -- never
#   duplicated here.
# - ResumeWorkflowResponse deliberately does NOT expose
#   WorkflowRunResult.final_state. final_state carries the full
#   re-supplied case (diagnosis_code, supporting_documentation,
#   clinical_notes), the raw extracted FHIR evidence, and the raw AI
#   analysis outcome -- exactly the categories docs/security.md
#   Section 4 ("Data minimization in persistence") says must never be
#   persisted or exposed beyond validated, structured facts. This
#   response exposes only the same canonical, already-deterministic
#   workflow_run/audit_events shape the existing
#   POST /human-review/decisions endpoint already exposes.
# - Phase 1 has no authentication/authorization layer (see
#   src/api/app.py's module docstring). Unlike
#   HumanReviewDecisionRequest, this request has no reviewer-identity
#   field at all -- resume_workflow() has no caller-identity parameter
#   beyond updated_by, which this endpoint leaves server/default
#   controlled rather than accepting from the caller. Adding real
#   authentication is a future productionization item, not implemented
#   here, and not claimed as implemented.
# =====================================================================

from pydantic import BaseModel, ConfigDict

from src.models.ai import AIProcessingRequirements
from src.models.audit import AuditEvent, WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements


class ResumeWorkflowRequest(BaseModel):
    """
    The request body for POST /workflows/{trace_id}/resume.

    Mirrors resume_workflow()'s own required caller-supplied business
    inputs exactly -- case, completeness_requirements, and
    ai_processing_requirements. Per Task 24A/24B-1's approved Option A
    design, none of these are durably reconstructable from persisted
    state (only case_id/member_id/provider_id/requested_service_code/
    requested_date persist) -- the caller must re-supply them for this
    controlled re-evaluation. Every other resume_workflow() parameter
    (repositories, session_factory, the FHIR client, the AI provider)
    is a server-constructed dependency and must never appear here.
    """

    model_config = ConfigDict(extra="forbid")

    case: PriorAuthorizationCase
    completeness_requirements: CompletenessRequirements
    ai_processing_requirements: AIProcessingRequirements


class ResumeWorkflowResponse(BaseModel):
    """
    The response body for POST /workflows/{trace_id}/resume.

    Reports the resumed run's identity and the canonical, deterministic
    workflow_run/audit_events state resulting from this continuation --
    never a clinical or payer decision, and never the raw
    case/FHIR/AI content in WorkflowRunResult.final_state (see this
    module's docstring above for why).
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    case_id: str
    workflow_run: WorkflowRunSnapshot
    audit_events: list[AuditEvent]
