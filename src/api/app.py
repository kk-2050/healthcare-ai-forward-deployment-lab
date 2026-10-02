# File Name: app.py
# Purpose: Exposes the Phase 1 FastAPI backend boundary for deterministic case validation/completeness evaluation and Human Review decision submission.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.ai.provider import AIAnalysisProvider
from src.api.dependencies import (
    FHIRIntegrationNotConfiguredError,
    get_ai_provider,
    get_case_repository,
    get_fhir_client,
    get_human_review_repository,
    get_session_factory,
    get_workflow_repository,
)
from src.db.case_repository import (
    CaseAlreadyExistsError,
    CaseRepository,
    ClientNotFoundError,
    PersistenceError as CasePersistenceError,
)
from src.db.human_review_repository import (
    HumanReviewConflictError,
    HumanReviewRepository,
    PersistenceError as HumanReviewPersistenceError,
)
from src.db.reference_data import workflow_definition_id
from src.db.repository import AuditEventConflictError, AuditRepository, PersistenceError
from src.integrations.fhir_client import FHIRStyleClient
from src.models.api import CaseValidationRequest, CaseValidationResponse
from src.models.human_review_api import (
    HumanReviewDecisionRequest,
    HumanReviewDecisionResponse,
)
from src.models.resume_api import ResumeWorkflowRequest, ResumeWorkflowResponse
from src.models.workflow_api import StartWorkflowRequest, StartWorkflowResponse
from src.rules.completeness import evaluate_completeness
from src.workflow.case_intake_service import start_new_case_workflow
from src.workflow.human_review_service import (
    InvalidCloseReasonError,
    ResumeError,
    resume_after_human_review,
)
from src.workflow.orchestrator import OrchestratorError
from src.workflow.resume_service import (
    ResumeCaseIdentityMismatchError,
    ResumeClaimConflictError,
    ResumeNotEligibleError,
    ResumeTraceNotFoundError,
    resume_workflow,
)

# =====================================================================
# APPLICATION
# Purpose:
# Creates the FastAPI application used by the Phase 1 API.
#
# Why:
# This object defines the HTTP entry points this project receives. The
# case-validation endpoint below does not make clinical approval or
# denial decisions, and never touches a database. The Human Review
# decision endpoint (Task 23C-7A) is the project's first
# database-touching endpoint -- it persists an already-recorded human
# decision through the existing resume_after_human_review() service; it
# does not decide anything itself and does not run the LangGraph
# workflow.
#
# Important Notes:
# - Phase 1 has NO authentication/authorization layer. Neither endpoint
#   verifies caller identity. For the Human Review decision endpoint,
#   reviewer_actor_type_code/reviewer_reference are supplied directly in
#   the request body by the caller -- exactly as every existing
#   offline/real-SQL Human Review test already does. Adding real
#   authentication is a known, tracked productionization item, not
#   implemented here, and not claimed as implemented.
# =====================================================================
app = FastAPI(title="Healthcare AI Forward Deployment Lab - Phase 1 API")


# =====================================================================
# FHIR INTEGRATION NOT CONFIGURED HANDLER (Task 24B-4C)
# Purpose:
# Maps FHIRIntegrationNotConfiguredError -- raised by
# get_fhir_client()'s fail-closed default (src/api/dependencies.py) --
# to a fixed, safe HTTP response.
#
# Why a dedicated exception handler, not a try/except in the route:
# FastAPI resolves every Depends() dependency BEFORE the route
# function body runs. get_fhir_client() raises while FastAPI is still
# resolving dependencies for POST /workflows/{trace_id}/resume, so the
# exception never reaches that route function's own try/except (which
# only wraps the resume_workflow() call itself) -- this module-level
# handler is the only mechanism that can intercept it.
#
# Why 503, not 500:
# This is a deliberate, known, already-documented "this integration is
# not yet configured/approved" condition (see
# src/api/dependencies.py's get_fhir_client() docstring) -- not an
# unexpected internal failure. 503 Service Unavailable is the accurate
# status for "this dependency is intentionally not available yet."
#
# Important Notes:
# - This handler is registered for exactly ONE exception type. It does
#   not touch, override, or broaden handling of any other exception --
#   HTTPException and every other unhandled exception in this app
#   continue to be handled exactly as before this change.
# - The response body is a fixed string. It never includes str(exc),
#   any base_url, any header, or any other configuration/secret value.
# =====================================================================
@app.exception_handler(FHIRIntegrationNotConfiguredError)
def handle_fhir_integration_not_configured(
    request: Request, exc: FHIRIntegrationNotConfiguredError
) -> JSONResponse:
    """Returns a fixed, safe 503 response for the FHIR fail-closed
    dependency -- never the raised exception's own message."""
    return JSONResponse(
        status_code=503,
        content={"detail": "Live FHIR-style integration is not available."},
    )


