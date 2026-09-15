# File Name: contracts.py
# Purpose: Defines validated input and output contracts for Phase 1 AI-assisted language analysis.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.models.ai import AITask

# =====================================================================
# AI ANALYSIS REQUEST
# Purpose:
# Defines the narrow set of information sent to an AI provider.
#
# Why:
# Only the minimum information needed for approved language tasks is
# sent — never the whole case, never member_id/provider_id, never
# database or audit internals. This limits what any AI provider
# (mocked now, Azure later) can ever see.
# =====================================================================


class AIAnalysisRequest(BaseModel):
    """
    The minimum-necessary input sent to an AI analysis provider.

    Deliberately narrow: case_id (to trace the result back to a case),
    the approved tasks to perform, and the clinical notes text those
    tasks operate on. Nothing else.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    tasks: list[AITask]
    clinical_notes: str | None = None


# =====================================================================
# AI ANALYSIS RESULT
# Purpose:
# Defines the only shape of structured output an AI provider is allowed
# to return.
#
# Why:
# AI output must never be trusted as-is. Every field here is AI-
# generated language analysis, not verified clinical fact, a payer
# rule, or an approval/denial. Keeping the fields limited to
# summarization/ambiguity/inconsistency/clarifying-question output
# makes that boundary explicit in the data model itself.
#
# Important Notes:
# This model intentionally has no approval, denial, medical_necessity,
# coverage_decision, treatment_recommendation, risk_score, or
# confidence field. Do not add one without updating the project's
# human-in-the-loop safety design first.
# =====================================================================


class AIAnalysisResult(BaseModel):
    """
    Structured, AI-generated language analysis for one case.

    Every field is an AI-assisted observation or suggestion, not a
    verified clinical finding, a payer rule, or a decision.
    """

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
    """
    The two ways an AI analysis attempt can fail.

    OUTPUT_VALIDATION_FAILED: the provider responded, but its output
    did not match AIAnalysisResult (or claimed a task it was not asked
    to do).
    PROVIDER_FAILED: the provider itself raised an error (e.g., a
    timeout or service error) before returning any output.
    """

    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


class AIAnalysisOutcome(BaseModel):
    """
    The validated outcome of one AI analysis attempt.

    Keeps a successful AIAnalysisResult clearly separate from a
    provider or output-validation failure, so callers (including the
    LangGraph workflow) can route failures safely instead of guessing
    from a partial or malformed result.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    result: AIAnalysisResult | None = None
    failure_type: AIAnalysisFailureType | None = None

    # A short, generic message only. This must never contain raw
    # provider exception text, stack traces, or other internals — see
    # src/ai/service.py, which is the only place this field is set.
    error_message: str | None = None
