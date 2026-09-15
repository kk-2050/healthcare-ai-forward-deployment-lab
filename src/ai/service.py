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


def run_ai_analysis(
    request: AIAnalysisRequest,
    provider: AIAnalysisProvider,
) -> AIAnalysisOutcome:
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
