# File Name: nodes.py
# Purpose: Implements the Phase 1 LangGraph workflow nodes that orchestrate existing deterministic completeness rules.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.ai.contracts import AIAnalysisFailureType, AIAnalysisRequest
from src.ai.provider import AIAnalysisProvider
from src.ai.service import run_ai_analysis
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


def build_run_ai_analysis_node(ai_provider: AIAnalysisProvider):
    # The provider is a runtime dependency, not workflow state: it is
    # bound here via closure rather than stored in CaseWorkflowState, so
    # it is never a candidate for future state persistence/checkpointing.
    def run_ai_analysis_node(state: CaseWorkflowState) -> dict:
        case = state["case"]
        routing_result = state["ai_routing_result"]

        # Minimum-necessary input only (see Task 12): the provider
        # receives neither member_id/provider_id nor any other case or
        # audit internals.
        request = AIAnalysisRequest(
            case_id=case.case_id,
            tasks=routing_result.requested_tasks,
            clinical_notes=case.clinical_notes,
        )

        outcome = run_ai_analysis(request, ai_provider)

        processing_steps = ["ai_analysis_executed"]

        if not outcome.success:
            if outcome.failure_type == AIAnalysisFailureType.PROVIDER_FAILED:
                processing_steps.append("ai_provider_failed")
            else:
                processing_steps.append("ai_output_validation_failed")

        return {
            "ai_analysis_outcome": outcome,
            "processing_steps": processing_steps,
        }

    return run_ai_analysis_node


def ai_analysis_complete_node(state: CaseWorkflowState) -> dict:
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.AI_ANALYSIS_COMPLETE,
        "processing_steps": ["ai_analysis_completed"],
    }
