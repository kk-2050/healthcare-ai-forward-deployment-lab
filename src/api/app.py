# File Name: app.py
# Purpose: Exposes the Phase 1 FastAPI backend boundary for deterministic case validation/completeness evaluation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from fastapi import FastAPI

from src.models.api import CaseValidationRequest, CaseValidationResponse
from src.rules.completeness import evaluate_completeness

# =====================================================================
# APPLICATION
# Purpose:
# Creates the FastAPI application used by the Phase 1 API.
#
# Why:
# This object defines the HTTP entry point for case validation
# requests. It is the only place in the project where an HTTP request
# is received.
#
# Important Notes:
# The current API does not make clinical approval or denial decisions.
# It exposes deterministic completeness checking only — it does not yet
# run the LangGraph workflow, call the AI service, or touch a database.
# =====================================================================
app = FastAPI(title="Healthcare AI Forward Deployment Lab - Phase 1 API")


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
