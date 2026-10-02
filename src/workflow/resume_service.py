# File Name: resume_service.py
# Purpose: Implements deterministic resume eligibility validation, persisted case-identity validation, the atomic resume claim, and resume_workflow() -- the public end-to-end entry point for same-run/same-trace application-level workflow continuation.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the eligibility/claim layer of Task 24's approved Option A
# architecture (Task 24A/24B-1 design lock): SAME-RUN/SAME-TRACE
# APPLICATION-LEVEL CONTINUATION, never LangGraph checkpoint-native
# resume. This module deliberately does NOT invoke LangGraph, the
# FHIR-style client, or the AI provider, and does NOT emit
# WORKFLOW_RESUMED or persist any final workflow disposition -- those
# belong to a separate, later, continuation-orchestration step that
# calls INTO this module's validate_and_claim_resume() first, exactly
# mirroring how src/workflow/human_review_service.py contains no
# LangGraph invocation or routing decisions of its own.
#
# Why re-supplied case input is trusted, not re-derived:
# The approved Option A design established (Task 24A) that
# diagnosis_code, supporting_documentation, and clinical_notes are
# never durably persisted anywhere in this project's schema -- only
# case_id, member_id, provider_id, requested_service_code, and
# requested_date are. This module therefore validates the
# caller-supplied case against exactly those five durable fields, and
# intentionally does NOT compare the other three -- there is no durable
# source to compare them against, and doing so would either silently
# accept an unverifiable claim or reject legitimate fresh input for no
# real reason.
#
# Claim ordering:
# Eligibility is checked via read-only lookups first (cheap, and gives
# a precise, attributable reason for ineligibility). The atomic
# conditional-UPDATE claim (AuditRepository.claim_workflow_run_for_resume(),
# Step 24B-2) is always attempted last, and is the actual race-safe
# gate -- if a concurrent request claimed the run between this call's
# eligibility reads and its own claim attempt, the claim itself fails
# (0 rows affected) even though the earlier reads looked eligible; this
# is reported as ResumeClaimConflictError, not silently ignored.

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.ai.provider import AIAnalysisProvider
from src.db.case_repository import CaseRepository, PersistedCaseIdentity
from src.db.human_review_repository import HumanReviewRepository
from src.db.repository import AuditRepository
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.audit import WorkflowRunSnapshot
from src.models.case import PriorAuthorizationCase
from src.models.human_review import HumanReviewOutcome, HumanReviewStatus
from src.models.rules import CompletenessRequirements
from src.workflow.orchestrator import (
    WorkflowRunResult,
    _continue_claimed_workflow_processing,
)

_CASE_IDENTITY_FIELDS = (
    "case_id",
    "member_id",
    "provider_id",
    "requested_service_code",
    "requested_date",
)


# =====================================================================
# DOMAIN ERRORS
# Purpose:
# A small, flat set of exception types -- no shared base class -- to
# match this project's existing exception style (see
# src/workflow/human_review_service.py's ResumeError/
# InvalidCloseReasonError, src/db/human_review_repository.py's
# HumanReviewConflictError/PersistenceError): one purpose-specific
# class per genuinely distinct failure category, not an elaborate
# hierarchy. Each maps to exactly one HTTP status in the approved Task
# 24B-1 error-mapping contract (404/409/422/409 respectively) -- kept
# separate for that reason, not merged into one generic error.
# =====================================================================
class ResumeTraceNotFoundError(Exception):
    """Raised when no workflow_runs row exists for the given trace_id,
    or (defensively) when the workflow run's own case_id has no
    matching prior_authorization_cases row -- the latter is a
    data-integrity condition that should never occur given the real
    foreign-key relationship, but is checked explicitly rather than
    assumed."""


class ResumeNotEligibleError(Exception):
    """Raised when the workflow run (and/or its Human Review) exists
    but does not meet the deterministic resume-eligibility contract:
    workflow_status_code != PENDING_RESUME, next_action_code !=
    CONTINUE_PROCESSING, no completed Human Review exists for this
    trace_id, its outcome is not CONTINUE_WORKFLOW, or its case_id does
    not match the workflow run's own case_id."""


class ResumeCaseIdentityMismatchError(Exception):
    """Raised when the caller-supplied PriorAuthorizationCase disagrees
    with the durable prior_authorization_cases row on any of the fields
    that are actually persisted (case_id, member_id, provider_id,
    requested_service_code, requested_date). Never raised for
    diagnosis_code/supporting_documentation/clinical_notes -- those are
    not durably persisted, so there is nothing to compare them against;
    the caller-supplied value is simply trusted as fresh input (see
    Task 24A/24B-1's approved Option A design)."""


