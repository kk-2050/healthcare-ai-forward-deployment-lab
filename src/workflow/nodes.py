# File Name: nodes.py
# Purpose: Implements the Phase 1 LangGraph workflow nodes that orchestrate existing deterministic completeness rules.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# Each function below is one "node" (one processing step) in the
# LangGraph workflow defined in src/workflow/graph.py. A node reads the
# current CaseWorkflowState and returns a small dict of the fields it
# changed — LangGraph merges that into the state before the next node
# runs. No node here re-implements business logic that already exists
# elsewhere (completeness rules, AI routing rules, the AI service, or
# the FHIR-style integration client); each one only calls that
# existing logic and records the result.

from src.ai.contracts import AIAnalysisFailureType, AIAnalysisRequest
from src.ai.provider import AIAnalysisProvider
from src.ai.service import run_ai_analysis
from src.integrations.fhir_client import FHIRStyleClient
from src.rules.ai_routing import evaluate_ai_requirement
from src.rules.completeness import evaluate_completeness
from src.workflow.state import CaseWorkflowState, WorkflowStatus


# =====================================================================
# HEALTHCARE EVIDENCE RETRIEVAL
# Purpose:
# Retrieves validated synthetic FHIR-style evidence before the workflow
# performs completeness checks or AI processing.
#
# Why:
# The workflow must not continue as if healthcare evidence exists when
# the integration failed to retrieve it. Running completeness or AI
# processing against missing/fabricated healthcare data would be
# unsafe, so this step happens first and its result decides whether
# the rest of the workflow is even reached.
#
# Important Notes:
# - Retrieval is deterministic and does not use AI.
# - Integration failures route directly to human review (see
#   route_after_healthcare_evidence in src/workflow/graph.py) — the
#   failure category is retained in state, but the routing decision
#   itself only checks outcome.success, never the failure_type or any
#   error text.
# - AI must never fabricate evidence when healthcare retrieval fails:
#   on failure, this node stores the failed FHIRIntegrationOutcome
#   (evidence=None, per src/integrations/fhir_client.py) and the graph
#   sends the case to human review before completeness or AI can run.
# - The live FHIRStyleClient is injected as a runtime dependency (the
#   same closure pattern as build_run_ai_analysis_node) and is never
#   stored in CaseWorkflowState.
# - This node does not mutate PriorAuthorizationCase with the retrieved
#   evidence. Comparing submitted case data against FHIR evidence is
#   separate business logic for a later, focused task.
# =====================================================================
def build_retrieve_healthcare_evidence_node(fhir_client: FHIRStyleClient):
    """
    Creates the retrieve_healthcare_evidence node, bound to one
    specific FHIR-style client.

    Returns a node function that closes over `fhir_client`, so the
    client itself never has to be stored in CaseWorkflowState.
    """

    def retrieve_healthcare_evidence_node(state: CaseWorkflowState) -> dict:
        """Retrieves FHIR-style evidence for the case and stores the outcome."""
        case_id = state["case"].case_id

        outcome = fhir_client.get_case_evidence(case_id)

        step = (
            "healthcare_evidence_retrieved"
            if outcome.success
            else "healthcare_integration_failed"
        )

        return {
            "fhir_integration_outcome": outcome,
            "processing_steps": [step],
        }

    return retrieve_healthcare_evidence_node


# =====================================================================
# DETERMINISTIC COMPLETENESS STEP
# Purpose:
# Runs the existing completeness rule and stores its result in state.
# =====================================================================
def evaluate_completeness_node(state: CaseWorkflowState) -> dict:
    """Checks whether the case has the required documents/notes."""
    result = evaluate_completeness(
        state["case"], state["completeness_requirements"]
    )

    return {
        "completeness_result": result,
        "processing_steps": ["completeness_evaluated"],
    }