# =====================================================================
# CASE VALIDATION ENDPOINT
# Purpose:
# Accepts a synthetic case plus completeness requirements, validates
# the request with Pydantic, and reports whether the case is complete.
#
# Why:
# This keeps the API a thin transport boundary: FastAPI/Pydantic handle
# the HTTP contract, and the actual completeness logic lives in
# src/rules/completeness.py so it is not duplicated here.
#
# Input:
# A CaseValidationRequest (validated automatically by FastAPI/Pydantic
# before this function runs — a malformed request never reaches here).
#
# Output:
# A CaseValidationResponse reporting is_complete plus exactly what (if
# anything) is missing.
#
# Important Notes:
# - This endpoint does not call an LLM and does not decide approval or
#   denial — it only reports deterministic completeness facts.
# - Business/completeness rules are not duplicated here; they are
#   reused from src/rules/completeness.py.
# =====================================================================
@app.post("/cases/validate", response_model=CaseValidationResponse)
def validate_case(request: CaseValidationRequest) -> CaseValidationResponse:
    """
    Validates a case's completeness against the supplied requirements.

    Pydantic has already rejected malformed input (missing fields,
    wrong types, unknown fields) by the time this function runs.
    """
    result = evaluate_completeness(request.case, request.requirements)

    return CaseValidationResponse(
        case_id=request.case.case_id,
        is_complete=result.is_complete,
        missing_fields=result.missing_fields,
        missing_documentation=result.missing_documentation,
    )


