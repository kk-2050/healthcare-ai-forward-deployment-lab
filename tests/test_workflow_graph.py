# File Name: test_workflow_graph.py
# Purpose: Tests the Phase 1 LangGraph workflow's deterministic completeness routing using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the full LangGraph workflow end to end: retrieving
# healthcare (FHIR-style) evidence first, routing an incomplete case or
# a failed healthcare integration to human review, routing a complete
# case with no AI task straight to COMPLETE, and running a complete
# case with an approved AI task through AI execution (success,
# malformed output, or provider failure). Every AI-related test here
# uses MockAIAnalysisProvider, and every healthcare-integration test
# uses FHIRStyleClient backed by httpx.MockTransport — MOCKED / TEST
# DOUBLES, never a live LLM or a live healthcare system — so the whole
# file runs offline and deterministically.

from datetime import date

import httpx

from src.ai.contracts import AIAnalysisFailureType, AIAnalysisRequest
from src.ai.mock_provider import MockAIAnalysisProvider
from src.integrations.fhir_client import FHIRStyleClient
from src.integrations.fhir_models import FHIRIntegrationFailureType
from src.models.ai import AIProcessingRequirements, AITask
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness
from src.workflow.graph import build_case_workflow_graph
from src.workflow.state import CaseWorkflowState, WorkflowStatus


def make_case(**overrides):
    """A minimal, fully valid synthetic case, letting each test
    override only the fields it cares about."""
    data = {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-SERVICE-001",
        "diagnosis_code": "SYN-DX-001",
        "requested_date": date(2026, 1, 15),
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


def make_requirements(**overrides):
    """A minimal, fully valid CompletenessRequirements, letting each
    test override only the fields it cares about."""
    data = {
        "required_documentation": [],
        "clinical_notes_required": False,
    }
    data.update(overrides)
    return CompletenessRequirements(**data)


def valid_fhir_bundle_json(entry=None):
    """
    A minimal, fully valid synthetic FHIR-style Bundle body.

    Kept local to this file (rather than imported from
    tests/test_fhir_client.py) so workflow tests stay independent of
    that test module's fixtures.
    """
    default_entry = [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "SYN-SR-001",
                "status": "active",
                "intent": "order",
                "code": {
                    "coding": [
                        {
                            "system": "http://example.org/synthetic-codes",
                            "code": "SYN-LUMBAR-MRI",
                            "display": "Lumbar MRI (synthetic)",
                        }
                    ]
                },
                "reasonReference": [],
            }
        }
    ]
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": default_entry if entry is None else entry,
    }


def make_fhir_client(
    json_body=None, status_code=200, raw_content=None, on_request=None
) -> FHIRStyleClient:
    """
    Builds an FHIRStyleClient backed by httpx.MockTransport -- an
    offline test double that never opens a socket. Defaults to a
    successful synthetic Bundle response unless overridden.

    on_request, if supplied, is called with each outgoing httpx.Request
    so a test can record what was requested (e.g. the case ID in the
    URL path) without a real server.
    """
    body = valid_fhir_bundle_json() if json_body is None else json_body

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        if raw_content is not None:
            return httpx.Response(status_code, content=raw_content)
        return httpx.Response(status_code, json=body)

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def run_workflow(
    case,
    requirements,
    ai_processing_requirements=None,
    ai_provider=None,
    fhir_client=None,
):
    """
    Builds a fresh graph and runs one case through it end to end.

    If ai_provider is not supplied, a default MockAIAnalysisProvider is
    used that echoes back whatever tasks were requested, so tests that
    don't care about AI execution details still get a deterministic
    successful outcome without wiring up a mock for every unrelated
    assertion. Likewise, if fhir_client is not supplied, a default
    FHIRStyleClient backed by a successful synthetic Bundle is used, so
    tests unrelated to healthcare integration still get a deterministic
    successful retrieval. Both are passed into the graph factory (not
    stored in state) — see src/workflow/graph.py and state.py for why.
    """
    if ai_processing_requirements is None:
        ai_processing_requirements = AIProcessingRequirements()

    if ai_provider is None:
        # Default provider echoes back whatever tasks were requested, so
        # tests that don't care about AI execution details still get a
        # deterministic successful outcome rather than needing to wire up
        # a mock provider explicitly for every unrelated assertion.
        ai_provider = MockAIAnalysisProvider(
            response={
                "completed_tasks": [
                    task.value for task in ai_processing_requirements.tasks
                ],
            }
        )

    if fhir_client is None:
        fhir_client = make_fhir_client()

    initial_state: CaseWorkflowState = {
        "case": case,
        "fhir_integration_outcome": None,
        "completeness_requirements": requirements,
        "completeness_result": None,
        "ai_processing_requirements": ai_processing_requirements,
        "ai_routing_result": None,
        "ai_analysis_outcome": None,
        "workflow_status": WorkflowStatus.PROCESSING,
        "human_review_required": False,
        "processing_steps": [],
    }
    # Both dependencies are injected into the graph factory, not the
    # state, so neither can ever be part of a future persisted/
    # checkpointed case.
    graph = build_case_workflow_graph(ai_provider, fhir_client)
    return graph.invoke(initial_state)