class ResumeClaimConflictError(Exception):
    """Raised when the atomic claim
    (AuditRepository.claim_workflow_run_for_resume()) affects zero
    rows even though the earlier eligibility reads passed -- a genuine
    race: another request claimed this run between this call's
    eligibility reads and its own claim attempt. Never retried
    automatically; the caller must submit a fresh resume request if
    still appropriate."""


@dataclass
class ResumeEligibilityResult:
    """The outcome of a successful eligibility validation + atomic
    claim: exactly what a future continuation step needs, and nothing
    more -- no raw clinical/FHIR/AI content, and no reference to a new
    workflow run or trace_id (there is none)."""

    trace_id: str
    case_id: str
    workflow_run: WorkflowRunSnapshot  # already reflects the claim: PROCESSING/NULL
    review_id: str
    review_completed_at_utc: datetime


# =====================================================================
# VALIDATE AND CLAIM RESUME
# Purpose:
# Validates the full deterministic resume-eligibility contract,
# validates the caller-supplied case's identity against durable
# persistence, and -- only if every check passes -- atomically claims
# the workflow run for resume continuation.
#
# Important Notes:
# - Never invokes LangGraph, the FHIR-style client, or the AI provider.
# - Never emits WORKFLOW_RESUMED or any other audit event.
# - Never persists a final workflow disposition.
# - Never creates a new workflow_runs row or a new trace_id -- reads
#   the existing row and, only at the very end, performs one
#   conditional UPDATE against that SAME row.
# =====================================================================
def validate_and_claim_resume(
    *,
    trace_id: str,
    case: PriorAuthorizationCase,
    workflow_repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    case_repository: CaseRepository,
    updated_by: str = "SYSTEM",
) -> ResumeEligibilityResult:
    """
    Runs the full eligibility + case-identity + atomic-claim sequence.

    Raises ResumeTraceNotFoundError, ResumeNotEligibleError,
    ResumeCaseIdentityMismatchError, or ResumeClaimConflictError on any
    failure -- never a raw SQLAlchemy/driver exception (the underlying
    repositories already guarantee this via their own PersistenceError
    conventions).
    """
    workflow_run = workflow_repository.get_workflow_run(trace_id)
    if workflow_run is None:
        raise ResumeTraceNotFoundError(
            f"No workflow run found for trace_id={trace_id!r}."
        )

    if workflow_run.workflow_status_code != "PENDING_RESUME":
        raise ResumeNotEligibleError(
            f"workflow_status_code is {workflow_run.workflow_status_code!r}, "
            "expected PENDING_RESUME."
        )
    if workflow_run.next_action_code != "CONTINUE_PROCESSING":
        raise ResumeNotEligibleError(
            f"next_action_code is {workflow_run.next_action_code!r}, "
            "expected CONTINUE_PROCESSING."
        )

    review = human_review_repository.get_completed_review_by_trace_id(trace_id)
    if review is None:
        raise ResumeNotEligibleError(
            f"No completed Human Review found for trace_id={trace_id!r}."
        )
    # get_completed_review_by_trace_id() already filters on
    # review_status_code=COMPLETED at the query level -- this check is
    # structurally redundant but kept as an explicit, self-documenting
    # assertion of the approved eligibility contract's own condition #5.
    if review.review_status_code != HumanReviewStatus.COMPLETED:
        raise ResumeNotEligibleError("Human Review is not COMPLETED.")
    if review.review_outcome_code != HumanReviewOutcome.CONTINUE_WORKFLOW:
        raise ResumeNotEligibleError(
            f"Human Review outcome is {review.review_outcome_code!r}, "
            "expected CONTINUE_WORKFLOW."
        )
    if review.case_id != workflow_run.case_id:
        raise ResumeNotEligibleError(
            "Human Review case_id does not match the workflow run's case_id."
        )

    persisted_case = case_repository.get_case_identity(workflow_run.case_id)
    if persisted_case is None:
        raise ResumeTraceNotFoundError(
            f"No prior_authorization_cases row found for case_id="
            f"{workflow_run.case_id!r}."
        )

    _validate_case_identity(case, persisted_case)

    claim_at_utc = datetime.now(timezone.utc)
    claimed = workflow_repository.claim_workflow_run_for_resume(
        trace_id,
        updated_at_utc=claim_at_utc,
        updated_by=updated_by,
    )
    if not claimed:
        raise ResumeClaimConflictError(
            f"Workflow run {trace_id!r} could not be claimed for resume -- "
            "it may already be claimed, or its state changed since "
            "eligibility was checked."
        )

    claimed_workflow_run = workflow_repository.get_workflow_run(trace_id)

    return ResumeEligibilityResult(
        trace_id=trace_id,
        case_id=workflow_run.case_id,
        workflow_run=claimed_workflow_run,
        review_id=review.review_id,
        review_completed_at_utc=review.completed_at_utc,
    )


