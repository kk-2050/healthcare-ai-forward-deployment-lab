# File Name: workflow_snapshot_api.py
# Purpose: Defines the response contract model for the read-only workflow-snapshot lookup API endpoint.
# Creation Date: 2026-10-04
# Author: K.Kashiwagi
#
# Module Explanation:
# Defines exactly what GET /workflows/{trace_id} returns
# (WorkflowSnapshotResponse). Mirrors src/models/resume_api.py's/
# src/models/workflow_api.py's existing convention: reuse the project's
# already-canonical models (WorkflowRunSnapshot, AuditEvent) instead of
# redefining similar fields here, so there is one single source of
# truth for what a workflow run/audit event looks like across the API.
#
# Important Notes:
# - This endpoint is read-only (Task 26B). It never creates, updates,
#   or deletes anything -- it only reports whatever the durable
#   workflow_runs/audit_events state already is.
# - This response has the same shape as StartWorkflowResponse/
#   ResumeWorkflowResponse (trace_id, case_id, workflow_run,
#   audit_events), but is defined as its own model rather than reusing
#   either of those, matching this project's existing precedent
#   (resume_api.py defines its own response model rather than reusing
#   workflow_api.py's identically-shaped one) -- each endpoint's
#   contract stays independently evolvable.
# - Like every other response in this project, this never exposes
#   WorkflowRunResult.final_state, a raw FHIR payload, a raw LLM
#   prompt/response, database configuration, or internal exception
#   detail -- only the same canonical, already-deterministic
#   workflow_run/audit_events shape every other endpoint already
#   exposes.
# =====================================================================

from pydantic import BaseModel, ConfigDict

from src.models.audit import AuditEvent, WorkflowRunSnapshot


class WorkflowSnapshotResponse(BaseModel):
    """
    The response body for GET /workflows/{trace_id}.

    Reports the current durable workflow_run/audit_events state for one
    trace_id -- never a clinical or payer decision, and never the raw
    case/FHIR/AI content a run's internal final_state carries.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    case_id: str
    workflow_run: WorkflowRunSnapshot
    audit_events: list[AuditEvent]