# =====================================================================
# COMPLETE CASE (NO AI) TESTS
# =====================================================================
def test_complete_case_reaches_complete_status():
    """Verify a complete case with no AI task requested ends in
    COMPLETE, which means processing finished, not clinical approval."""
    # TEST-004A
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETE
    assert final_state["human_review_required"] is False


def test_complete_case_completeness_result_is_complete_true():
    """Verify the completeness_result stored in state reflects a
    complete case, not just the final workflow_status."""
    # TEST-004D
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["completeness_result"].is_complete is True


def test_processing_steps_shows_completeness_before_routing():
    """Verify the completeness check is recorded before the case
    finishes, proving deterministic validation runs first."""
    # TEST-004G
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)
    steps = final_state["processing_steps"]

    assert steps.index("completeness_evaluated") < steps.index("workflow_completed")


def test_complete_path_excludes_human_review_step():
    """Verify a complete case's trace never mentions human review — the
    complete path and the human-review path stay distinct."""
    # TEST-004H
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert "human_review_required" not in final_state["processing_steps"]


def test_complete_case_without_ai_tasks_reaches_complete_with_expected_step_order():
    """
    Verify the exact processing-step order for the simplest path:
    healthcare evidence retrieval, completeness check, AI-needed check
    (which finds nothing to do), then completion.

    (TEST-005G, updated by Task 16B: healthcare evidence retrieval now
    runs before completeness evaluation, so "healthcare_evidence_retrieved"
    is the new first step. This is a deliberate update to an existing
    exact-list assertion, not a weakening — it now documents the real,
    complete step order.)
    """
    # TEST-005G
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETE
    assert final_state["processing_steps"] == [
        "healthcare_evidence_retrieved",
        "completeness_evaluated",
        "ai_requirement_evaluated",
        "workflow_completed",
    ]


def test_complete_case_without_ai_task_never_calls_provider():
    """Verify a complete case that requests no AI task never calls the
    provider at all — an unused AI provider must never be a required
    dependency for a case that does not need it."""
    # TEST-007K
    case = make_case()
    requirements = make_requirements()
    provider = MockAIAnalysisProvider(response={"completed_tasks": []})

    run_workflow(case, requirements, ai_provider=provider)

    assert provider.last_request is None


# =====================================================================
# INCOMPLETE CASE / HUMAN REVIEW TESTS
# =====================================================================
def test_missing_documentation_routes_to_human_review():
    """Verify a case missing required documentation is routed to human
    review rather than completing anyway."""
    # TEST-004B
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = make_requirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert final_state["human_review_required"] is True


def test_missing_clinical_notes_routes_to_human_review():
    """Verify a case missing required clinical notes is routed to human
    review."""
    # TEST-004C
    case = make_case(clinical_notes=None)
    requirements = make_requirements(clinical_notes_required=True)

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert final_state["human_review_required"] is True


