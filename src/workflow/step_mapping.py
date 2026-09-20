# File Name: step_mapping.py
# Purpose: Defines the one authoritative mapping from LangGraph node names to the stable, persisted workflow_definition_steps.step_code contract.
# Creation Date: 2026-09-19
# Author: K.Kashiwagi
#
# Module Explanation:
# ADR-007 (docs/decisions/ADR-007-trace-id-and-workflow-step-mapping.md)
# established the rule this file implements: Python LangGraph node names
# are an implementation detail; workflow_definition_steps.step_code is
# the stable, persisted contract. No code may derive a persisted step
# from function.__name__ or any other Python implementation detail, and
# this mapping must live in exactly one place -- here -- rather than be
# duplicated per node.

# =====================================================================
# STABLE STEP CODES
# Purpose:
# The exact step_code values proposed for workflow_definition_steps in
# docs/database/reference_data.md Section 7, reused verbatim -- this
# file does not invent new codes.
#
# Important Notes:
# CASE_VALIDATION has no LangGraph node: it is pre-graph Pydantic
# validation (see docs/decisions/ADR-007). It is listed here only so
# callers have one place to find the full step vocabulary; it never
# appears as a key in LANGGRAPH_NODE_TO_STEP_CODE below.
# =====================================================================
STEP_CODE_CASE_VALIDATION = "CASE_VALIDATION"
STEP_CODE_FHIR_RETRIEVAL = "FHIR_RETRIEVAL"
STEP_CODE_EVIDENCE_CONSISTENCY = "EVIDENCE_CONSISTENCY"
STEP_CODE_COMPLETENESS_CHECK = "COMPLETENESS_CHECK"
STEP_CODE_AI_ROUTING = "AI_ROUTING"
STEP_CODE_AI_ANALYSIS = "AI_ANALYSIS"
STEP_CODE_HUMAN_REVIEW = "HUMAN_REVIEW"
STEP_CODE_COMPLETE = "COMPLETE"


# =====================================================================
# LANGGRAPH NODE -> STEP CODE
# Purpose:
# The single authoritative mapping table. Every node currently
# registered in src/workflow/graph.py's build_case_workflow_graph()
# must appear here exactly once.
#
# Why:
# ai_analysis_required and run_ai_analysis both map to AI_ANALYSIS, and
# complete/ai_analysis_complete both map to COMPLETE -- see ADR-007 for
# the reasoning: these pairs are sub-phases of one logical step, not
# two different persisted steps, and the deterministic-vs-AI-assisted
# distinction is already preserved elsewhere (workflow_status_code).
#
# Maintenance Note:
# If src/workflow/graph.py ever adds, removes, or renames a node, this
# table must be updated in the same reviewed change -- see
# verify_mapping_matches_graph() below, which tests call to catch a
# drift instead of silently mismapping.
# =====================================================================
LANGGRAPH_NODE_TO_STEP_CODE: dict[str, str] = {
    "retrieve_healthcare_evidence": STEP_CODE_FHIR_RETRIEVAL,
    "evaluate_evidence_consistency": STEP_CODE_EVIDENCE_CONSISTENCY,
    "evaluate_completeness": STEP_CODE_COMPLETENESS_CHECK,
    "evaluate_ai_requirement": STEP_CODE_AI_ROUTING,
    "ai_analysis_required": STEP_CODE_AI_ANALYSIS,
    "run_ai_analysis": STEP_CODE_AI_ANALYSIS,
    "human_review_required": STEP_CODE_HUMAN_REVIEW,
    "complete": STEP_CODE_COMPLETE,
    "ai_analysis_complete": STEP_CODE_COMPLETE,
}


def step_code_for_node(node_name: str) -> str:
    """
    Resolves one LangGraph node name to its stable, persisted step_code.

    Raises KeyError for an unmapped node name rather than guessing --
    an unmapped node is a real gap that must be fixed in
    LANGGRAPH_NODE_TO_STEP_CODE, never silently ignored or derived from
    the node name itself.
    """
    return LANGGRAPH_NODE_TO_STEP_CODE[node_name]


def verify_mapping_matches_graph(registered_node_names) -> None:
    """
    Verifies every node actually registered in the compiled graph has a
    mapping entry, and that no mapping entry references a node that no
    longer exists.

    Intended for a test to call with the graph's real registered node
    names (e.g. graph.get_graph().nodes, minus the implicit
    START/END markers), so a future graph change that adds, removes, or
    renames a node is caught here rather than silently mismapping.
    Raises AssertionError describing the exact mismatch found.
    """
    mapped_names = set(LANGGRAPH_NODE_TO_STEP_CODE.keys())
    actual_names = set(registered_node_names)

    missing_from_mapping = actual_names - mapped_names
    stale_in_mapping = mapped_names - actual_names

    assert not missing_from_mapping, (
        f"Graph node(s) with no step_code mapping: {sorted(missing_from_mapping)}"
    )
    assert not stale_in_mapping, (
        f"Mapping references node(s) no longer in the graph: {sorted(stale_in_mapping)}"
    )


__all__ = [
    "STEP_CODE_CASE_VALIDATION",
    "STEP_CODE_FHIR_RETRIEVAL",
    "STEP_CODE_EVIDENCE_CONSISTENCY",
    "STEP_CODE_COMPLETENESS_CHECK",
    "STEP_CODE_AI_ROUTING",
    "STEP_CODE_AI_ANALYSIS",
    "STEP_CODE_HUMAN_REVIEW",
    "STEP_CODE_COMPLETE",
    "LANGGRAPH_NODE_TO_STEP_CODE",
    "step_code_for_node",
    "verify_mapping_matches_graph",
]
