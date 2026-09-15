# File Name: completeness.py
# Purpose: Implements deterministic completeness checks for validated synthetic prior authorization cases.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements, CompletenessResult


def evaluate_completeness(
    case: PriorAuthorizationCase,
    requirements: CompletenessRequirements,
) -> CompletenessResult:
    missing_fields: list[str] = []
    missing_documentation: list[str] = []

    if requirements.clinical_notes_required:
        notes = case.clinical_notes
        if notes is None or notes.strip() == "":
            missing_fields.append("clinical_notes")

    provided_documentation = set(case.supporting_documentation)
    for required_document in requirements.required_documentation:
        if required_document not in provided_documentation:
            missing_documentation.append(required_document)

    is_complete = not missing_fields and not missing_documentation

    return CompletenessResult(
        missing_fields=missing_fields,
        missing_documentation=missing_documentation,
        is_complete=is_complete,
    )