def test_incomplete_case_preserves_exact_missing_documentation():
    """Verify the workflow's stored completeness_result matches what
    calling the rule directly would produce — the graph does not alter
    the rule's answer."""
    # TEST-004E
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = make_requirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B", "SYN-DOC-C"]
    )

    direct_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements)

    assert (
        final_state["completeness_result"].missing_documentation
        == direct_result.missing_documentation
    )


def test_incomplete_case_preserves_exact_missing_fields():
    """Verify missing_fields in the workflow's result matches the
    direct rule call exactly."""
    # TEST-004F
    case = make_case(clinical_notes=None)
    requirements = make_requirements(clinical_notes_required=True)

    direct_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements)

    assert (
        final_state["completeness_result"].missing_fields
        == direct_result.missing_fields
    )


def test_human_review_path_does_not_produce_complete_status():
    """Verify an incomplete case never ends in COMPLETE and never runs
    the completion step."""
    # TEST-004I
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] != WorkflowStatus.COMPLETE
    assert "workflow_completed" not in final_state["processing_steps"]


def test_workflow_does_not_mutate_original_case():
    """Verify running the workflow never modifies the original case
    object supplied to it."""
    # TEST-004J
    case = make_case(supporting_documentation=["SYN-DOC-A"], clinical_notes=None)
    requirements = make_requirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"],
        clinical_notes_required=True,
    )

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes

    run_workflow(case, requirements)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes


def test_incomplete_case_with_ai_task_still_routes_to_human_review():
    """Verify an incomplete case is routed to human review even when an
    AI task was requested — a missing document or note always takes
    priority over AI analysis, and AI routing/execution never runs for
    an incomplete case."""
    # TEST-005J
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert "ai_requirement_evaluated" not in final_state["processing_steps"]
    assert "ai_analysis_required" not in final_state["processing_steps"]


def test_incomplete_case_never_calls_provider():
    """Verify an incomplete case never calls the AI provider, even when
    an AI task was requested — the provider is not a dependency for a
    case that never reaches AI routing."""
    # TEST-007J
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_workflow(case, requirements, ai_requirements, provider)

    assert provider.last_request is None


# =====================================================================
# AI ROUTING TESTS (NO EXECUTION YET)
# =====================================================================
def test_complete_case_with_ai_task_preserves_requested_task():
    """Verify the AI-routing step records exactly which task was
    requested, before AI execution runs."""
    # TEST-005I
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.IDENTIFY_AMBIGUITY])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["ai_routing_result"].requested_tasks == [
        AITask.IDENTIFY_AMBIGUITY
    ]


def test_completeness_result_remains_intact_after_ai_routing():
    """Verify the completeness result from earlier in the workflow is
    unchanged after the AI-routing step runs."""
    # TEST-005L
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    direct_completeness_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements, ai_requirements)

    assert (
        final_state["completeness_result"].is_complete
        == direct_completeness_result.is_complete
    )
    assert (
        final_state["completeness_result"].missing_fields
        == direct_completeness_result.missing_fields
    )
    assert (
        final_state["completeness_result"].missing_documentation
        == direct_completeness_result.missing_documentation
    )


def test_ai_routing_does_not_mutate_original_case():
    """Verify the AI-routing step never modifies the original case
    object."""
    # TEST-005M
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes

    run_workflow(case, requirements, ai_requirements)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes


# =====================================================================
# AI SUCCESS PATH TESTS
# =====================================================================
def test_complete_case_with_approved_ai_task_reaches_ai_analysis_complete():
    """Verify a complete case with an approved AI task, run through the
    default successful mock provider, ends in AI_ANALYSIS_COMPLETE —
    not human review and not the plain COMPLETE status.

    (TEST-005H, updated by Task 13: the AI-required path now continues
    through AI execution via the default successful mock provider,
    rather than terminating at AI_ANALYSIS_REQUIRED as it did in
    Task 11.)"""
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] == WorkflowStatus.AI_ANALYSIS_COMPLETE
    assert final_state["human_review_required"] is False


