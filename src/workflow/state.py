# File Name: state.py
# Purpose: Defines explicit LangGraph workflow state for Phase 1 deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

import operator
from enum import Enum
from typing import Annotated, TypedDict

from src.models.ai import AIProcessingRequirements, AIRoutingResult
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements, CompletenessResult


class WorkflowStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    AI_ANALYSIS_REQUIRED = "AI_ANALYSIS_REQUIRED"


class CaseWorkflowState(TypedDict):
    case: PriorAuthorizationCase
    completeness_requirements: CompletenessRequirements
    completeness_result: CompletenessResult | None
    ai_processing_requirements: AIProcessingRequirements
    ai_routing_result: AIRoutingResult | None
    workflow_status: WorkflowStatus
    human_review_required: bool
    processing_steps: Annotated[list[str], operator.add]
