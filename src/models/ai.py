# File Name: ai.py
# Purpose: Defines the approved AI task enum and the explicit AI-processing requirements/routing-result models for Phase 1.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =====================================================================
# APPROVED AI TASKS
# Purpose:
# Lists every AI task this project is allowed to request. A request can
# only use one of these exact values.
#
# Why:
# The project must never let free-form or unapproved AI work run. Using
# a fixed enum (instead of a plain string) means an unsupported task
# name is rejected automatically by Pydantic before any code runs.
#
# Important Notes:
# AI may only summarize, look for ambiguity, look for inconsistencies,
# or suggest clarifying questions. It may not approve or deny care,
# invent clinical facts, or invent payer policy.
#
# Maintenance Note:
# If a new AI task is ever needed, add it here (and update the related
# tests) rather than accepting an arbitrary task string anywhere else.
# =====================================================================


class AITask(str, Enum):
    SUMMARIZE_NARRATIVE = "summarize_narrative"
    IDENTIFY_AMBIGUITY = "identify_ambiguity"
    IDENTIFY_TEXT_INCONSISTENCIES = "identify_text_inconsistencies"
    SUGGEST_CLARIFYING_QUESTIONS = "suggest_clarifying_questions"


class AIProcessingRequirements(BaseModel):
    """
    The list of approved AI tasks that have been explicitly requested
    for a case.

    This is an input to the deterministic AI-routing rule
    (src/rules/ai_routing.py), not a decision by itself. An empty list
    means no AI work is requested.
    """

    model_config = ConfigDict(extra="forbid")

    tasks: list[AITask] = Field(default_factory=list)

    @field_validator("tasks")
    @classmethod
    def deduplicate_tasks_preserving_order(cls, value: list[AITask]) -> list[AITask]:
        # A duplicate task request is redundant, not invalid, so it is
        # normalized deterministically (first occurrence kept) rather than
        # rejected or silently double-counted.
        seen: set[AITask] = set()
        deduplicated: list[AITask] = []
        for task in value:
            if task not in seen:
                seen.add(task)
                deduplicated.append(task)
        return deduplicated


class AIRoutingResult(BaseModel):
    """
    The outcome of the deterministic "is AI needed?" check.

    This only records a routing decision (do we need AI, and for which
    tasks). It never contains AI-generated content, a confidence score,
    or a clinical decision — those concerns belong to later steps.
    """

    model_config = ConfigDict(extra="forbid")

    # True when at least one approved task was requested.
    ai_required: bool

    # The exact approved tasks that were requested (echoes
    # AIProcessingRequirements.tasks after deduplication).
    requested_tasks: list[AITask]
