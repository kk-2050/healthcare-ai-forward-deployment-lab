# File Name: ai.py
# Purpose: Defines the approved AI task enum and the explicit AI-processing requirements/routing-result models for Phase 1.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AITask(str, Enum):
    SUMMARIZE_NARRATIVE = "summarize_narrative"
    IDENTIFY_AMBIGUITY = "identify_ambiguity"
    IDENTIFY_TEXT_INCONSISTENCIES = "identify_text_inconsistencies"
    SUGGEST_CLARIFYING_QUESTIONS = "suggest_clarifying_questions"


class AIProcessingRequirements(BaseModel):
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
    model_config = ConfigDict(extra="forbid")

    ai_required: bool
    requested_tasks: list[AITask]
