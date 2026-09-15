# File Name: test_workflow_graph.py
# Purpose: Tests the Phase 1 LangGraph workflow's deterministic completeness routing using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from datetime import date

from src.ai.contracts import AIAnalysisFailureType, AIAnalysisRequest
from src.ai.mock_provider import MockAIAnalysisProvider
from src.models.ai import AIProcessingRequirements, AITask
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness
from src.workflow.graph import build_case_workflow_graph
from src.workflow.state import CaseWorkflowState, WorkflowStatus


def make_case(**overrides):
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
    data = {
        "required_documentation": [],
        "clinical_notes_required": False,
    }
    data.update(overrides)
    return CompletenessRequirements(**data)


def run_workflow(
    case, requirements, ai_processing_requirements=None, ai_provider=None
):
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

    initial_state: CaseWorkflowState = {
        "case": case,
        "completeness_requirements": requirements,
        "completeness_result": None,
        "ai_processing_requirements": ai_processing_requirements,
        "ai_routing_result": None,
        "ai_analysis_outcome": None,
        "workflow_status": WorkflowStatus.PROCESSING,
        "human_review_required": False,
        "processing_steps": [],
    }
    # The provider is injected into the graph factory, not the state, so
    # it can never be part of a future persisted/checkpointed case.
    graph = build_case_workflow_graph(ai_provider)
    return graph.invoke(initial_state)


def test_complete_case_reaches_complete_status():
    # TEST-004A
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETE
    assert final_state["human_review_required"] is False


def test_missing_documentation_routes_to_human_review():
    # TEST-004B
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = make_requirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert final_state["human_review_required"] is True


def test_missing_clinical_notes_routes_to_human_review():
    # TEST-004C
    case = make_case(clinical_notes=None)
    requirements = make_requirements(clinical_notes_required=True)

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert final_state["human_review_required"] is True


def test_complete_case_completeness_result_is_complete_true():
    # TEST-004D
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["completeness_result"].is_complete is True


def test_incomplete_case_preserves_exact_missing_documentation():
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
    # TEST-004F
    case = make_case(clinical_notes=None)
    requirements = make_requirements(clinical_notes_required=True)

    direct_result = evaluate_completeness(case, requirements)
    final_state = run_workflow(case, requirements)

    assert (
        final_state["completeness_result"].missing_fields
        == direct_result.missing_fields
    )


def test_processing_steps_shows_completeness_before_routing():
    # TEST-004G
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)
    steps = final_state["processing_steps"]

    assert steps.index("completeness_evaluated") < steps.index("workflow_completed")


def test_complete_path_excludes_human_review_step():
    # TEST-004H
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert "human_review_required" not in final_state["processing_steps"]


def test_human_review_path_does_not_produce_complete_status():
    # TEST-004I
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] != WorkflowStatus.COMPLETE
    assert "workflow_completed" not in final_state["processing_steps"]


def test_workflow_does_not_mutate_original_case():
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


def test_complete_case_without_ai_tasks_reaches_complete_with_expected_step_order():
    # TEST-005G
    case = make_case()
    requirements = make_requirements()

    final_state = run_workflow(case, requirements)

    assert final_state["workflow_status"] == WorkflowStatus.COMPLETE
    assert final_state["processing_steps"] == [
        "completeness_evaluated",
        "ai_requirement_evaluated",
        "workflow_completed",
    ]


def test_complete_case_with_approved_ai_task_reaches_ai_analysis_complete():
    # TEST-005H (updated by Task 13: the AI-required path now continues
    # through AI execution via the default successful mock provider,
    # rather than terminating at AI_ANALYSIS_REQUIRED as it did in Task 11)
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] == WorkflowStatus.AI_ANALYSIS_COMPLETE
    assert final_state["human_review_required"] is False


def test_complete_case_with_ai_task_preserves_requested_task():
    # TEST-005I
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.IDENTIFY_AMBIGUITY])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["ai_routing_result"].requested_tasks == [
        AITask.IDENTIFY_AMBIGUITY
    ]


def test_incomplete_case_with_ai_task_still_routes_to_human_review():
    # TEST-005J
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] == WorkflowStatus.HUMAN_REVIEW_REQUIRED
    assert "ai_requirement_evaluated" not in final_state["processing_steps"]
    assert "ai_analysis_required" not in final_state["processing_steps"]


def test_ai_analysis_required_path_never_produces_complete_status():
    # TEST-005K
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    final_state = run_workflow(case, requirements, ai_requirements)

    assert final_state["workflow_status"] != WorkflowStatus.COMPLETE
    assert "workflow_completed" not in final_state["processing_steps"]


def test_completeness_result_remains_intact_after_ai_routing():
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
    # TEST-005M
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes

    run_workflow(case, requirements, ai_requirements)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes


def test_successful_ai_analysis_reaches_ai_analysis_complete():
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


def test_malformed_ai_output_routes_to_human_review():
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
    # TEST-007I
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert final_state["ai_analysis_outcome"].result is None


def test_incomplete_case_never_calls_provider():
    # TEST-007J
    case = make_case(supporting_documentation=[])
    requirements = make_requirements(required_documentation=["SYN-DOC-A"])
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_workflow(case, requirements, ai_requirements, provider)

    assert provider.last_request is None


def test_complete_case_without_ai_task_never_calls_provider():
    # TEST-007K
    case = make_case()
    requirements = make_requirements()
    provider = MockAIAnalysisProvider(response={"completed_tasks": []})

    run_workflow(case, requirements, ai_provider=provider)

    assert provider.last_request is None


def test_successful_ai_analysis_does_not_produce_complete_status():
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


def test_ai_analysis_request_contains_only_minimum_necessary_fields():
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


def test_completeness_result_remains_intact_after_ai_execution():
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


def test_final_workflow_state_does_not_contain_ai_provider():
    # Task 13 architecture correction: the provider is a runtime
    # dependency injected into the graph factory, not workflow state, so
    # it must never appear as a key in the state returned by invoke().
    case = make_case()
    requirements = make_requirements()
    ai_requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    final_state = run_workflow(case, requirements, ai_requirements, provider)

    assert "ai_provider" not in final_state
    assert set(CaseWorkflowState.__annotations__.keys()) == {
        "case",
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
    # Persistence-readiness structural check: every value in the final
    # state must be plain data (a Pydantic model, enum, bool, str, or
    # list) — never the injected provider/client object itself — so the
    # state is safe to serialize/persist/checkpoint in a future task.
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
