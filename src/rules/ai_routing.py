# File Name: ai_routing.py
# Purpose: Implements the deterministic rule for whether explicitly approved AI-assisted analysis is required.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.models.ai import AIProcessingRequirements, AIRoutingResult


def evaluate_ai_requirement(requirements: AIProcessingRequirements) -> AIRoutingResult:
    ai_required = len(requirements.tasks) > 0

    return AIRoutingResult(
        ai_required=ai_required,
        requested_tasks=list(requirements.tasks),
    )
