# File Name: evidence.py
# Purpose: Defines the deterministic output model for comparing a submitted case against retrieved FHIR-style evidence.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# EVIDENCE MISMATCH REASONS
# Purpose:
# Lists every stable, deterministic reason the submitted case can
# disagree with retrieved FHIR-style evidence.
#
# Why:
# A fixed set of reason identifiers (instead of free-text explanations)
# keeps the result machine-checkable and easy to test, and matches the
# project's existing pattern for reporting deterministic reasons (see
# AIAnalysisFailureType, FHIRIntegrationFailureType).
# =====================================================================


class EvidenceMismatchReason(str, Enum):
    SERVICE_CODE_MISMATCH = "SERVICE_CODE_MISMATCH"
    DIAGNOSIS_CODE_MISMATCH = "DIAGNOSIS_CODE_MISMATCH"
    DOCUMENTATION_NOT_FOUND = "DOCUMENTATION_NOT_FOUND"


# =====================================================================
# EVIDENCE CONSISTENCY RESULT
# Purpose:
# Reports whether a submitted case's facts agree with the healthcare
# evidence retrieved for it, and exactly which facts (if any) disagree.
#
# Why:
# Keeping this a plain facts-and-reasons report — not a decision —
# matches the project's deterministic-first design: this rule answers
# "do the facts agree?", never "should this be approved?".
#
# Important Notes:
# This model intentionally has no approval, denial, medical_necessity,
# coverage, or confidence field. It reports consistency facts only.
# =====================================================================


class EvidenceConsistencyResult(BaseModel):
    """
    The outcome of comparing one submitted case against its retrieved
    FHIR-style evidence.

    is_consistent is True only when the service code matches, the
    diagnosis code matches, and no submitted documentation is missing
    from the retrieved evidence.
    """

    model_config = ConfigDict(extra="forbid")

    service_code_matches: bool
    diagnosis_code_matches: bool

    # Submitted documentation entries that were not found, by exact
    # name, in the retrieved evidence's supporting_documentation.
    missing_documentation: list[str] = Field(default_factory=list)

    is_consistent: bool

    # Every reason this case is inconsistent, in a fixed, predictable
    # order (service code, then diagnosis code, then documentation).
    # Empty when is_consistent is True.
    mismatch_reasons: list[EvidenceMismatchReason] = Field(default_factory=list)