def test_successful_ai_analysis_reaches_ai_analysis_complete():
    """Verify a successful AI analysis (explicit mock provider) ends in
    AI_ANALYSIS_COMPLETE."""
    # TEST-007A
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "summary": "SYN-SUMMARY-WF-001",
        }
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["workflow_status"] == WorkflowStatus.AI_ANALYSIS_COMPLETE


def test_successful_ai_path_stores_valid_outcome():
    """Verify a successful run stores a valid AIAnalysisOutcome with
    success=True in state, not just a status change."""
    # TEST-007B
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    outcome = final_state["ai_analysis_outcome"]
    assert outcome is not None
    assert outcome.success is True


def test_successful_ai_path_stores_result():
    """Verify the AI-generated summary is available in state after a
    successful run, so downstream code can use it."""
    # TEST-007C
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "summary": "SYN-SUMMARY-WF-002",
        }
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    result = final_state["ai_analysis_outcome"].result
    assert result is not None
    assert result.summary == "SYN-SUMMARY-WF-002"


def test_successful_ai_path_processing_order():
    """Verify the successful-path trace shows completeness, then AI
    routing, then AI execution, then completion — in that order — so
    the workflow's real path can be understood from the trace alone."""
    # TEST-007D
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)
    steps = final_state["processing_steps"]

    assert steps.index("completeness_evaluated") < steps.index(
        "ai_requirement_evaluated"
    )
    assert steps.index("ai_requirement_evaluated") < steps.index(
        "ai_analysis_executed"
    )
    assert steps.index("ai_analysis_executed") < steps.index("ai_analysis_completed")


def test_successful_ai_analysis_does_not_produce_complete_status():
    """Verify a successful AI run ends in AI_ANALYSIS_COMPLETE, never
    the plain COMPLETE status used for the no-AI path — the two
    statuses must stay distinguishable."""
    # TEST-007L
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["workflow_status"] != WorkflowStatus.COMPLETE
    assert final_state["workflow_status"] == WorkflowStatus.AI_ANALYSIS_COMPLETE


def test_completeness_result_remains_intact_after_ai_execution():
    """Verify the completeness result is still correct after the AI
    step runs — AI execution must not overwrite earlier results."""
    # TEST-007O
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    direct_completeness_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert (
        final_state["completeness_result"].is_complete
        == direct_completeness_result.is_complete
    )
    assert (
        final_state["completeness_result"].missing_fields
        == direct_completeness_result.missing_fields
    )
    assert (
        final_state["completeness_result"].missing_documentation
        == direct_completeness_result.missing_documentation
    )


# =====================================================================
# AI FAILURE PATH TESTS
# =====================================================================
def test_ai_analysis_required_path_never_produces_complete_status():
    """Verify a case that needed AI analysis never ends in the plain
    COMPLETE status, regardless of how the AI step turns out."""
    # TEST-005K
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] != WorkflowStatus.COMPLETE
    assert "workflow_completed" not in final_state["processing_steps"]


def test_malformed_ai_output_routes_to_human_review():
    """Verify malformed structured AI output safely routes the case to
    human review instead of continuing as if analysis succeeded."""
    # TEST-007E
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "unexpected_field": "not allowed",
        }
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_malformed_ai_output_preserves_failure_type():
    """Verify the stored outcome records OUTPUT_VALIDATION_FAILED so a
    reviewer can see why the case needed human review."""
    # TEST-007F
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "unexpected_field": "not allowed",
        }
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    outcome = final_state["ai_analysis_outcome"]
    assert outcome.failure_type == AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED


def test_provider_exception_routes_to_human_review():
    """Verify a provider exception (e.g., simulating a timeout) safely
    routes the case to human review."""
    # TEST-007G
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_provider_exception_preserves_failure_type():
    """Verify the stored outcome records PROVIDER_FAILED, distinct from
    OUTPUT_VALIDATION_FAILED, so the two failure causes stay
    distinguishable in the trace."""
    # TEST-007H
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    outcome = final_state["ai_analysis_outcome"]
    assert outcome.failure_type == AIAnalysisFailureType.PROVIDER_FAILED


