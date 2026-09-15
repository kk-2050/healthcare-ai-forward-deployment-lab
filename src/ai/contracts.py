# File Name: contracts.py
# Purpose: Defines validated input and output contracts for Phase 1 AI-assisted language analysis.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.models.ai import AITask


class AIAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    tasks: list[AITask]
    clinical_notes: str | None = None


class AIAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # completed_tasks has no default: the provider must always state
    # explicitly which approved tasks it actually completed, rather than
    # this silently defaulting to "none completed" when omitted.
    completed_tasks: list[AITask]
    summary: str | None = None
    ambiguities: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class AIAnalysisFailureType(str, Enum):
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


class AIAnalysisOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    result: AIAnalysisResult | None = None
    failure_type: AIAnalysisFailureType | None = None
    error_message: str | None = None
