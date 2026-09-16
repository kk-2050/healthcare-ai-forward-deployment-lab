# File Name: test_evidence_consistency.py
# Purpose: Tests the deterministic evidence-consistency rule comparing a submitted case against FHIR-style evidence.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect evaluate_evidence_consistency(), the deterministic
# rule that checks whether a submitted case's facts agree with the
# healthcare evidence retrieved for it. This rule never uses AI, never
# fuzzy-matches text, and never decides approval, denial, or medical
# necessity — it only reports whether facts match, exactly.

import inspect
from datetime import date

from src.integrations.fhir_models import FHIRCaseEvidence
from src.models.case import PriorAuthorizationCase
from src.models.evidence import EvidenceConsistencyResult, EvidenceMismatchReason
from src.rules import evidence_consistency
from src.rules.evidence_consistency import evaluate_evidence_consistency


def make_case(**overrides):
    """A minimal, fully valid synthetic case whose facts agree with
    make_evidence()'s defaults, letting each test override only what
    it cares about."""
    data = {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-LUMBAR-MRI",
        "diagnosis_code": "SYN-LOW-BACK-PAIN",
        "requested_date": date(2026, 1, 15),
        "supporting_documentation": ["Physical Therapy Summary"],
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


def make_evidence(**overrides):
    """A minimal, fully valid synthetic FHIRCaseEvidence whose facts
    agree with make_case()'s defaults."""
    data = {
        "service_request_id": "SYN-SR-001",
        "requested_service_code": "SYN-LUMBAR-MRI",
        "diagnosis_codes": ["SYN-LOW-BACK-PAIN"],
        "supporting_documentation": ["Physical Therapy Summary"],
        "source_resource_ids": ["SYN-SR-001"],
    }
    data.update(overrides)
    return FHIRCaseEvidence(**data)


# =====================================================================
# CONSISTENT CASE TESTS
# =====================================================================
def test_all_facts_match_is_consistent():
    """Verify a case whose service code, diagnosis code, and
    documentation all agree with the evidence is reported consistent,
    with no mismatch reasons."""
    # TEST-012A
    result = evaluate_evidence_consistency(make_case(), make_evidence())

    assert result.is_consistent is True
    assert result.service_code_matches is True
    assert result.diagnosis_code_matches is True
    assert result.missing_documentation == []
    assert result.mismatch_reasons == []


def test_empty_submitted_documentation_produces_no_missing_documentation():
    """Verify a case submitted with no documentation at all produces an
    empty missing_documentation list — this rule only compares what was
    submitted, it does not decide whether documentation was required."""
    # TEST-012G
    case = make_case(supporting_documentation=[])
    evidence = make_evidence(supporting_documentation=["Physical Therapy Summary"])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.missing_documentation == []


def test_extra_fhir_documentation_does_not_create_mismatch():
    """Verify extra documentation present in the evidence but not
    submitted by the case does not, by itself, make the case
    inconsistent — only missing submitted documentation matters."""
    # TEST-012H
    case = make_case(supporting_documentation=["Physical Therapy Summary"])
    evidence = make_evidence(
        supporting_documentation=["Physical Therapy Summary", "SYN-EXTRA-FHIR-DOC"]
    )

    result = evaluate_evidence_consistency(case, evidence)

    assert result.missing_documentation == []
    assert result.is_consistent is True


# =====================================================================
# MISMATCH DETECTION TESTS
# =====================================================================
def test_service_code_mismatch_detected():
    """Verify a submitted service code that differs from the evidence
    is detected and marks the case inconsistent."""
    # TEST-012B
    case = make_case(requested_service_code="SYN-DIFFERENT-CODE")

    result = evaluate_evidence_consistency(case, make_evidence())

    assert result.service_code_matches is False
    assert result.is_consistent is False
    assert EvidenceMismatchReason.SERVICE_CODE_MISMATCH in result.mismatch_reasons


def test_diagnosis_code_mismatch_detected():
    """Verify a submitted diagnosis code that is not among the
    evidence's diagnosis codes is detected and marks the case
    inconsistent."""
    # TEST-012C
    case = make_case(diagnosis_code="SYN-DIFFERENT-DX")

    result = evaluate_evidence_consistency(case, make_evidence())

    assert result.diagnosis_code_matches is False
    assert result.is_consistent is False
    assert EvidenceMismatchReason.DIAGNOSIS_CODE_MISMATCH in result.mismatch_reasons


def test_diagnosis_matches_one_of_multiple_retrieved_codes():
    """Verify a submitted diagnosis code matches successfully as long
    as it equals any one of several diagnosis codes retrieved from
    evidence — a case can be justified by more than one condition."""
    # TEST-012D
    case = make_case(diagnosis_code="SYN-LOW-BACK-PAIN")
    evidence = make_evidence(diagnosis_codes=["SYN-OTHER-DX", "SYN-LOW-BACK-PAIN"])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.diagnosis_code_matches is True


def test_missing_submitted_documentation_detected():
    """Verify a submitted document not found (by exact name) in the
    evidence is reported as missing and marks the case inconsistent."""
    # TEST-012E
    case = make_case(
        supporting_documentation=["Physical Therapy Summary", "SYN-EXTRA-DOC"]
    )
    evidence = make_evidence(supporting_documentation=["Physical Therapy Summary"])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.missing_documentation == ["SYN-EXTRA-DOC"]
    assert result.is_consistent is False
    assert EvidenceMismatchReason.DOCUMENTATION_NOT_FOUND in result.mismatch_reasons


def test_multiple_missing_documentation_items_retained():
    """Verify every missing submitted document is reported, not just
    the first one found."""
    # TEST-012F
    case = make_case(supporting_documentation=["SYN-DOC-A", "SYN-DOC-B"])
    evidence = make_evidence(supporting_documentation=[])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.missing_documentation == ["SYN-DOC-A", "SYN-DOC-B"]


# =====================================================================
# EXACT-MATCH-ONLY (NO FUZZY MATCHING) TESTS
# =====================================================================
def test_near_match_document_names_do_not_fuzzy_match():
    """Verify a near-match document name ("PT Summary" vs. "Physical
    Therapy Summary") is treated as a genuine mismatch, not silently
    accepted as the same document."""
    # TEST-012I
    case = make_case(supporting_documentation=["PT Summary"])
    evidence = make_evidence(supporting_documentation=["Physical Therapy Summary"])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.missing_documentation == ["PT Summary"]


def test_service_code_comparison_is_exact():
    """Verify service code comparison is case-sensitive exact string
    equality — no case-folding or normalization is applied."""
    # TEST-012J
    case = make_case(requested_service_code="syn-lumbar-mri")
    evidence = make_evidence(requested_service_code="SYN-LUMBAR-MRI")

    result = evaluate_evidence_consistency(case, evidence)

    assert result.service_code_matches is False


def test_diagnosis_comparison_is_exact():
    """Verify diagnosis code comparison is case-sensitive exact string
    equality."""
    # TEST-012K
    case = make_case(diagnosis_code="syn-low-back-pain")
    evidence = make_evidence(diagnosis_codes=["SYN-LOW-BACK-PAIN"])

    result = evaluate_evidence_consistency(case, evidence)

    assert result.diagnosis_code_matches is False


# =====================================================================
# MISMATCH REASON STABILITY TESTS
# =====================================================================
def test_mismatch_reasons_are_deterministic_and_stable():
    """Verify calling the rule twice with the same input produces the
    exact same mismatch reasons, in the same order — the rule must
    never vary between calls."""
    # TEST-012L
    case = make_case(requested_service_code="SYN-DIFFERENT-CODE")
    evidence = make_evidence()

    result_one = evaluate_evidence_consistency(case, evidence)
    result_two = evaluate_evidence_consistency(case, evidence)

    assert result_one.mismatch_reasons == result_two.mismatch_reasons
    assert result_one.mismatch_reasons == [EvidenceMismatchReason.SERVICE_CODE_MISMATCH]


def test_multiple_mismatch_reasons_can_coexist():
    """Verify a case with several simultaneous disagreements reports
    every applicable mismatch reason, not just the first one found."""
    # TEST-012M
    case = make_case(
        requested_service_code="SYN-DIFFERENT-CODE",
        diagnosis_code="SYN-DIFFERENT-DX",
        supporting_documentation=["SYN-MISSING-DOC"],
    )

    result = evaluate_evidence_consistency(case, make_evidence())

    assert set(result.mismatch_reasons) == {
        EvidenceMismatchReason.SERVICE_CODE_MISMATCH,
        EvidenceMismatchReason.DIAGNOSIS_CODE_MISMATCH,
        EvidenceMismatchReason.DOCUMENTATION_NOT_FOUND,
    }
    assert result.is_consistent is False


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_input_case_is_not_mutated():
    """Verify evaluating consistency never modifies the submitted case
    object."""
    # TEST-012N
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    evidence = make_evidence(supporting_documentation=[])

    original_documentation = list(case.supporting_documentation)
    original_service_code = case.requested_service_code

    evaluate_evidence_consistency(case, evidence)

    assert case.supporting_documentation == original_documentation
    assert case.requested_service_code == original_service_code


def test_input_evidence_is_not_mutated():
    """Verify evaluating consistency never modifies the retrieved
    evidence object."""
    # TEST-012O
    case = make_case()
    evidence = make_evidence(diagnosis_codes=["SYN-LOW-BACK-PAIN"])

    original_diagnosis_codes = list(evidence.diagnosis_codes)

    evaluate_evidence_consistency(case, evidence)

    assert evidence.diagnosis_codes == original_diagnosis_codes


def test_result_contains_no_approval_denial_fields():
    """Verify EvidenceConsistencyResult exposes only consistency facts
    — never an approval, denial, medical-necessity, coverage, or
    confidence field, since this rule never makes a clinical or payer
    decision."""
    # TEST-012P
    assert set(EvidenceConsistencyResult.model_fields.keys()) == {
        "service_code_matches",
        "diagnosis_code_matches",
        "missing_documentation",
        "is_consistent",
        "mismatch_reasons",
    }


def test_rule_contains_no_ai_dependency():
    """Verify the evidence-consistency module imports nothing from
    src/ai/* and does not import an OpenAI/LLM library — this rule is
    deterministic-only and must never depend on AI. (Its documentation
    comments are allowed to mention AI/OpenAI by name when explaining
    this boundary; only actual import statements are checked here.)"""
    # TEST-012Q
    import_lines = [
        line.strip()
        for line in inspect.getsource(evidence_consistency).splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]

    assert not any("src.ai" in line for line in import_lines)
    assert not any("openai" in line.lower() for line in import_lines)