def test_failure_path_never_fabricates_result():
    """Verify a provider failure never leaves a fabricated AI result in
    state — result must be None."""
    # TEST-007I
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["ai_analysis_outcome"].result is None


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_ai_analysis_request_contains_only_minimum_necessary_fields():
    """Verify the request actually sent to the provider contains only
    case_id, tasks, and clinical_notes — never member_id, provider_id,
    or any other case/audit internals."""
    # TEST-007M
    case = make_case(clinical_notes="SYN-NOTE-WORKFLOW-001")
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_workflow(case, requirements, ai_requirements, provider)

    sent_request = provider.last_request
    assert set(AIAnalysisRequest.model_fields.keys()) == {
        "case_id",
        "tasks",
        "clinical_notes",
    }
    assert sent_request.case_id == case.case_id
    assert sent_request.tasks == [AITask.SUMMARIZE_NARRATIVE]
    assert sent_request.clinical_notes == "SYN-NOTE-WORKFLOW-001"


def test_ai_execution_does_not_mutate_original_case():
    """Verify running AI execution inside the workflow never modifies
    the original case object."""
    # TEST-007N
    case = make_case(clinical_notes="SYN-NOTE-WORKFLOW-002")
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes

    run_workflow(case, requirements, ai_requirements, provider)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes


def test_final_workflow_state_does_not_contain_ai_provider():
    """Verify the AI provider never appears as a key in the state
    returned by the graph — it is a runtime dependency injected into
    the graph factory, not workflow/case data (Task 13 architecture
    correction)."""
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert "ai_provider" not in final_state
    # Updated by Task 16B: fhir_integration_outcome was added to
    # CaseWorkflowState alongside the existing fields.
    assert set(CaseWorkflowState.__annotations__.keys()) == {
        "case",
        "fhir_integration_outcome",
        "completeness_requirements",
        "completeness_result",
        "ai_processing_requirements",
        "ai_routing_result",
        "ai_analysis_outcome",
        "workflow_status",
        "human_review_required",
        "processing_steps",
    }


def test_workflow_state_contains_no_provider_or_client_objects():
    """Verify every value in the final state is plain data — never the
    injected provider/client object itself — so the state stays safe to
    serialize/persist/checkpoint in a future task (persistence-readiness
    structural check; persistence itself is not implemented yet)."""
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    for value in final_state.values():
        assert not isinstance(value, MockAIAnalysisProvider)
        assert value is not provider


# =====================================================================
# HEALTHCARE INTEGRATION SUCCESS PATH TESTS
# =====================================================================
def test_healthcare_evidence_retrieval_occurs_before_completeness():
    """Verify healthcare evidence retrieval is recorded before the
    completeness check, proving FHIR-style retrieval is genuinely the
    first workflow step."""
    # TEST-011A
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)
    steps = final_state["processing_steps"]

    assert steps.index("healthcare_evidence_retrieved") < steps.index(
        "completeness_evaluated"
    )


def test_validated_fhir_evidence_is_retained_in_final_state():
    """Verify the validated FHIRCaseEvidence extracted from the
    synthetic Bundle is available in the final workflow state, not
    just a bare success flag."""
    # TEST-011B
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    outcome = final_state["fhir_integration_outcome"]
    assert outcome is not None
    assert outcome.success is True
    assert outcome.evidence is not None
    assert outcome.evidence.service_request_id == "SYN-SR-001"


def test_fhir_client_is_called_with_synthetic_workflow_case_id():
    """Verify the FHIR-style client is asked for evidence using the
    exact case ID from the workflow's PriorAuthorizationCase, not a
    placeholder or a different identifier."""
    # TEST-011C
    requested_urls = []

    def record_request(request: httpx.Request) -> None:
        requested_urls.append(str(request.url))

    case = make_case(case_id="SYN-CASE-999")
    requirements = make_requirements()
    fhir_client = make_fhir_client(on_request=record_request)

    run_workflow(case, requirements, fhir_client=fhir_client)

    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/fhir-style/cases/SYN-CASE-999")


