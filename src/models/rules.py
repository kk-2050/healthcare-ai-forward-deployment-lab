# File Name: rules.py
# Purpose: Defines the input requirements and output result models for deterministic case completeness evaluation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# COMPLETENESS REQUIREMENTS AND RESULT MODELS
# Purpose:
# Defines what "complete" means for a case (CompletenessRequirements)
# and what the completeness check reports back (CompletenessResult).
#
# Why:
# Keeping "what is required" and "what the case is missing" as two
# separate, explicit models makes the completeness rule in
# src/rules/completeness.py easy to test and easy to explain: it is a
# pure function of (case, requirements) -> result, with no hidden state.
#
# Important Notes:
# - These models hold facts only (what documents/fields are required,
#   what is missing). They do not decide medical necessity or
#   approval/denial.
# - Real payer-specific documentation rules are not defined here; the
#   caller supplies whatever requirements apply, so this stays a
#   generic, reusable contract.
# =====================================================================


class CompletenessRequirements(BaseModel):
    """
    What a case must contain to be considered complete.

    This is supplied by the caller (not hard-coded) so real business
    rules can later come from configuration or a database without
    changing this model or the completeness-checking code.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Document names that must be present in the case's
    # supporting_documentation list. Empty by default: no documents
    # required unless the caller says otherwise.
    required_documentation: list[str] = Field(default_factory=list)

    # Whether clinical_notes must be present (and non-blank) for the
    # case to be complete. False by default.
    clinical_notes_required: bool = False


class CompletenessResult(BaseModel):
    """
    The outcome of one deterministic completeness check.

    Reports exactly what is missing (if anything) so the workflow and
    the API can explain the result, rather than returning a bare
    true/false with no reasoning behind it.
    """

    model_config = ConfigDict(extra="forbid")

    # Names of required non-documentation fields that are missing
    # (currently only "clinical_notes" can appear here).
    missing_fields: list[str] = Field(default_factory=list)

    # Required documents that were not found in the case.
    missing_documentation: list[str] = Field(default_factory=list)

    # True only when both lists above are empty.
    is_complete: bool
