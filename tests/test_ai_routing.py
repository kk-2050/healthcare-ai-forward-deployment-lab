# File Name: test_ai_routing.py
# Purpose: Tests deterministic AI-needed routing evaluation using explicitly supplied, synthetic approved-task requests only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect evaluate_ai_requirement(), the deterministic
# switch that decides whether AI-assisted analysis is needed for a
# case. This rule never calls an LLM and never makes a clinical
# decision — it only reads an explicit list of requested, approved
# tasks.

import pytest
from pydantic import ValidationError

from src.models.ai import AIProcessingRequirements, AIRoutingResult, AITask
from src.rules.ai_routing import evaluate_ai_requirement


# =====================================================================
# AI-NEEDED ROUTING TESTS
# =====================================================================
def test_no_requested_tasks_means_ai_not_required():
    """Verify AI is not required when no approved task was requested."""
    # TEST-005A
    requirements = AIProcessingRequirements()

    result = evaluate_ai_requirement(requirements)

    assert result.ai_required is False
    assert result.requested_tasks == []


def test_one_approved_task_means_ai_required():
    """Verify requesting a single approved task marks AI as required
    and echoes that exact task back."""
    # TEST-005B
    requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])

    result = evaluate_ai_requirement(requirements)

    assert result.ai_required is True
    assert result.requested_tasks == [AITask.SUMMARIZE_NARRATIVE]


def test_multiple_approved_tasks_are_preserved():
    """Verify multiple requested tasks are all preserved in the result,
    not collapsed to a single task."""
    # TEST-005C
    tasks = [AITask.SUMMARIZE_NARRATIVE, AITask.IDENTIFY_AMBIGUITY]
    requirements = AIProcessingRequirements(tasks=tasks)

    result = evaluate_ai_requirement(requirements)

    assert result.ai_required is True
    assert result.requested_tasks == tasks


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_unsupported_task_value_raises_validation_error():
    """Verify a task name outside the approved AITask enum is rejected
    by Pydantic before the routing rule ever runs — free-form AI task
    names must never be accepted."""
    # TEST-005D
    with pytest.raises(ValidationError):
        AIProcessingRequirements(tasks=["not_a_real_task"])


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_evaluation_does_not_mutate_input_requirements():
    """Verify evaluating the AI-needed rule never modifies the
    requirements object it was given."""
    # TEST-005E
    requirements = AIProcessingRequirements(tasks=[AITask.SUMMARIZE_NARRATIVE])
    original_tasks = list(requirements.tasks)

    evaluate_ai_requirement(requirements)

    assert requirements.tasks == original_tasks


def test_ai_routing_result_contains_no_clinical_decision_fields():
    """Verify AIRoutingResult exposes only routing facts (ai_required,
    requested_tasks) — never an approval, denial, or confidence field,
    since AI routing is not a clinical decision."""
    # TEST-005F
    assert set(AIRoutingResult.model_fields.keys()) == {
        "ai_required",
        "requested_tasks",
    }
