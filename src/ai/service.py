# File Name: service.py
# Purpose: Executes an injected AI-analysis provider and validates its output against the Phase 1 AI output contract.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from pydantic import ValidationError

from src.ai.contracts import (
    AIAnalysisFailureType,
    AIAnalysisOutcome,
    AIAnalysisRequest,
    AIAnalysisResult,
)
from src.ai.provider import AIAnalysisProvider


# =====================================================================
# SAFE AI FAILURE ROUTING
# Purpose:
# Runs an injected AI provider and validates whatever it returns,
# turning every possible outcome — success, malformed output, or a
# provider error — into one explicit AIAnalysisOutcome.
#
# Why:
# The workflow must never continue as if AI analysis succeeded when the
# provider failed or returned invalid structured output. Centralizing
# that check here (instead of in the workflow or the API) means every
# caller gets the same safety guarantee for free.
#
# Input:
# - request: the minimum-necessary AIAnalysisRequest to send.
# - provider: any object matching the AIAnalysisProvider protocol
#   (a MockAIAnalysisProvider in tests; a real provider in the future).
#
# Output:
# An AIAnalysisOutcome. success=True only when the provider returned
# data that (a) matches the AIAnalysisResult schema and (b) only claims
# tasks that were actually requested.
#
# Important Notes:
# - Never create a fabricated fallback AI result. Every failure path
#   below returns result=None.
# - Raw exception text and raw invalid provider output are never placed
#   in error_message — only a short, generic, safe message.
# =====================================================================
def run_ai_analysis(
    request: AIAnalysisRequest,
    provider: AIAnalysisProvider,
) -> AIAnalysisOutcome:
    """
    Calls the provider and validates its output.

    Returns an AIAnalysisOutcome describing success, or one of the two
    AIAnalysisFailureType failures (PROVIDER_FAILED or
    OUTPUT_VALIDATION_FAILED). Never raises — callers can rely on
    always getting back a structured outcome.
    """
    try:
        raw_output = provider.analyze(request)
    except Exception:
        # Raw exception details are never surfaced: they may carry provider
        # internals (stack traces, request context) that should not reach
        # a user-facing result.
        return AIAnalysisOutcome(
            success=False,
            result=None,
            failure_type=AIAnalysisFailureType.PROVIDER_FAILED,
            error_message="The AI provider failed to return a response.",
        )

    try:
        result = AIAnalysisResult.model_validate(raw_output)
    except ValidationError:
        return AIAnalysisOutcome(
            success=False,
            result=None,
            failure_type=AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED,
            error_message="The AI provider output failed structured validation.",
        )

    # A supported AITask enum value is not automatically authorized for
    # this request: the provider may only report tasks it was actually
    # asked to perform, never additional ones of its own choosing.
    if not set(result.completed_tasks).issubset(request.tasks):
        return AIAnalysisOutcome(
            success=False,
            result=None,
            failure_type=AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED,
            error_message="The AI provider output failed structured validation.",
        )

    return AIAnalysisOutcome(success=True, result=result)
