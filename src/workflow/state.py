# File Name: state.py
# Purpose: Defines explicit LangGraph workflow state for Phase 1 deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

import operator
from enum import Enum
from typing import Annotated, TypedDict

from src.ai.contracts import AIAnalysisOutcome
from src.models.ai import AIProcessingRequirements, AIRoutingResult
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements, CompletenessResult

# =====================================================================
# WORKFLOW STATUS
# Purpose:
# Lists every status a case's workflow run can end in.
#
# Why:
# An explicit, named status (instead of a loose string) makes the
# workflow's possible outcomes visible in one place and lets other code
# check the status safely (e.g. `status == WorkflowStatus.COMPLETE`).
#
# Important Notes:
# - COMPLETE does NOT mean clinical approval. It only means the
#   deterministic processing for this case finished with no AI step
#   needed and nothing flagged for human review.
# - AI_ANALYSIS_COMPLETE does NOT mean clinical approval, clinical
#   denial, a payer decision, or a medical necessity decision. It means
#   only that the AI-assisted language-analysis step finished
#   successfully. A human still makes any real decision.
# - HUMAN_REVIEW_REQUIRED is a safety outcome, not a failure of the
#   system — it means a person needs to look at the case.
# - AI_ANALYSIS_REQUIRED is a transient status set while the case is on
#   its way into AI execution; it is not a final resting state in the
#   current single-pass graph.
# =====================================================================


class WorkflowStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    AI_ANALYSIS_REQUIRED = "AI_ANALYSIS_REQUIRED"
    AI_ANALYSIS_COMPLETE = "AI_ANALYSIS_COMPLETE"


# =====================================================================
# CASE WORKFLOW STATE
# Purpose:
# Defines every piece of data that flows through one case's LangGraph
# run: the case itself, the rules it is checked against, the results of
# each deterministic/AI step, and a trace of what happened.
#
# Why:
# LangGraph passes this dictionary-like object between nodes. Declaring
# every field up front (as a TypedDict) makes the whole workflow's data
# shape explicit and inspectable, instead of hidden inside function
# bodies.
#
# Important Notes:
# - This holds workflow/business data only — plain Pydantic models, an
#   enum, a bool, and a list of strings. It does not hold a live AI
#   provider/client object (see src/workflow/nodes.py and graph.py for
#   why the provider is injected separately instead).
# - Keeping this data-only is what makes future persistence and
#   checkpointing possible — everything here is safe to serialize.
#   Persistence itself is NOT implemented yet.
# - processing_steps uses an "add" reducer (Annotated[..., operator.add])
#   so each node can append its own step name and LangGraph merges them
#   in order automatically, without each node needing to know the full
#   history so far.
# =====================================================================


class CaseWorkflowState(TypedDict):
    case: PriorAuthorizationCase
    completeness_requirements: CompletenessRequirements
    completeness_result: CompletenessResult | None
    ai_processing_requirements: AIProcessingRequirements
    ai_routing_result: AIRoutingResult | None
    ai_analysis_outcome: AIAnalysisOutcome | None
    workflow_status: WorkflowStatus
    human_review_required: bool
    processing_steps: Annotated[list[str], operator.add]
