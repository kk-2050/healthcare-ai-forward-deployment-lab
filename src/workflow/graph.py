# File Name: graph.py
# Purpose: Builds and compiles the Phase 1 LangGraph workflow graph for deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# This file wires the nodes in src/workflow/nodes.py together into one
# explicit graph, using LangGraph's StateGraph. It defines every path a
# case can take:
#
#   Incomplete case            -> HUMAN_REVIEW_REQUIRED
#   Complete case, no AI task  -> COMPLETE
#   Complete case, AI task     -> AI analysis
#     AI success                 -> AI_ANALYSIS_COMPLETE
#     AI provider failure         -> HUMAN_REVIEW_REQUIRED
#     Malformed AI output         -> HUMAN_REVIEW_REQUIRED
#
# All routing below is deterministic: each routing function reads a
# plain field already stored in state (e.g. `result.is_complete`,
# `outcome.success`) and returns a fixed next-step name. The AI's
# free-form text content is never inspected to choose a route.

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
    """
    Routes the case after the completeness check.

    Complete cases continue to the AI-routing step. Incomplete cases go
    straight to human review and never reach AI routing or execution.
    """
    result = state["completeness_result"]

    if result is not None and result.is_complete:
        return "evaluate_ai_requirement"

    return "human_review_required"


def route_after_ai_requirement(state: CaseWorkflowState) -> str:
    """
    Routes the case after the AI-needed check.

    No requested AI task means processing is already finished
    (COMPLETE). A requested task means AI analysis must run next.
    """
    result = state["ai_routing_result"]

    if result is not None and result.ai_required:
        return "ai_analysis_required"

    return "complete"


def route_after_ai_analysis(state: CaseWorkflowState) -> str:
    """
    Routes the case after AI analysis.

    Successful analysis continues to AI_ANALYSIS_COMPLETE. Both a
    provider failure and invalid/unauthorized AI output are treated the
    same way here — they safely go to human review. See
    src/workflow/nodes.py (build_run_ai_analysis_node) for how the two
    failure types are still recorded separately in processing_steps.
    """
    outcome = state["ai_analysis_outcome"]

    if outcome is not None and outcome.success:
        return "ai_analysis_complete"

    return "human_review_required"


# =====================================================================
# WORKFLOW GRAPH CONSTRUCTION
# Purpose:
# Builds one compiled LangGraph graph, wired to a specific AI provider.
#
# Why:
# The AI provider (a MockAIAnalysisProvider in tests, a real provider
# in the future) is a runtime dependency, not workflow data — see
# src/workflow/state.py for why it is deliberately kept out of
# CaseWorkflowState. Taking it as a factory argument and passing it
# into build_run_ai_analysis_node() means the graph's shape and routing
# never need to change just to use a different provider.
#
# Important Notes:
# - This is a graph factory, not a single shared graph instance: call
#   it once per provider you want to run with (e.g., once per test).
# - The graph never instantiates a live AI provider itself; the caller
#   always supplies one.
# =====================================================================
def build_case_workflow_graph(ai_provider: AIAnalysisProvider):
    """
    Builds and compiles the case workflow graph for one AI provider.

    Returns a compiled LangGraph graph. Call `.invoke(initial_state)`
    on the result to run one case through the full workflow.
    """
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