def test_successful_retrieval_with_no_ai_tasks_still_reaches_complete():
    """Verify adding the healthcare retrieval step does not change the
    existing outcome for a complete case with no AI task requested —
    it still reaches COMPLETE."""
    # TEST-011D
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETE


def test_successful_retrieval_with_ai_task_still_reaches_ai_execution():
    """Verify adding the healthcare retrieval step does not change the
    existing outcome for a complete case with an AI task requested —
    it still reaches the existing AI execution path."""
    # TEST-011E
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] == WorkflowStatus.AI_ANALYSIS_COMPLETE
    assert final_state["ai_analysis_outcome"] is not None


# =====================================================================
# HEALTHCARE INTEGRATION FAILURE ROUTING TESTS
# =====================================================================
def test_http_failure_routes_to_human_review():
    """Verify an HTTP-level healthcare integration failure (e.g. a
    500 response) routes the case to human review instead of
    continuing."""
    # TEST-011F
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_malformed_json_routes_to_human_review():
    """Verify a healthcare response body that is not valid JSON routes
    the case to human review."""
    # TEST-011G
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client(raw_content=b"{not valid json")

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_invalid_fhir_style_schema_routes_to_human_review():
    """Verify a healthcare response that does not match the expected
    FHIR-style schema routes the case to human review."""
    # TEST-011H
    case = make_case()
    requirements = make_requirements()
    entry = [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "SYN-SR-001",
                # "status" and "intent" are required and missing here.
                "code": {"coding": []},
            }
        }
    ]
    fhir_client = make_fhir_client(json_body=valid_fhir_bundle_json(entry=entry))

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_missing_service_request_routes_to_human_review():
    """Verify a Bundle with no ServiceRequest resource routes the case
    to human review."""
    # TEST-011I
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client(json_body=valid_fhir_bundle_json(entry=[]))

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_broken_condition_reference_routes_to_human_review():
    """Verify a ServiceRequest reasonReference pointing at a Condition
    that does not exist in the Bundle routes the case to human review."""
    # TEST-011J
    case = make_case()
    requirements = make_requirements()
    entry = [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "SYN-SR-001",
                "status": "active",
                "intent": "order",
                "code": {"coding": [{"code": "SYN-LUMBAR-MRI"}]},
                "reasonReference": [
                    {"reference": "Condition/SYN-COND-DOES-NOT-EXIST"}
                ],
            }
        }
    ]
    fhir_client = make_fhir_client(json_body=valid_fhir_bundle_json(entry=entry))

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


def test_unsupported_resource_type_routes_to_human_review():
    """Verify a Bundle containing a resource type outside the approved
    subset (e.g. "Patient") routes the case to human review."""
    # TEST-011K
    case = make_case()
    requirements = make_requirements()
    entry = [{"resource": {"resourceType": "Patient", "id": "SYN-PATIENT-001"}}]
    fhir_client = make_fhir_client(json_body=valid_fhir_bundle_json(entry=entry))

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED


# =====================================================================
# HEALTHCARE INTEGRATION SAFETY BOUNDARY TESTS
#
# These tests protect the most important Task 16B safety rule: AI must
# never run when healthcare evidence could not be retrieved, because
# that would mean asking AI to reason about facts the integration
# failed to provide.
# =====================================================================
def test_healthcare_failure_does_not_call_ai_provider():
    """Verify a healthcare integration failure never reaches the AI
    provider — AI must not be asked to work with missing evidence."""
    # TEST-011L
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})
    ai_provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_workflow(
        case, requirements, ai_requirements, ai_provider, fhir_client=fhir_client
    )

    assert ai_provider.last_request is None


def test_healthcare_failure_does_not_run_completeness_evaluation():
    """Verify a healthcare integration failure never reaches the
    completeness check — completeness_result stays None, proving the
    workflow stopped before that step."""
    # TEST-011M
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    assert final_state["completeness_result"] is None
    assert "completeness_evaluated" not in final_state["processing_steps"]


