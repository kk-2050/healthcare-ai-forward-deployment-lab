# File Name: completeness.py
# Purpose: Implements deterministic completeness checks for validated synthetic prior authorization cases.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements, CompletenessResult


# =====================================================================
# COMPLETENESS VALIDATION
# Purpose:
# Checks whether a case contains the documentation and clinical notes
# that are explicitly required by the supplied requirements.
#
# Why:
# Simple, factual checks like this should use deterministic rules
# before AI is ever considered. This keeps the result predictable,
# explainable, and testable without needing an AI call.
#
# Input:
# - case: an already-validated PriorAuthorizationCase.
# - requirements: the CompletenessRequirements to check the case
#   against (supplied by the caller, never hard-coded here).
#
# Output:
# A CompletenessResult listing exactly what (if anything) is missing.
#
# Important Notes:
# - This logic does not use an LLM and does not guess.
# - It does not approve or deny clinical care — it only reports facts.
# - Document matching is exact (no fuzzy/synonym matching), and this
#   function never modifies the case or requirements it is given.
# - Do not add payer-specific rules here. Real business rules should be
#   supplied by the caller as requirements, not hard-coded in this
#   function.
# =====================================================================
def evaluate_completeness(
    case: PriorAuthorizationCase,
    requirements: CompletenessRequirements,
) -> CompletenessResult:
    """
    Checks whether a case has everything the given requirements demand.

    Returns a CompletenessResult with is_complete=True only when no
    required documentation and no required clinical notes are missing.
    """
    missing_fields: list[str] = []
    missing_documentation: list[str] = []

    # Clinical notes count as missing if they are required but absent,
    # or present only as whitespace (e.g., " ") after stripping.
    if requirements.clinical_notes_required:
        notes = case.clinical_notes
        if notes is None or notes.strip() == "":
            missing_fields.append("clinical_notes")

    # Exact-match check: a required document is only satisfied if it
    # appears, by exact name, in the case's supporting_documentation.
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
