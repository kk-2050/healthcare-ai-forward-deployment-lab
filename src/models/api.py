# File Name: api.py
# Purpose: Defines the request/response contract models for the Phase 1 case validation API endpoint.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from pydantic import BaseModel, ConfigDict

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements


class CaseValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: PriorAuthorizationCase
    requirements: CompletenessRequirements


class CaseValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    is_complete: bool
    missing_fields: list[str]
    missing_documentation: list[str]
