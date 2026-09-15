# File Name: test_workflow_graph.py
# Purpose: Tests the Phase 1 LangGraph workflow's deterministic completeness routing using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from datetime import date

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness
from src.workflow.graph import case_workflow_graph
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


def run_workflow(case, requirements):
    initial_state: CaseWorkflowState = {
        "case": case,
        "completeness_requirements": requirements,
        "completeness_result": None,
        "workflow_status": WorkflowStatus.PROCESSING,
        "human_review_required": False,
        "processing_steps": [],
    }
    return case_workflow_graph.invoke(initial_state)


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
