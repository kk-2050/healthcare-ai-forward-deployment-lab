# File Name: test_ai_service.py
# Purpose: Tests the Phase 1 AI analysis service and its offline mock provider using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

import pytest
from pydantic import ValidationError

from src.ai.contracts import (
    AIAnalysisFailureType,
    AIAnalysisRequest,
    AIAnalysisResult,
)
from src.ai.mock_provider import MockAIAnalysisProvider
from src.ai.service import run_ai_analysis
from src.models.ai import AITask


def make_request(**overrides):
    data = {
        "case_id": "SYN-CASE-001",
        "tasks": [AITask.SUMMARIZE_NARRATIVE],
        "clinical_notes": "SYN-NOTE-001: synthetic narrative for testing only.",
    }
    data.update(overrides)
    return AIAnalysisRequest(**data)


def test_valid_structured_result_returns_success():
    # TEST-006A
    request = make_request()
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "summary": "SYN-SUMMARY-001",
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is True
    assert isinstance(outcome.result, AIAnalysisResult)
    assert outcome.failure_type is None


def test_summary_is_preserved():
    # TEST-006B
    request = make_request()
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "summary": "SYN-SUMMARY-002",
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result.summary == "SYN-SUMMARY-002"


def test_ambiguities_are_preserved():
    # TEST-006C
    request = make_request(tasks=[AITask.IDENTIFY_AMBIGUITY])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["identify_ambiguity"],
            "ambiguities": ["SYN-AMBIGUITY-001"],
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result.ambiguities == ["SYN-AMBIGUITY-001"]


def test_inconsistencies_are_preserved():
    # TEST-006D
    request = make_request(tasks=[AITask.IDENTIFY_TEXT_INCONSISTENCIES])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["identify_text_inconsistencies"],
            "inconsistencies": ["SYN-INCONSISTENCY-001"],
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result.inconsistencies == ["SYN-INCONSISTENCY-001"]


def test_clarifying_questions_are_preserved():
    # TEST-006E
    request = make_request(tasks=[AITask.SUGGEST_CLARIFYING_QUESTIONS])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["suggest_clarifying_questions"],
            "clarifying_questions": ["SYN-QUESTION-001"],
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result.clarifying_questions == ["SYN-QUESTION-001"]


def test_unknown_output_field_fails_validation():
    # TEST-006F
    request = make_request()
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "unexpected_field": "not allowed",
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is False
    assert outcome.failure_type == AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED
    assert outcome.result is None


def test_wrong_output_field_type_fails_validation():
    # TEST-006G
    request = make_request()
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
            "ambiguities": "not-a-list",
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is False
    assert outcome.failure_type == AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED
    assert outcome.result is None


def test_missing_required_output_field_fails_validation():
    # TEST-006H
    request = make_request()
    provider = MockAIAnalysisProvider(
        response={
            "summary": "SYN-SUMMARY-003",
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is False
    assert outcome.failure_type == AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED
    assert outcome.result is None


def test_provider_exception_returns_provider_failed():
    # TEST-006I
    request = make_request()
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is False
    assert outcome.failure_type == AIAnalysisFailureType.PROVIDER_FAILED
    assert outcome.result is None


def test_provider_failure_does_not_fabricate_content():
    # TEST-006J
    request = make_request()
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result is None
    assert outcome.success is False


def test_request_rejects_unsupported_task_value():
    # TEST-006K
    with pytest.raises(ValidationError):
        AIAnalysisRequest(case_id="SYN-CASE-001", tasks=["not_a_real_task"])


def test_ai_analysis_result_contains_no_clinical_decision_fields():
    # TEST-006L
    assert set(AIAnalysisResult.model_fields.keys()) == {
        "completed_tasks",
        "summary",
        "ambiguities",
        "inconsistencies",
        "clarifying_questions",
    }


def test_service_does_not_mutate_request():
    # TEST-006M
    request = make_request(tasks=[AITask.SUMMARIZE_NARRATIVE])
    original_tasks = list(request.tasks)
    original_notes = request.clinical_notes

    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_ai_analysis(request, provider)

    assert request.tasks == original_tasks
    assert request.clinical_notes == original_notes


def test_mock_provider_receives_expected_request():
    # TEST-006N
    request = make_request(
        case_id="SYN-CASE-999", tasks=[AITask.SUMMARIZE_NARRATIVE]
    )
    provider = MockAIAnalysisProvider(
        response={"completed_tasks": ["summarize_narrative"]}
    )

    run_ai_analysis(request, provider)

    assert provider.last_request is request
    assert provider.last_request.case_id == "SYN-CASE-999"


def test_full_flow_runs_offline_and_deterministically():
    # TEST-006O
    request = make_request()
    response = {
        "completed_tasks": ["summarize_narrative"],
        "summary": "SYN-SUMMARY-004",
    }

    outcome_one = run_ai_analysis(request, MockAIAnalysisProvider(response=response))
    outcome_two = run_ai_analysis(request, MockAIAnalysisProvider(response=response))

    assert outcome_one.success is True
    assert outcome_two.success is True
    assert outcome_one.result.summary == outcome_two.result.summary


def test_completed_task_outside_requested_scope_fails_validation():
    # TEST-006P
    request = make_request(tasks=[AITask.SUMMARIZE_NARRATIVE])
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative", "identify_ambiguity"],
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is False
    assert outcome.failure_type == AIAnalysisFailureType.OUTPUT_VALIDATION_FAILED
    assert outcome.result is None


def test_completed_tasks_subset_of_requested_tasks_is_accepted():
    # TEST-006Q
    request = make_request(
        tasks=[AITask.SUMMARIZE_NARRATIVE, AITask.IDENTIFY_AMBIGUITY]
    )
    provider = MockAIAnalysisProvider(
        response={
            "completed_tasks": ["summarize_narrative"],
        }
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.success is True
    assert outcome.result.completed_tasks == [AITask.SUMMARIZE_NARRATIVE]