# =====================================================================
# HUMAN REVIEW DECISION ENDPOINT (Task 23C-7A)
# Purpose:
# Accepts an already-made human reviewer decision for an existing
# pending Human Review request, and persists it through the existing
# resume_after_human_review() service -- the ONLY place this project's
# outcome-to-state business logic lives. This endpoint never decides
# anything itself.
#
# Why:
# This is a thin transport boundary, matching validate_case() above:
# FastAPI/Pydantic handle input shape and the four-outcome type
# constraint (HumanReviewDecisionRequest.review_outcome_code is typed as
# the real HumanReviewOutcome enum, so no clinical approve/deny value
# can ever reach this function); this function's only remaining job is
# to invoke the service exactly once and translate its already-defined
# domain/persistence exceptions into HTTP responses.
#
# Important Notes:
# - This endpoint does NOT resume LangGraph, does NOT invoke any
#   continuation graph, does NOT emit WORKFLOW_RESUMED, and does NOT
#   create a new workflow run or trace_id -- resume_after_human_review()
#   itself guarantees all of that (see its own module docstring in
#   src/workflow/human_review_service.py); this endpoint adds nothing
#   on top of it.
# - For CONTINUE_WORKFLOW specifically: the response reflects the
#   already-approved PENDING_RESUME/CONTINUE_PROCESSING state with
#   completed_at_utc left null -- this endpoint does not claim the
#   workflow actually continued. True post-review continuation is
#   Task 24's scope, not this endpoint's.
# - Error mapping (see below): ResumeError (unknown review_id/trace_id)
#   -> 404; InvalidCloseReasonError (invalid CLOSE_CASE input) -> 422;
#   HumanReviewConflictError/AuditEventConflictError (state already
#   disagrees with this request) -> 409; any persistence failure -> 500
#   with a fixed, safe message (these repositories' own PersistenceError
#   types are already designed to never carry raw driver text, but a
#   fixed message is used here regardless, as an extra margin). No
#   exception is ever caught and converted into a false-success 200
#   response.
# =====================================================================
@app.post(
    "/human-review/decisions",
    response_model=HumanReviewDecisionResponse,
)
def submit_human_review_decision(
    request: HumanReviewDecisionRequest,
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    workflow_repository: AuditRepository = Depends(get_workflow_repository),
    human_review_repository: HumanReviewRepository = Depends(get_human_review_repository),
    case_repository: CaseRepository = Depends(get_case_repository),
) -> HumanReviewDecisionResponse:
    """
    Persists an already-made Human Review decision for an existing
    pending review, via the existing resume_after_human_review()
    service.

    Pydantic has already rejected malformed input (missing fields,
    wrong types, an outcome outside the four approved values) by the
    time this function runs.
    """
    try:
        result = resume_after_human_review(
            review_id=request.review_id,
            review_outcome_code=request.review_outcome_code,
            reviewer_actor_type_code=request.reviewer_actor_type_code,
            reviewer_reference=request.reviewer_reference,
            decision_at_utc=request.decision_at_utc,
            session_factory=session_factory,
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            review_note_text=request.review_note_text,
            close_reason_code=request.close_reason_code,
            close_reason_text=request.close_reason_text,
            updated_by=request.updated_by,
        )
    except ResumeError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidCloseReasonError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (HumanReviewConflictError, AuditEventConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (HumanReviewPersistenceError, PersistenceError, CasePersistenceError) as error:
        raise HTTPException(
            status_code=500,
            detail="The Human Review decision could not be persisted.",
        ) from error

    return HumanReviewDecisionResponse(
        review=result.review,
        workflow_run=result.workflow_run,
        audit_events=result.audit_events,
    )


# =====================================================================
# WORKFLOW RESUME ENDPOINT (Task 24B-4C)
# Purpose:
# Continues an eligible workflow run on the SAME trace_id through
# resume_workflow(), which validates and atomically claims the run
# before continuation (src/workflow/resume_service.py) -- the sole
# supported application-level end-to-end continuation entry point
# (Task 24B-4A).
#
# Why:
# This is a thin transport boundary, matching validate_case() and
# submit_human_review_decision() above: FastAPI/Pydantic handle input
# shape, and this function's only remaining job is to invoke
# resume_workflow() exactly once and translate its already-defined
# domain/persistence exceptions into HTTP responses. It owns NONE of
# the actual resume business logic -- eligibility validation, the
# Human Review CONTINUE_WORKFLOW check, case-identity validation, the
# atomic resume claim, graph continuation, WORKFLOW_RESUMED creation,
# and all persistence belong entirely to resume_workflow() and the
# functions it calls (validate_and_claim_resume(),
# _continue_claimed_workflow_processing()) -- never duplicated here.
#
# Important Notes:
# - trace_id comes ONLY from the URL path -- it identifies the
#   EXISTING workflow run being resumed. This endpoint never
#   generates a trace_id and never creates a new workflow run; it can
#   only continue a run that already exists and is already eligible
#   (enforced entirely inside resume_workflow()).
# - The response never includes WorkflowRunResult.final_state -- see
#   src/models/resume_api.py for why (raw re-supplied case content,
#   raw FHIR evidence, and raw AI output all live there). Only the
#   canonical workflow_run/audit_events shape is returned, and
#   case_id is read from the persisted workflow_run, not from the
#   request, so the response always reflects the durable record.
# - The response-shaping read (workflow_repository.get_workflow_run())
#   runs inside the same try block as resume_workflow(), so a
#   repository failure there is caught by the same safe
#   PersistenceError -> fixed 500 mapping below. If that read
#   unexpectedly returns None, this function returns a fixed, safe 500
#   without attempting any compensation or rollback -- resume_workflow()
#   has already committed its result by that point, and this failure
#   is only about building the HTTP response, not about workflow state.
# - get_fhir_client()/get_ai_provider() are resolved lazily, per
#   request, by FastAPI's own Depends() mechanism -- neither is called
#   merely by importing or registering this route. get_fhir_client()
#   fails closed by default (see src/api/dependencies.py); a real
#   request that reaches it without an override is turned into a
#   fixed 503 by this module's exception handler above, before
#   resume_workflow() is ever called.
# - Error mapping below: ResumeTraceNotFoundError -> 404;
#   ResumeNotEligibleError/ResumeCaseIdentityMismatchError/
#   ResumeClaimConflictError -> 409 (new Phase 1 API design choices,
#   modeled directly on the existing ResumeError->404 and
#   HumanReviewConflictError->409 precedent below);
#   HumanReviewConflictError/AuditEventConflictError -> 409 (existing
#   precedent, unchanged); any persistence failure or OrchestratorError
#   -> 500 with a fixed, safe message (existing precedent's posture).
#   No exception is ever caught and converted into a false-success 200
#   response.
# - Phase 1 has no authentication/authorization layer (see this
#   module's docstring above). updated_by is left at resume_workflow()'s
#   own server default ("SYSTEM") -- this request has no reviewer-
#   identity field at all, unlike the Human Review decision endpoint.
# =====================================================================
@app.post(
    "/workflows/{trace_id}/resume",
    response_model=ResumeWorkflowResponse,
)
def resume_workflow_endpoint(
    trace_id: str,
    request: ResumeWorkflowRequest,
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    workflow_repository: AuditRepository = Depends(get_workflow_repository),
    human_review_repository: HumanReviewRepository = Depends(get_human_review_repository),
    case_repository: CaseRepository = Depends(get_case_repository),
    fhir_client: FHIRStyleClient = Depends(get_fhir_client),
    ai_provider: AIAnalysisProvider = Depends(get_ai_provider),
) -> ResumeWorkflowResponse:
    """
    Continues an eligible workflow run on the SAME trace_id through
    resume_workflow(), which validates and atomically claims the run
    before continuation.

    Pydantic has already rejected malformed input (missing fields,
    wrong types, unknown fields) by the time this function runs.
    """
    try:
        result = resume_workflow(
            trace_id=trace_id,
            case=request.case,
            completeness_requirements=request.completeness_requirements,
            ai_processing_requirements=request.ai_processing_requirements,
            ai_provider=ai_provider,
            fhir_client=fhir_client,
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=session_factory,
        )
        workflow_run = workflow_repository.get_workflow_run(result.trace_id)
    except ResumeTraceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        ResumeNotEligibleError,
        ResumeCaseIdentityMismatchError,
        ResumeClaimConflictError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (HumanReviewConflictError, AuditEventConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (HumanReviewPersistenceError, PersistenceError, CasePersistenceError) as error:
        raise HTTPException(
            status_code=500,
            detail="The workflow resume could not be persisted.",
        ) from error
    except OrchestratorError as error:
        raise HTTPException(
            status_code=500,
            detail="Workflow continuation could not complete.",
        ) from error

    if workflow_run is None:
        # Defensive guard only -- resume_workflow() has already
        # committed its continuation successfully by this point (any
        # failure there would have raised one of the exceptions above
        # instead of reaching here). A missing row at this read would
        # mean something unexpected happened outside resume_workflow()'s
        # own atomic persistence helpers, which are designed to prevent
        # exactly this. This is a response-shaping failure only: no
        # compensation, rollback, or rewrite of already-persisted
        # workflow state is attempted here -- the row resume_workflow()
        # left behind is not touched; this request simply reports that
        # its own HTTP response could not be safely built.
        raise HTTPException(
            status_code=500,
            detail="The workflow resume response could not be built.",
        )

    return ResumeWorkflowResponse(
        trace_id=result.trace_id,
        case_id=workflow_run.case_id,
        workflow_run=workflow_run,
        audit_events=result.audit_events,
    )


# =====================================================================
# FRESH-CASE WORKFLOW START ENDPOINT (Task 25B)
# Purpose:
# Starts a brand-new workflow run for a fresh (or safely-retried) case
# intake, via start_new_case_workflow() -- the sole supported
# application-level entry point for this boundary
# (src/workflow/case_intake_service.py).
#
# Why:
# This is a thin transport boundary, matching every other endpoint
# above: FastAPI/Pydantic handle input shape, and this function's only
# remaining job is to invoke the service exactly once and translate its
# already-defined domain/persistence exceptions into HTTP responses. It
# owns NONE of the actual intake/claim/workflow logic -- client
# validation, duplicate/safe-retry resolution, the atomic case claim,
# claim compensation, and graph execution all belong entirely to
# start_new_case_workflow() and the functions it calls -- never
# duplicated here.
#
# Important Notes:
# - client_id must identify an existing, active, non-deleted client --
#   this endpoint never creates one.
# - trace_id comes ONLY from the application: this endpoint never
#   accepts one from the caller and always starts a genuinely new run
#   (or, for a safe retry, continues an existing case with zero prior
#   workflow runs -- never a second run for a case that already has
#   one).
# - The response never includes WorkflowRunResult.final_state -- see
#   src/models/workflow_api.py for why. case_id is read from the
#   persisted workflow_run, not merely echoed from the request.
# - The response-shaping read (workflow_repository.get_workflow_run())
#   runs inside the same try block as start_new_case_workflow(), so a
#   repository failure there is caught by the same safe
#   PersistenceError -> fixed 500 mapping below, exactly mirroring the
#   Resume endpoint's own defensive pattern.
# - Error mapping below: ClientNotFoundError -> 404;
#   CaseAlreadyExistsError -> 409, with a single FIXED public message
#   regardless of its internal reason_category -- the category (which
#   field mismatched, whether another client owns the case, etc.) is
#   never exposed to the caller; any persistence failure or
#   OrchestratorError -> 500 with a fixed, safe message. No exception
#   is ever caught and converted into a false-success 2xx response.
# - get_fhir_client()/get_ai_provider() are resolved lazily, per
#   request, by FastAPI's own Depends() mechanism, exactly as the
#   Resume endpoint already does -- get_fhir_client() fails closed by
#   default (src/api/dependencies.py), turned into a fixed 503 by this
#   module's existing exception handler above, before
#   start_new_case_workflow() is ever called.
# - Phase 1 has no authentication/authorization layer. No caller
#   identity field exists on this request beyond client_id, which
#   identifies an existing business client, not a human caller.
# =====================================================================
@app.post(
    "/workflows",
    response_model=StartWorkflowResponse,
    status_code=201,
)
def start_workflow_endpoint(
    request: StartWorkflowRequest,
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    workflow_repository: AuditRepository = Depends(get_workflow_repository),
    human_review_repository: HumanReviewRepository = Depends(get_human_review_repository),
    case_repository: CaseRepository = Depends(get_case_repository),
    fhir_client: FHIRStyleClient = Depends(get_fhir_client),
    ai_provider: AIAnalysisProvider = Depends(get_ai_provider),
) -> StartWorkflowResponse:
    """
    Starts a brand-new workflow run for a fresh case submission, via
    start_new_case_workflow().

    Pydantic has already rejected malformed input (missing fields,
    wrong types, unknown fields) by the time this function runs.
    """
    try:
        result = start_new_case_workflow(
            client_id=request.client_id,
            case=request.case,
            completeness_requirements=request.completeness_requirements,
            ai_processing_requirements=request.ai_processing_requirements,
            ai_provider=ai_provider,
            fhir_client=fhir_client,
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=session_factory,
            workflow_definition_id=workflow_definition_id(),
        )
        workflow_run = workflow_repository.get_workflow_run(result.trace_id)
    except ClientNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="The specified client could not be found."
        ) from error
    except CaseAlreadyExistsError as error:
        raise HTTPException(
            status_code=409,
            detail="This case_id already exists and cannot be used for a new intake.",
        ) from error
    except (HumanReviewPersistenceError, PersistenceError, CasePersistenceError) as error:
        raise HTTPException(
            status_code=500,
            detail="The case/workflow could not be persisted.",
        ) from error
    except OrchestratorError as error:
        raise HTTPException(
            status_code=500,
            detail="Workflow execution could not complete.",
        ) from error

    if workflow_run is None:
        raise HTTPException(
            status_code=500,
            detail="The workflow start response could not be built.",
        )

    return StartWorkflowResponse(
        trace_id=result.trace_id,
        case_id=workflow_run.case_id,
        workflow_run=workflow_run,
        audit_events=result.audit_events,
    )
