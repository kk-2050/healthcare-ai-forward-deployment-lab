# File Name: graph.py
# Purpose: Builds and compiles the Phase 1 LangGraph workflow graph for deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from langgraph.graph import END, START, StateGraph

from src.ai.provider import AIAnalysisProvider
from src.workflow.nodes import (
    ai_analysis_complete_node,
    ai_analysis_required_node,
    build_run_ai_analysis_node,
    complete_node,
    evaluate_ai_requirement_node,
    evaluate_completeness_node,
    human_review_required_node,
)
from src.workflow.state import CaseWorkflowState


def route_after_completeness(state: CaseWorkflowState) -> str:
    result = state["completeness_result"]

    if result is not None and result.is_complete:
        return "evaluate_ai_requirement"

    return "human_review_required"


def route_after_ai_requirement(state: CaseWorkflowState) -> str:
    result = state["ai_routing_result"]

    if result is not None and result.ai_required:
        return "ai_analysis_required"

    return "complete"


def route_after_ai_analysis(state: CaseWorkflowState) -> str:
    outcome = state["ai_analysis_outcome"]

    if outcome is not None and outcome.success:
        return "ai_analysis_complete"

    return "human_review_required"


def build_case_workflow_graph(ai_provider: AIAnalysisProvider):
    graph = StateGraph(CaseWorkflowState)

    graph.add_node("evaluate_completeness", evaluate_completeness_node)
    graph.add_node("evaluate_ai_requirement", evaluate_ai_requirement_node)
    graph.add_node("complete", complete_node)
    graph.add_node("human_review_required", human_review_required_node)
    graph.add_node("ai_analysis_required", ai_analysis_required_node)
    graph.add_node("run_ai_analysis", build_run_ai_analysis_node(ai_provider))
    graph.add_node("ai_analysis_complete", ai_analysis_complete_node)

    graph.add_edge(START, "evaluate_completeness")
    graph.add_conditional_edges(
        "evaluate_completeness",
        route_after_completeness,
        {
            "evaluate_ai_requirement": "evaluate_ai_requirement",
            "human_review_required": "human_review_required",
        },
    )
    graph.add_conditional_edges(
        "evaluate_ai_requirement",
        route_after_ai_requirement,
        {
            "complete": "complete",
            "ai_analysis_required": "ai_analysis_required",
        },
    )
    graph.add_edge("ai_analysis_required", "run_ai_analysis")
    graph.add_conditional_edges(
        "run_ai_analysis",
        route_after_ai_analysis,
        {
            "ai_analysis_complete": "ai_analysis_complete",
            "human_review_required": "human_review_required",
        },
    )
    graph.add_edge("complete", END)
    graph.add_edge("human_review_required", END)
    graph.add_edge("ai_analysis_complete", END)

    return graph.compile()
