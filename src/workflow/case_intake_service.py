# File Name: case_intake_service.py
# Purpose: Implements the fresh-case intake boundary that validates the requesting client, resolves fresh/duplicate/safe-retry case state, and starts a brand-new workflow run through the existing orchestrator.
# Creation Date: 2026-10-01
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the application-level boundary POST /workflows (src/api/app.py)
# calls into. It owns exactly the fresh-intake decision described by Task
# 25A/25A-2/25A-3: whether a client exists, whether a case_id is genuinely
# new, a genuine duplicate, or a safe retry, and the atomic claim that
# makes concurrent fresh-intake requests for the same case safe. It owns
# NONE of the actual workflow logic -- run_prior_authorization_workflow()
# (src/workflow/orchestrator.py) is called completely unmodified and keeps
# full ownership of LangGraph invocation, FHIR/AI routing, and all of its
# own existing persistence/atomicity guarantees.
#
# WHY A NEW CASE NEEDS AN EXPLICIT CLAIM, NOT JUST A DUPLICATE CHECK:
# run_prior_authorization_workflow() has never created a
# prior_authorization_cases row itself (confirmed directly in its own
# module docstring), and WorkflowRunORM.case_id carries a real
# ForeignKey() to prior_authorization_cases -- so the case row must exist
# before that function's very first write can succeed. This module is
# the one place that case row gets created. A plain "does case_id exist,
# does it have zero workflow runs, does identity match" check is NOT
# enough by itself: two concurrent identical requests could both pass
# that check before either one calls the orchestrator, producing two
# separate trace_ids/workflow_runs for one case. See CASE_STATUS_CODE
# CLAIM below for how this is actually prevented.
#
# CASE_STATUS_CODE CLAIM (reuses an existing, already-approved value --
# no migration, no new reference-data row, no change to
# src/workflow/orchestrator.py):
# case_statuses already defines "IN_PROGRESS" ("Active workflow
# processing"), loaded since Task 22 and never previously set by any
# code path. This module uses it as the fresh-intake claim:
# - A brand-new case is inserted directly as IN_PROGRESS -- the INSERT
#   itself is the claim, and the case_id primary key is what makes two
#   concurrent creates for the same case_id impossible to both succeed
#   (CaseRepository.create_case()).
# - An existing case with zero workflow runs is claimed via a race-safe
#   conditional UPDATE, OPEN -> IN_PROGRESS
#   (CaseRepository.transition_case_status_conditionally()) -- the exact
#   same conditional-UPDATE design already proven in
#   AuditRepository.claim_workflow_run_for_resume() (Task 24), applied
#   to a different column. Only a successful claim may proceed to call
#   run_prior_authorization_workflow(); a failed claim means a
#   concurrent request already won the race, and this request must
#   report a conflict, never retry silently and never start a second
#   run.
#
# COMPENSATION:
# If the claim succeeds but run_prior_authorization_workflow() raises
# before it ever creates a workflow_runs row (its own first write,
# save_workflow_run(), itself failing), the case would otherwise be left
# stuck at IN_PROGRESS with zero runs -- silently reintroducing the exact
# "crash before first write" retry problem the safe-retry rule exists to
# solve. This module checks (from the outside, via
# AuditRepository.case_has_workflow_run() -- no change to orchestrator.py
# needed) whether any run was actually created; if not, it reverts the
# claim (IN_PROGRESS -> OPEN, the same conditional-UPDATE method used in
# reverse) before re-raising the original error. If a run WAS created
# (even a FAILED one), the claim is never reverted -- that case now has
# genuine workflow history, and a later fresh-intake attempt for it must
# conflict, not silently start a second run.
#
# WHAT THIS MODULE DELIBERATELY DOES NOT OWN:
# LangGraph business logic, clinical approval/denial, the FHIR-style
# client's own implementation, the AI provider's own implementation, and
# Human Review internals -- all of that remains entirely in
# src/workflow/orchestrator.py, src/workflow/graph.py,
# src/integrations/fhir_client.py, src/ai/*, and
# src/workflow/human_review_service.py, none of which this module
# changes or duplicates.

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.ai.provider import AIAnalysisProvider
from src.db.case_repository import (
    CaseAlreadyExistsError,
    CaseRepository,
    ClientNotFoundError,
)
from src.db.human_review_repository import HumanReviewRepository
from src.db.repository import AuditRepository
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.workflow.orchestrator import WorkflowRunResult, run_prior_authorization_workflow

_CASE_STATUS_OPEN = "OPEN"
_CASE_STATUS_IN_PROGRESS = "IN_PROGRESS"