def _validate_case_identity(
    supplied: PriorAuthorizationCase, persisted: PersistedCaseIdentity
) -> None:
    """Compares the caller-supplied case against the durable identity
    fields on exactly _CASE_IDENTITY_FIELDS -- never diagnosis_code/
    supporting_documentation/clinical_notes (see module docstring)."""
    mismatched_fields = [
        field
        for field in _CASE_IDENTITY_FIELDS
        if getattr(supplied, field) != getattr(persisted, field)
    ]
    if mismatched_fields:
        raise ResumeCaseIdentityMismatchError(
            "Supplied case identity does not match the persisted case on: "
            f"{', '.join(mismatched_fields)}."
        )


# =====================================================================
# RESUME WORKFLOW (Step 24B-4A)
# Purpose:
# The sole supported application-level end-to-end continuation entry
# point for same-run/same-trace resume. Runs the full authorization
# boundary (validate_and_claim_resume()) and, only if that succeeds,
# continues automated processing on the same trace_id.
#
# Why this is the one entry point callers should use:
# src.workflow.orchestrator._continue_claimed_workflow_processing() is
# an internal helper -- not exported from that module's __all__, and
# not part of the supported public application API. It has its own
# fresh-read precondition check, but that check is a race/staleness
# guard only, not an authorization check (PROCESSING/next_action_code
# is None is not unique to a post-Human-Review resume -- an ordinary
# initial run legitimately passes through that same state). Calling it
# directly, bypassing this function, would skip the actual
# authorization boundary: eligibility validation, the Human Review
# CONTINUE_WORKFLOW check, case-identity validation, and the atomic
# resume claim.
# =====================================================================
def resume_workflow(
    *,
    trace_id: str,
    case: PriorAuthorizationCase,
    completeness_requirements: CompletenessRequirements,
    ai_processing_requirements: AIProcessingRequirements,
    ai_provider: AIAnalysisProvider,
    fhir_client: FHIRStyleClient,
    workflow_repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    case_repository: CaseRepository,
    session_factory: Callable[[], Session],
    updated_by: str = "SYSTEM",
) -> WorkflowRunResult:
    """
    Validates resume eligibility, atomically claims the workflow run,
    and continues automated processing using the SAME trace_id.

    Retains and uses validate_and_claim_resume()'s full result --
    specifically resume_eligibility.review_id, threaded into the
    continuation helper so WORKFLOW_RESUMED's event_id can be
    deterministically derived from the authorizing Human Review
    decision (see _continue_claimed_workflow_processing() and
    _make_event() in src/workflow/orchestrator.py for exactly what that
    does and does not mean -- it is defense-in-depth only, not a new
    AuditEvent schema field, and the PRIMARY duplicate-resume
    protection remains the atomic conditional claim itself).
    resume_eligibility.workflow_run is deliberately NOT passed through
    as a trusted snapshot -- the continuation helper re-reads the row
    fresh and verifies it is still genuinely in the claimed state
    before doing anything, rather than trusting a value that could have
    gone stale between this call and that one.

    Raises ResumeTraceNotFoundError/ResumeNotEligibleError/
    ResumeCaseIdentityMismatchError/ResumeClaimConflictError if
    eligibility or the claim fails; raises OrchestratorError if
    continuation itself fails unsafely after the claim succeeded.
    """
    resume_eligibility = validate_and_claim_resume(
        trace_id=trace_id,
        case=case,
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        updated_by=updated_by,
    )
    return _continue_claimed_workflow_processing(
        trace_id=trace_id,
        review_id=resume_eligibility.review_id,
        case=case,
        completeness_requirements=completeness_requirements,
        ai_processing_requirements=ai_processing_requirements,
        ai_provider=ai_provider,
        fhir_client=fhir_client,
        repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=session_factory,
        updated_by=updated_by,
    )


__all__ = [
    "ResumeTraceNotFoundError",
    "ResumeNotEligibleError",
    "ResumeCaseIdentityMismatchError",
    "ResumeClaimConflictError",
    "ResumeEligibilityResult",
    "validate_and_claim_resume",
    "resume_workflow",
]
