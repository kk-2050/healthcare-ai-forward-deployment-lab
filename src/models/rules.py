# File Name: rules.py
# Purpose: Defines the input requirements and output result models for deterministic case completeness evaluation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from pydantic import BaseModel, ConfigDict, Field


class CompletenessRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    required_documentation: list[str] = Field(default_factory=list)
    clinical_notes_required: bool = False


class CompletenessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_fields: list[str] = Field(default_factory=list)
    missing_documentation: list[str] = Field(default_factory=list)
    is_complete: bool
