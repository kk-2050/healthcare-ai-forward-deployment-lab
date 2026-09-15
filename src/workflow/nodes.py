# File Name: nodes.py
# Purpose: Implements the Phase 1 LangGraph workflow nodes that orchestrate existing deterministic completeness rules.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.rules.ai_routing import evaluate_ai_requirement
from src.rules.completeness import evaluate_completeness
from src.workflow.state import CaseWorkflowState, WorkflowStatus


def evaluate_completeness_node(state: CaseWorkflowState) -> dict:
    result = evaluate_completeness(
        state["case"], state["completeness_requirements"]
    )

    return {
        "completeness_result": result,
        "processing_steps": ["completeness_evaluated"],
    }


def human_review_required_node(state: CaseWorkflowState) -> dict:
    return {
        "human_review_required": True,
        "workflow_status": WorkflowStatus.HUMAN_REVIEW_REQUIRED,
        "processing_steps": ["human_review_required"],
    }


def complete_node(state: CaseWorkflowState) -> dict:
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.COMPLETE,
        "processing_steps": ["workflow_completed"],
    }


def evaluate_ai_requirement_node(state: CaseWorkflowState) -> dict:
    result = evaluate_ai_requirement(state["ai_processing_requirements"])

    return {
        "ai_routing_result": result,
        "processing_steps": ["ai_requirement_evaluated"],
    }


def ai_analysis_required_node(state: CaseWorkflowState) -> dict:
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.AI_ANALYSIS_REQUIRED,
        "processing_steps": ["ai_analysis_required"],
    }
