# File Name: case.py
# Purpose: Defines the validated synthetic prior authorization case input model.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class PriorAuthorizationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    requested_service_code: str = Field(min_length=1)
    diagnosis_code: str = Field(min_length=1)
    requested_date: date

    supporting_documentation: list[str] = Field(default_factory=list)
    clinical_notes: str | None = None