# =====================================================================
# HUMAN REVIEW ROUTING
# Purpose:
# Marks the case as needing a human reviewer.
#
# Why:
# Cases reach this node when healthcare (FHIR-style) evidence could
# not be retrieved, when important case information is missing, when
# AI execution fails, or when AI returns invalid structured output. In
# every one of those situations the safe choice is a person, not a
# guess.
# =====================================================================
def human_review_required_node(state: CaseWorkflowState) -> dict:
    """Flags the case for human review and sets the matching status."""
    return {
        "human_review_required": True,
        "workflow_status": WorkflowStatus.HUMAN_REVIEW_REQUIRED,
        "processing_steps": ["human_review_required"],
    }


def complete_node(state: CaseWorkflowState) -> dict:
    """
    Marks deterministic-only processing as finished.

    Reached only when the case is complete and no AI task was
    requested. COMPLETE does not mean clinical approval — see
    src/workflow/state.py for what each WorkflowStatus does and does
    not mean.
    """
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.COMPLETE,
        "processing_steps": ["workflow_completed"],
    }


# =====================================================================
# AI ROUTING STEP
# Purpose:
# Runs the existing deterministic "is AI needed?" rule and stores its
# result in state.
#
# Important Notes:
# This node only reads an explicit request for approved tasks — it does
# not call an LLM and does not decide anything about the case's
# clinical content.
# =====================================================================
def evaluate_ai_requirement_node(state: CaseWorkflowState) -> dict:
    """Decides whether an approved AI task was requested for this case."""
    result = evaluate_ai_requirement(state["ai_processing_requirements"])

    return {
        "ai_routing_result": result,
        "processing_steps": ["ai_requirement_evaluated"],
    }


def ai_analysis_required_node(state: CaseWorkflowState) -> dict:
    """
    Marks that AI analysis is needed, just before it runs.

    This is a transient step on the way into AI execution (see
    src/workflow/graph.py) — it does not mean AI analysis has completed
    or that a decision has been made.
    """
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.AI_ANALYSIS_REQUIRED,
        "processing_steps": ["ai_analysis_required"],
    }


# =====================================================================
# AI EXECUTION (SAFE AI FAILURE ROUTING)
# Purpose:
# Builds a minimum-necessary AIAnalysisRequest from the case, runs it
# through the existing AI service, and records whatever outcome comes
# back — success or failure — without ever inventing a result.
#
# Why:
# The provider (mocked now, a real Azure provider later) is a runtime
# technical dependency, not case/workflow data. Binding it here through
# a closure — instead of storing it in CaseWorkflowState — keeps the
# workflow state limited to plain, serializable data. This supports
# future persistence, checkpointing, and human-review pause/resume,
# and it means swapping in a different provider never requires changing
# CaseWorkflowState or any node's signature. None of those future
# capabilities (persistence, checkpointing, pause/resume) are
# implemented yet.
#
# Important Notes:
# - This node does not duplicate the AI service's validation logic; it
#   only calls run_ai_analysis() and records the result.
# - Both failure types (a provider error and invalid structured output)
#   are recorded with their own processing step, but the actual "what
#   happens next" routing decision is made afterward in
#   src/workflow/graph.py (route_after_ai_analysis), based only on
#   outcome.success — never on the AI's free-form content.
# =====================================================================
def build_run_ai_analysis_node(ai_provider: AIAnalysisProvider):
    """
    Creates the run_ai_analysis node, bound to one specific provider.

    Returns a node function that closes over `ai_provider`, so the
    provider itself never has to be stored in CaseWorkflowState.
    """

    def run_ai_analysis_node(state: CaseWorkflowState) -> dict:
        """Runs AI analysis for the case and stores the outcome in state."""
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
    """
    Marks the AI-assisted analysis step as finished successfully.

    AI_ANALYSIS_COMPLETE means only that this processing step
    succeeded — not a clinical approval, denial, payer decision, or
    medical necessity decision. A human still makes any real decision.
    """
    return {
        "human_review_required": False,
        "workflow_status": WorkflowStatus.AI_ANALYSIS_COMPLETE,
        "processing_steps": ["ai_analysis_completed"],
    }