def test_healthcare_failure_produces_no_fabricated_evidence():
    """Verify a healthcare integration failure never leaves fabricated
    evidence in state — the stored outcome's evidence must be None."""
    # TEST-011N
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client(status_code=500, json_body={"error": "synthetic"})

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    outcome = final_state["fhir_integration_outcome"]
    assert outcome.success is False
    assert outcome.evidence is None
    assert outcome.failure_type == FHIRIntegrationFailureType.HTTP_ERROR


# =====================================================================
# HEALTHCARE INTEGRATION STATE SAFETY TESTS
# =====================================================================
def test_fhir_client_is_not_stored_in_final_state():
    """Verify FHIRStyleClient never appears as a value in the final
    workflow state — it is a runtime dependency injected into the graph
    factory, not workflow/case data (same pattern as the AI provider,
    see Task 13)."""
    # TEST-011O
    case = make_case()
    requirements = make_requirements()
    fhir_client = make_fhir_client()

    final_state = run_workflow(case, requirements, fhir_client=fhir_client)

    for value in final_state.values():
        assert not isinstance(value, FHIRStyleClient)
        assert value is not fhir_client


def test_httpx_client_is_not_stored_in_final_state():
    """Verify the underlying httpx.Client/transport object never
    appears in the final workflow state — only plain, serializable
    data belongs there."""
    # TEST-011P
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    for value in final_state.values():
        assert not isinstance(value, httpx.Client)


def test_fhir_retrieval_does_not_mutate_original_case():
    """Verify healthcare evidence retrieval never modifies the original
    PriorAuthorizationCase object supplied to the workflow."""
    # TEST-011Q
    case = make_case(supporting_documentation=["SYN-DOC-A"], clinical_notes="SYN-NOTE")
    requirements = make_requirements()

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes
    original_case_id = case.case_id

    run_workflow(case, requirements)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes
    assert case.case_id == original_case_id


# =====================================================================
# REGRESSION / INTEGRATION CONSISTENCY TESTS
# =====================================================================
def test_completeness_result_remains_correct_on_successful_integration():
    """Verify the existing deterministic completeness rule still
    produces the exact same result once healthcare retrieval runs
    first — the new step must not change completeness behavior."""
    # TEST-011R
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = make_requirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    direct_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements)

    assert (
        final_state["completeness_result"].missing_documentation
        == direct_result.missing_documentation
    )
    assert final_state["completeness_result"].is_complete == direct_result.is_complete


def test_ai_provider_failure_still_routes_to_human_review_after_fhir_success():
    """Verify the existing AI-failure-routes-to-human-review behavior
    (Task 13) still works correctly once healthcare retrieval succeeds
    first — the new step must not interfere with existing AI safety
    routing."""
    # TEST-011S
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    ai_provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    final_state = run_workflow(case, requirements, ai_requirements, ai_provider)

    assert final_state["fhir_integration_outcome"].success is True
    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert (
        final_state["ai_analysis_outcome"].failure_type
        == AIAnalysisFailureType.PROVIDER_FAILED
    )


def test_processing_steps_distinguish_healthcare_success_from_failure():
    """Verify the processing-step trace uses distinct, recognizable
    names for a successful healthcare retrieval versus a failed one —
    a reviewer reading the trace must be able to tell which happened."""
    # TEST-011T
    case = make_case()
    requirements = make_requirements()

    success_state = run_workflow(case, requirements)
    failure_state = run_workflow(
        case,
        requirements,
        fhir_client=make_fhir_client(status_code=500, json_body={"error": "synthetic"}),
    )

    assert "healthcare_evidence_retrieved" in success_state["processing_steps"]
    assert "healthcare_integration_failed" not in success_state["processing_steps"]

    assert "healthcare_integration_failed" in failure_state["processing_steps"]
    assert "healthcare_evidence_retrieved" not in failure_state["processing_steps"]