# =====================================================================
# START NEW CASE WORKFLOW
# Purpose:
# The sole supported application-level entry point for fresh-case
# workflow start. Validates the requesting client, resolves the
# fresh/duplicate/safe-retry case state (claiming the case for workflow
# processing as part of that resolution), then calls the existing,
# unmodified run_prior_authorization_workflow().
#
# Inputs:
# client_id/case/completeness_requirements/ai_processing_requirements
# are the caller-supplied business inputs (see
# src/models/workflow_api.py's StartWorkflowRequest, which this
# function's keyword arguments mirror exactly). Everything else is a
# server-constructed dependency.
#
# Output / state changes:
# Returns the same WorkflowRunResult run_prior_authorization_workflow()
# itself returns. May create a new prior_authorization_cases row (fresh
# intake) or leave an existing one untouched except for its
# case_status_code claim (safe retry). Never creates more than one
# workflow_runs row per call.
#
# Safety / failure behavior:
# Raises ClientNotFoundError if client_id is not an existing, active,
# non-deleted client. Raises CaseAlreadyExistsError (with a safe
# internal reason_category only -- see that exception's docstring) if
# this case_id cannot be used for a new intake: it already has a
# workflow run, a concurrent request already created or claimed it, or
# it exists with a durable identity that disagrees with this request.
# Any other persistence/orchestrator failure propagates unchanged (its
# own existing exception type), after this function's own claim
# compensation (see module docstring) has already run where applicable.
# =====================================================================
def start_new_case_workflow(
    *,
    client_id: str,
    case: PriorAuthorizationCase,
    completeness_requirements: CompletenessRequirements,
    ai_processing_requirements: AIProcessingRequirements,
    ai_provider: AIAnalysisProvider,
    fhir_client: FHIRStyleClient,
    workflow_repository: AuditRepository,
    human_review_repository: HumanReviewRepository,
    case_repository: CaseRepository,
    session_factory: Callable[[], Session],
    workflow_definition_id: str,
    created_by: str = "SYSTEM",
) -> WorkflowRunResult:
    if not case_repository.client_exists(client_id):
        raise ClientNotFoundError(
            "client_id does not identify an active, non-deleted client."
        )

    existing_identity = case_repository.get_case_intake_identity(case.case_id)

    if existing_identity is None:
        # Fresh case: the INSERT itself is the claim (case_status_code
        # = IN_PROGRESS from the start) -- see module docstring.
        case_repository.create_case(
            case=case,
            client_id=client_id,
            created_by=created_by,
            opened_at_utc=datetime.now(timezone.utc),
        )
    else:
        if workflow_repository.case_has_workflow_run(case.case_id):
            raise CaseAlreadyExistsError("EXISTING_WORKFLOW_RUN")

        identity_matches = (
            existing_identity.client_id == client_id
            and existing_identity.member_id == case.member_id
            and existing_identity.provider_id == case.provider_id
            and existing_identity.requested_service_code
            == case.requested_service_code
            and existing_identity.requested_date == case.requested_date
        )
        if not identity_matches:
            raise CaseAlreadyExistsError("IDENTITY_MISMATCH")

        # Safe retry: the case already exists, no workflow was ever
        # started for it, and every durable field (including
        # client_id) matches this request. Claim it the same race-safe
        # way a fresh case is claimed by creation.
        claimed = case_repository.transition_case_status_conditionally(
            case.case_id,
            expected_status=_CASE_STATUS_OPEN,
            new_status=_CASE_STATUS_IN_PROGRESS,
            updated_at_utc=datetime.now(timezone.utc),
            updated_by=created_by,
        )
        if not claimed:
            # A concurrent request won the claim race between our
            # checks above and this attempt -- a deterministic
            # conflict, never retried silently.
            raise CaseAlreadyExistsError("CASE_CLAIM_CONFLICT")

    try:
        return run_prior_authorization_workflow(
            case=case,
            completeness_requirements=completeness_requirements,
            ai_processing_requirements=ai_processing_requirements,
            ai_provider=ai_provider,
            fhir_client=fhir_client,
            repository=workflow_repository,
            workflow_definition_id=workflow_definition_id,
            case_repository=case_repository,
            human_review_repository=human_review_repository,
            session_factory=session_factory,
            created_by=created_by,
        )
    except Exception:
        _revert_claim_if_no_run_was_created(
            case_repository=case_repository,
            workflow_repository=workflow_repository,
            case_id=case.case_id,
            updated_by=created_by,
        )
        raise


def _revert_claim_if_no_run_was_created(
    *,
    case_repository: CaseRepository,
    workflow_repository: AuditRepository,
    case_id: str,
    updated_by: str,
) -> None:
    """
    Compensation for a workflow-start failure that happened before any
    workflow_runs row was ever created for this case (see module
    docstring). Reverts the IN_PROGRESS claim back to OPEN only when
    that precondition genuinely holds; never reverts a claim for a case
    that already has a real workflow run (even a FAILED one), since
    that case now has genuine history a later fresh-intake attempt must
    see as a conflict, not a clean retry.

    Never hides the original workflow-start exception: this function's
    caller always re-raises it afterward, regardless of whether
    compensation succeeded, was skipped, or was refused.
    """
    if workflow_repository.case_has_workflow_run(case_id):
        return

    case_repository.transition_case_status_conditionally(
        case_id,
        expected_status=_CASE_STATUS_IN_PROGRESS,
        new_status=_CASE_STATUS_OPEN,
        updated_at_utc=datetime.now(timezone.utc),
        updated_by=updated_by,
    )
    # A False return here means the row's state already changed again
    # since the check above (e.g. a run appeared between the check and
    # this call) -- that is itself a safe outcome: the claim is simply
    # left as-is, and a later fresh-intake attempt will correctly see
    # whatever state actually exists now. The original workflow-start
    # exception is still what propagates; this function never raises
    # its own error on top of it.


__all__ = ["start_new_case_workflow"]
