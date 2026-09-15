# File Name: ai_routing.py
# Purpose: Implements the deterministic rule for whether explicitly approved AI-assisted analysis is required.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.models.ai import AIProcessingRequirements, AIRoutingResult


# =====================================================================
# AI ROUTING
# Purpose:
# Determines whether one of the approved AI language-analysis tasks is
# needed for a case, based only on what was explicitly requested.
#
# Why:
# AI is used only when language understanding or ambiguity requires
# it — never "just in case". This function is the single, simple
# switch that decides that, so nothing downstream has to guess.
#
# Input:
# requirements: an AIProcessingRequirements listing zero or more
# approved AITask values that were explicitly requested for this case.
#
# Output:
# An AIRoutingResult recording whether AI is required and exactly
# which tasks were requested.
#
# Important Notes:
# - AI routing is not a clinical decision. It only decides whether a
#   language-analysis step should run later.
# - Only tasks defined in the AITask enum are ever allowed; anything
#   else is already rejected by Pydantic before this function runs.
# - This function does not detect ambiguity itself and does not call
#   an LLM — it only reads the explicit request.
# - Incomplete cases must be routed to human review before this
#   function is ever reached (see src/workflow/graph.py).
# =====================================================================
def evaluate_ai_requirement(requirements: AIProcessingRequirements) -> AIRoutingResult:
    """
    Decides whether AI-assisted analysis is required for a case.

    ai_required is True only when at least one approved task was
    requested; an empty task list means AI is not needed.
    """
    ai_required = len(requirements.tasks) > 0

    return AIRoutingResult(
        ai_required=ai_required,
        requested_tasks=list(requirements.tasks),
    )
