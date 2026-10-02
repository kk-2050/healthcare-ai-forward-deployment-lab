# File Name: workflow_api.py
# Purpose: Defines the request/response contract models for the fresh-case workflow-start API endpoint.
# Creation Date: 2026-10-01
# Author: K.Kashiwagi
#
# Module Explanation:
# Defines exactly what POST /workflows accepts (StartWorkflowRequest) and
# returns (StartWorkflowResponse). Mirrors src/models/resume_api.py's
# existing convention: reuse the project's already-canonical models
# (PriorAuthorizationCase, CompletenessRequirements,
# AIProcessingRequirements, WorkflowRunSnapshot, AuditEvent) instead of
# redefining similar fields here.
#
# Important Notes:
# - client_id is request-level intake context only -- it identifies
#   which existing client this fresh case belongs to. It is
#   deliberately NOT added to the shared PriorAuthorizationCase model,
#   which has no concept of a client. This endpoint never creates a
#   client; a client_id that does not identify an existing, active,
#   non-deleted clients row is rejected (see
#   src/workflow/case_intake_service.py).
# - trace_id is never accepted from the caller -- it stays
#   application-generated inside run_prior_authorization_workflow(),
#   exactly as every other orchestration entry point already works.
# - This is a request/response transport contract only. All
#   client-validation, duplicate/safe-retry, case-creation, and
#   workflow-start business logic lives entirely in
#   src/workflow/case_intake_service.py's start_new_case_workflow() --
#   never duplicated here.
# - StartWorkflowResponse deliberately does NOT expose
#   WorkflowRunResult.final_state. final_state carries the re-supplied
#   case, the raw extracted FHIR evidence, and the raw AI analysis
#   outcome -- exactly the categories docs/security.md Section 4
#   ("Data minimization in persistence") says must never be persisted
#   or exposed beyond validated, structured facts. This response
#   exposes only the same canonical, already-deterministic
#   workflow_run/audit_events shape the Resume API already exposes.
# - Phase 1 has no authentication/authorization layer: no caller
#   identity field is accepted here beyond client_id, which identifies
#   an existing business client, not a human caller.
# =====================================================================

from pydantic import BaseModel, ConfigDict, Field

from src.models.ai import AIProcessingRequirements
from src.models.audit import AuditEvent, WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements


class StartWorkflowRequest(BaseModel):
    """
    The request body for POST /workflows.

    Mirrors start_new_case_workflow()'s own required caller-supplied
    inputs exactly -- client_id, case, completeness_requirements, and
    ai_processing_requirements. Every other parameter that function
    needs (repositories, session_factory, the FHIR client, the AI
    provider, workflow_definition_id) is a server-constructed
    dependency and must never appear here.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    case: PriorAuthorizationCase
    completeness_requirements: CompletenessRequirements
    ai_processing_requirements: AIProcessingRequirements


class StartWorkflowResponse(BaseModel):
    """
    The response body for POST /workflows.

    Reports the new run's identity and the canonical, deterministic
    workflow_run/audit_events state resulting from this workflow start
    -- never a clinical or payer decision, and never the raw
    case/FHIR/AI content in WorkflowRunResult.final_state (see this
    module's docstring above for why).
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    case_id: str
    workflow_run: WorkflowRunSnapshot
    audit_events: list[AuditEvent]
