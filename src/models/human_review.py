# File Name: human_review.py
# Purpose: Defines the application-facing persistence contracts for Human-in-the-Loop review tasks and their controlled outcomes.
# Creation Date: 2026-09-21
# Author: K.Kashiwagi

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# HUMAN REVIEW OUTCOME
# Purpose:
# Lists every outcome a human reviewer may record -- copied verbatim
# from docs/database/reference_data.md Section 18.
#
# Why:
# A fixed, small set of codes (instead of free text or, worse, an
# approval/denial flag) keeps this the same kind of controlled
# vocabulary already used throughout this project (AITask,
# EvidenceMismatchReason, FHIRIntegrationFailureType) -- and makes the
# project's core safety rule structurally enforced, not just
# documented: no code path can construct an "approve" or "deny" value
# because no such value exists in this enum.
#
# Important Notes:
# No autonomous clinical approval/denial outcome is defined here or
# anywhere in the canonical schema (see
# docs/database/reference_data.md Section 18's own note). Do not add
# one without first updating the project's human-in-the-loop safety
# design (ADR-001, docs/security.md Section 5).
# =====================================================================


class HumanReviewOutcome(str, Enum):
    CONTINUE_WORKFLOW = "CONTINUE_WORKFLOW"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    ESCALATE = "ESCALATE"
    CLOSE_CASE = "CLOSE_CASE"


# =====================================================================
# HUMAN REVIEW STATUS
# Purpose:
# Lists every lifecycle status a review task can be in -- copied
# verbatim from docs/database/reference_data.md Section 17.
# =====================================================================


class HumanReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# =====================================================================
# HUMAN REVIEW RECORD
# Purpose:
# Represents one canonical human_reviews row: a review task requested
# for one workflow run, and -- once recorded -- its outcome.
#
# Why:
# Keeping this a separate model from WorkflowRunSnapshot/AuditEvent
# (src/models/audit.py) makes the deterministic-vs-AI-vs-human
# responsibility boundary explicit in the data model itself: this is
# the ONLY model in the project a human decision is ever written
# through. AI output is never accepted as input to
# review_outcome_code -- see src/db/human_review_repository.py, which
# is the only code that ever sets it, always from a caller-supplied
# HumanReviewOutcome value, never derived from an AIAnalysisOutcome.
#
# Important Notes:
# - This model intentionally has no approval, denial, or
#   medical_necessity field -- see HumanReviewOutcome above for why
#   that is structural, not just a convention.
# - reviewer_reference must be a synthetic identifier only in Phase 1
#   (see docs/database/reference_data.md Section 21) -- never a real
#   person's name or ID, in tests or otherwise.
# - review_note_text is optional, synthetic-only, and must never
#   contain PHI/PII, a raw LLM prompt, or a raw LLM provider response.
# =====================================================================


class HumanReviewRecord(BaseModel):
    """One human-in-the-loop review task and its recorded outcome."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    review_status_code: HumanReviewStatus = HumanReviewStatus.REQUESTED
    review_outcome_code: HumanReviewOutcome | None = None
    reason_code: str = Field(min_length=1)
    assigned_department_id: str | None = None
    assigned_location_id: str | None = None
    requested_at_utc: datetime
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    reviewer_actor_type_code: str | None = None
    reviewer_reference: str | None = None
    review_note_text: str | None = None
    source_component_code: str = Field(min_length=1)
    metadata_json: str | None = None
    created_at_utc: datetime
    created_by: str = Field(min_length=1)
    updated_at_utc: datetime
    updated_by: str = Field(min_length=1)
    is_deleted: bool = False
    deleted_at_utc: datetime | None = None
    deleted_by: str | None = None
    delete_reason_code: str | None = None
    delete_reason_text: str | None = None
