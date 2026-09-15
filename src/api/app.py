# File Name: app.py
# Purpose: Exposes the Phase 1 FastAPI backend boundary for deterministic case validation/completeness evaluation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from fastapi import FastAPI

from src.models.api import CaseValidationRequest, CaseValidationResponse
from src.rules.completeness import evaluate_completeness

app = FastAPI(title="Healthcare AI Forward Deployment Lab - Phase 1 API")


@app.post("/cases/validate", response_model=CaseValidationResponse)
def validate_case(request: CaseValidationRequest) -> CaseValidationResponse:
    result = evaluate_completeness(request.case, request.requirements)

    return CaseValidationResponse(
        case_id=request.case.case_id,
        is_complete=result.is_complete,
        missing_fields=result.missing_fields,
        missing_documentation=result.missing_documentation,
    )
