# File Name: human_review_api.py
# Purpose: Defines the request/response contract models for the Human Review decision-submission API endpoint.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.audit import AuditEvent, WorkflowRunSnapshot
from src.models.human_review import HumanReviewOutcome, HumanReviewRecord

# =====================================================================
# HUMAN REVIEW DECISION API REQUEST/RESPONSE CONTRACT
# Purpose:
# Defines exactly what POST /human-review/decisions accepts
# (HumanReviewDecisionRequest) and returns (HumanReviewDecisionResponse).
#
# Why:
# Mirrors src/models/api.py's existing convention (Task 14): reuse the
# project's already-canonical models (HumanReviewRecord,
# WorkflowRunSnapshot, AuditEvent) instead of redefining similar fields
# here, so there is one single source of truth for what a review/
# workflow-run/audit event looks like across the API and the rest of
# the project. review_outcome_code is typed as the real HumanReviewOutcome
# enum, so FastAPI/Pydantic reject any value outside the four approved
# outcomes (CONTINUE_WORKFLOW, REQUEST_MORE_INFORMATION, ESCALATE,
# CLOSE_CASE) before the route body ever runs -- no clinical
# approve/deny outcome exists to accept.
#
# Important Notes:
# - This is a request/response transport contract only. All decision
#   business logic (outcome-to-state mapping, CLOSE_CASE reason
#   validation, transaction atomicity) lives entirely in
#   src/workflow/human_review_service.py's resume_after_human_review()
#   -- never duplicated here.
# - Phase 1 has no authentication/authorization layer (see
#   src/api/app.py's module docstring and this file's own note below):
#   reviewer_actor_type_code/reviewer_reference are supplied directly by
#   the caller, exactly as every existing offline/real-SQL Human Review
#   test already does. Adding real authentication is a future
#   productionization item, not implemented here, and not claimed as
#   implemented.
# =====================================================================


class HumanReviewDecisionRequest(BaseModel):
    """
    The request body for POST /human-review/decisions.

    Mirrors resume_after_human_review()'s own required/optional
    parameters exactly -- fields required there are required here;
    fields optional there (with the same defaults) are optional here.
    close_reason_code/close_reason_text are only required by the
    service when review_outcome_code=CLOSE_CASE -- that validation
    happens inside resume_after_human_review() itself (deterministic,
    before any database interaction), not duplicated in this schema.
    """

    model_config = ConfigDict(extra="forbid")

    review_id: str
    review_outcome_code: HumanReviewOutcome
    reviewer_actor_type_code: str
    reviewer_reference: str
    decision_at_utc: datetime
    review_note_text: str | None = None
    close_reason_code: str | None = None
    close_reason_text: str | None = None
    updated_by: str = "SYSTEM"


class HumanReviewDecisionResponse(BaseModel):
    """
    The response body for POST /human-review/decisions.

    Reports the resulting review/workflow-run state and the audit
    events this decision produced -- not a clinical or payer decision.
    For CONTINUE_WORKFLOW, workflow_run.workflow_status_code is
    PENDING_RESUME and workflow_run.completed_at_utc is null; this
    response never represents true post-review workflow continuation
    (Task 24) and audit_events never includes WORKFLOW_RESUMED, because
    src/workflow/human_review_service.py never produces it.
    """

    model_config = ConfigDict(extra="forbid")

    review: HumanReviewRecord
    workflow_run: WorkflowRunSnapshot
    audit_events: list[AuditEvent]
