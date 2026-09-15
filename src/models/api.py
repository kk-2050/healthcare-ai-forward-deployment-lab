# File Name: api.py
# Purpose: Defines the request/response contract models for the Phase 1 case validation API endpoint.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from pydantic import BaseModel, ConfigDict

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements

# =====================================================================
# API REQUEST/RESPONSE CONTRACT
# Purpose:
# Defines exactly what the /cases/validate endpoint accepts
# (CaseValidationRequest) and returns (CaseValidationResponse).
#
# Why:
# Reusing PriorAuthorizationCase and CompletenessRequirements here
# (instead of redefining similar fields) keeps one single source of
# truth for what a "case" and "requirements" look like across the API
# and the rest of the project.
#
# Important Notes:
# The response reports completeness facts only. It does not represent
# an approval, a denial, or a medical necessity decision.
# =====================================================================


class CaseValidationRequest(BaseModel):
    """
    The request body for POST /cases/validate.

    Bundles a case together with the completeness requirements it
    should be checked against.
    """

    model_config = ConfigDict(extra="forbid")

    case: PriorAuthorizationCase
    requirements: CompletenessRequirements


class CaseValidationResponse(BaseModel):
    """
    The response body for POST /cases/validate.

    Reports the deterministic completeness result for the submitted
    case. This is not a clinical or payer decision — see
    src/api/app.py for what the endpoint does and does not do.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    is_complete: bool
    missing_fields: list[str]
    missing_documentation: list[str]
