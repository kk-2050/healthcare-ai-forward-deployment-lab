# File Name: test_ai_service.py
# Purpose: Tests the Phase 1 AI analysis service and its offline mock provider using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect run_ai_analysis(), the function that calls an
# injected AI provider and validates whatever it returns. Every test
# here uses MockAIAnalysisProvider — a MOCKED / TEST DOUBLE, not a live
# LLM — so the whole file runs offline, deterministically, and without
# any API cost or Azure/OpenAI credentials.

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
    """A minimal, fully valid synthetic AIAnalysisRequest, letting each
    test override only the fields it cares about."""
    data = {
        "case_id": "SYN-CASE-001",
        "tasks": [AITask.SUMMARIZE_NARRATIVE],
        "clinical_notes": "SYN-NOTE-001: synthetic narrative for testing only.",
    }
    data.update(overrides)
    return AIAnalysisRequest(**data)


# =====================================================================
# AI SUCCESS PATH TESTS
# =====================================================================
def test_valid_structured_result_returns_success():
    """Verify a well-formed provider response produces success=True and
    a validated AIAnalysisResult."""
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
    """Verify the provider's summary text is preserved in the
    validated result, not dropped or altered."""
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
    """Verify ambiguity findings from the provider are preserved."""
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
    """Verify text-inconsistency findings from the provider are
    preserved."""
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
    """Verify clarifying-question suggestions from the provider are
    preserved."""
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


def test_completed_tasks_subset_of_requested_tasks_is_accepted():
    """Verify a provider that completes only some of the requested
    tasks (a subset) is accepted — it is not required to complete every
    requested task to succeed."""
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


# =====================================================================
# AI FAILURE PATH TESTS (MALFORMED OUTPUT)
# =====================================================================
def test_unknown_output_field_fails_validation():
    """Verify an unexpected field in the provider's response is
    rejected — the AI output contract never accepts fields it did not
    define."""
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
    """Verify a field with the wrong data type (a string where a list
    is expected) is rejected rather than coerced."""
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
    """Verify a response missing the required completed_tasks field is
    rejected, since the provider must always state what it completed."""
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


def test_completed_task_outside_requested_scope_fails_validation():
    """Verify a provider that reports completing a task nobody
    requested is rejected — a supported AITask value is not
    automatically authorized for every request."""
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


def test_request_rejects_unsupported_task_value():
    """Verify the request itself rejects a task name outside the
    approved AITask enum, before any provider is even called."""
    # TEST-006K
    with pytest.raises(ValidationError):
        AIAnalysisRequest(case_id="SYN-CASE-001", tasks=["not_a_real_task"])


# =====================================================================
# AI FAILURE PATH TESTS (PROVIDER ERROR)
# =====================================================================
def test_provider_exception_returns_provider_failed():
    """Verify a provider that raises an exception (simulating a
    timeout or service error) is safely converted into a
    PROVIDER_FAILED outcome instead of crashing the caller."""
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
    """Verify a provider failure never produces a fabricated AI
    result — result must be None, not a guessed or default value."""
    # TEST-006J
    request = make_request()
    provider = MockAIAnalysisProvider(
        exception=RuntimeError("synthetic provider failure")
    )

    outcome = run_ai_analysis(request, provider)

    assert outcome.result is None
    assert outcome.success is False


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_ai_analysis_result_contains_no_clinical_decision_fields():
    """Verify AIAnalysisResult exposes only language-analysis fields —
    never an approval, denial, medical-necessity, or confidence
    field — since AI output is never a clinical decision."""
    # TEST-006L
    assert set(AIAnalysisResult.model_fields.keys()) == {
        "completed_tasks",
        "summary",
        "ambiguities",
        "inconsistencies",
        "clarifying_questions",
    }


def test_service_does_not_mutate_request():
    """Verify running AI analysis never modifies the request object it
    was given."""
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
    """Verify the exact request object passed in is the one the
    provider receives — confirming there is no hidden transformation or
    a different request built along the way."""
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
    """Verify running the same request through two separately
    configured mock providers with the same response produces the same
    result — proving the whole flow is deterministic and needs no live
    network/API call."""
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
