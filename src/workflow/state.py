# File Name: state.py
# Purpose: Defines explicit LangGraph workflow state for Phase 1 deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

import operator
from enum import Enum
from typing import Annotated, TypedDict

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements, CompletenessResult


class WorkflowStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class CaseWorkflowState(TypedDict):
    case: PriorAuthorizationCase
    completeness_requirements: CompletenessRequirements
    completeness_result: CompletenessResult | None
    workflow_status: WorkflowStatus
    human_review_required: bool
    processing_steps: Annotated[list[str], operator.add]
