# File Name: graph.py
# Purpose: Builds and compiles the Phase 1 LangGraph workflow graph for deterministic case completeness routing.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from langgraph.graph import END, START, StateGraph

from src.workflow.nodes import (
    complete_node,
    evaluate_completeness_node,
    human_review_required_node,
)
from src.workflow.state import CaseWorkflowState


def route_after_completeness(state: CaseWorkflowState) -> str:
    result = state["completeness_result"]

    if result is not None and result.is_complete:
        return "complete"

    return "human_review_required"


def build_case_workflow_graph():
    graph = StateGraph(CaseWorkflowState)

    graph.add_node("evaluate_completeness", evaluate_completeness_node)
    graph.add_node("complete", complete_node)
    graph.add_node("human_review_required", human_review_required_node)

    graph.add_edge(START, "evaluate_completeness")
    graph.add_conditional_edges(
        "evaluate_completeness",
        route_after_completeness,
        {
            "complete": "complete",
            "human_review_required": "human_review_required",
        },
    )
    graph.add_edge("complete", END)
    graph.add_edge("human_review_required", END)

    return graph.compile()


case_workflow_graph = build_case_workflow_graph()
