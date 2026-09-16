# File Name: audit.py
# Purpose: Defines the application-facing persistence and audit models for workflow run traceability.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# AUDIT EVENT CATEGORY
# Purpose:
# Lists the distinct kinds of workflow activity an audit event can
# record.
#
# Why:
# A fixed, small set of categories -- one per architectural concern
# already in this project (the workflow itself, the healthcare
# integration, a deterministic rule, AI, human review, or an error) --
# keeps audit records easy to filter and query later, without inventing
# categories nobody needs yet.
# =====================================================================


class AuditEventCategory(str, Enum):
    WORKFLOW = "WORKFLOW"
    HEALTHCARE_INTEGRATION = "HEALTHCARE_INTEGRATION"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    AI = "AI"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ERROR = "ERROR"


# =====================================================================
# WORKFLOW RUN SNAPSHOT
# Purpose:
# Represents the current state of one workflow run, identified by
# trace_id, for persistence and later retrieval.
#
# Why:
# The workflow run's status must be traceable without persisting
# clinical content, FHIR payloads, or AI text -- that content already
# lives, transiently, in src/workflow/state.py during a run. This
# snapshot only records the small set of facts a reviewer or dashboard
# needs: which case, what state, whether it needs a human.
#
# Important Notes:
# - This model intentionally has no clinical_notes, FHIR payload,
#   member_id, provider_id, or AI response field -- only case_id (a
#   synthetic case reference), workflow_status, and
#   human_review_required/failure_category are stored.
# - Timestamp Policy: created_at_utc and updated_at_utc are always UTC.
#   This model does not perform timezone conversion itself -- the
#   caller is responsible for supplying values already normalized to
#   UTC.
# =====================================================================


class WorkflowRunSnapshot(BaseModel):
    """A persisted snapshot of one workflow run's current state."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    workflow_status: str = Field(min_length=1)
    human_review_required: bool
    failure_category: str | None = None
    created_at_utc: datetime
    updated_at_utc: datetime


# =====================================================================
# AUDIT EVENT
# Purpose:
# Represents one small, structured fact about workflow activity -- a
# step that happened, at a point in time, for one trace.
#
# Why:
# Audit events are the append-only trail behind a WorkflowRunSnapshot's
# current state: multiple events accumulate over time for the same
# trace_id, so a reviewer can see the sequence of what happened, not
# just where a case ended up.
#
# Important Notes:
# - No raw clinical text, FHIR payload, AI prompt/response text,
#   credentials, or approval/denial/medical-necessity field belongs
#   here -- only small structured metadata (see CLAUDE.md Security
#   Rules and Task 18A's data-minimization requirement).
# - event_id defaults to a freshly generated UUID4 string when not
#   supplied. A UUID carries no PHI/PII and needs no external
#   dependency, so this is a safe, simple default -- callers that need
#   a specific ID (e.g. for idempotency) may still supply their own.
# - Timestamp Policy: occurred_at_utc is always UTC, matching
#   WorkflowRunSnapshot's created_at_utc/updated_at_utc.
# =====================================================================


class AuditEvent(BaseModel):
    """One append-only audit record for a single workflow trace."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    trace_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_category: AuditEventCategory
    workflow_status: str | None = None
    processing_step: str | None = None
    failure_category: str | None = None
    occurred_at_utc: datetime
