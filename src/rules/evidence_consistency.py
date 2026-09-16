# File Name: evidence_consistency.py
# Purpose: Implements the deterministic rule comparing a submitted case against retrieved FHIR-style evidence.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from src.integrations.fhir_models import FHIRCaseEvidence
from src.models.case import PriorAuthorizationCase
from src.models.evidence import EvidenceConsistencyResult, EvidenceMismatchReason


# =====================================================================
# EVIDENCE CONSISTENCY CHECK
# Purpose:
# Compares submitted prior-authorization facts (the case) with
# retrieved healthcare evidence (the FHIR-style Bundle extraction), and
# reports exactly what matches and what does not.
#
# Why:
# Conflicting facts should be detected deterministically before AI
# language analysis is considered. A case that claims one service or
# diagnosis while the healthcare system's own records show another
# should never be allowed to look "consistent" by accident.
#
# Input:
# - case: an already-validated PriorAuthorizationCase (what was
#   submitted).
# - evidence: an already-validated FHIRCaseEvidence (what the
#   healthcare integration retrieved) — see src/integrations/fhir_client.py.
#
# Output:
# An EvidenceConsistencyResult reporting service/diagnosis code
# agreement, any submitted documentation missing from the evidence, and
# a stable list of mismatch reasons.
#
# Important Notes:
# - Matching is exact string/exact membership only. There is no
#   fuzzy matching, case-folding, punctuation stripping, synonym
#   expansion, or code-system translation here. "PT Summary" is not
#   treated as equal to "Physical Therapy Summary". If normalization
#   is ever needed, it must be a separate, explicitly documented rule
#   — not added quietly here.
# - This function does not use AI and does not call any AI/OpenAI code.
# - This function does not decide approval, denial, medical necessity,
#   coverage, or payer policy. It only reports whether submitted facts
#   agree with retrieved evidence.
# - This function does not decide documentation completeness (was
#   every required document supplied?) — that remains the
#   responsibility of src/rules/completeness.py. An empty submitted
#   documentation list simply produces no missing-documentation
#   mismatches here, not a completeness judgment.
# - Neither input is modified.
# =====================================================================
def evaluate_evidence_consistency(
    case: PriorAuthorizationCase,
    evidence: FHIRCaseEvidence,
) -> EvidenceConsistencyResult:
    """
    Deterministically compares a submitted case against retrieved
    FHIR-style evidence and reports factual agreement/disagreement.

    is_consistent is True only when the service code matches, the
    diagnosis code matches, and every submitted document is found, by
    exact name, in the evidence.
    """
    service_code_matches = case.requested_service_code == evidence.requested_service_code
    diagnosis_code_matches = case.diagnosis_code in evidence.diagnosis_codes

    # Exact-name membership check only — no fuzzy/synonym matching.
    evidence_documentation = set(evidence.supporting_documentation)
    missing_documentation = [
        document
        for document in case.supporting_documentation
        if document not in evidence_documentation
    ]

    mismatch_reasons: list[EvidenceMismatchReason] = []
    if not service_code_matches:
        mismatch_reasons.append(EvidenceMismatchReason.SERVICE_CODE_MISMATCH)
    if not diagnosis_code_matches:
        mismatch_reasons.append(EvidenceMismatchReason.DIAGNOSIS_CODE_MISMATCH)
    if missing_documentation:
        mismatch_reasons.append(EvidenceMismatchReason.DOCUMENTATION_NOT_FOUND)

    is_consistent = (
        service_code_matches
        and diagnosis_code_matches
        and not missing_documentation
    )

    return EvidenceConsistencyResult(
        service_code_matches=service_code_matches,
        diagnosis_code_matches=diagnosis_code_matches,
        missing_documentation=missing_documentation,
        is_consistent=is_consistent,
        mismatch_reasons=mismatch_reasons,
    )
