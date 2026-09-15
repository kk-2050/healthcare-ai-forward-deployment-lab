# File Name: test_completeness_rules.py
# Purpose: Tests deterministic completeness evaluation for validated synthetic prior authorization cases.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect evaluate_completeness(), the deterministic rule
# that decides whether a case has all the documentation and clinical
# notes it explicitly requires. This rule never uses AI and never
# decides approval or denial — it only reports missing facts.

from datetime import date

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness


def make_case(**overrides):
    """Builds a synthetic case with sensible defaults, letting each
    test override only the fields it cares about."""
    data = {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-SERVICE-001",
        "diagnosis_code": "SYN-DX-001",
        "requested_date": date(2026, 1, 15),
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


# =====================================================================
# COMPLETE CASE TESTS
# =====================================================================
def test_no_requirements_case_is_complete():
    """Verify a case is complete when no documentation or clinical
    notes are required at all."""
    # TEST-002A
    case = make_case()
    requirements = CompletenessRequirements()

    result = evaluate_completeness(case, requirements)

    assert result.is_complete is True
    assert result.missing_fields == []
    assert result.missing_documentation == []


def test_all_required_documents_present_case_is_complete():
    """Verify a case is complete once every required document is
    present, by exact name."""
    # TEST-002B
    case = make_case(supporting_documentation=["SYN-DOC-A", "SYN-DOC-B"])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.is_complete is True
    assert result.missing_documentation == []


def test_extra_documentation_does_not_invalidate_complete_case():
    """Verify extra documents beyond what is required do not make an
    otherwise-complete case incomplete."""
    # TEST-002H
    case = make_case(supporting_documentation=["SYN-DOC-A", "SYN-DOC-EXTRA"])
    requirements = CompletenessRequirements(required_documentation=["SYN-DOC-A"])

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == []
    assert result.is_complete is True


def test_clinical_notes_not_required_and_absent_is_not_reported():
    """Verify clinical notes are not reported missing when they were
    never required in the first place."""
    # TEST-002G
    case = make_case(clinical_notes=None)
    requirements = CompletenessRequirements(clinical_notes_required=False)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" not in result.missing_fields
    assert result.is_complete is True


# =====================================================================
# MISSING DOCUMENTATION TESTS
# =====================================================================
def test_one_missing_required_document_is_reported():
    """Verify exactly one missing required document is named in the
    result, not just a generic "incomplete" flag."""
    # TEST-002C
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == ["SYN-DOC-B"]
    assert result.is_complete is False


def test_multiple_missing_required_documents_are_reported():
    """Verify every missing required document is reported, not only the
    first one found."""
    # TEST-002D
    case = make_case(supporting_documentation=[])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B", "SYN-DOC-C"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == ["SYN-DOC-A", "SYN-DOC-B", "SYN-DOC-C"]
    assert result.is_complete is False


# =====================================================================
# MISSING CLINICAL NOTES TESTS
# =====================================================================
def test_clinical_notes_required_and_none_is_reported_missing():
    """Verify required clinical notes that are entirely absent (None)
    are reported as missing."""
    # TEST-002E
    case = make_case(clinical_notes=None)
    requirements = CompletenessRequirements(clinical_notes_required=True)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" in result.missing_fields
    assert result.is_complete is False


def test_clinical_notes_required_and_blank_is_reported_missing():
    """Verify required clinical notes that are only whitespace are
    treated the same as missing, not as meaningful content."""
    # TEST-002F
    case = make_case(clinical_notes="   ")
    requirements = CompletenessRequirements(clinical_notes_required=True)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" in result.missing_fields
    assert result.is_complete is False


# =====================================================================
# COMBINED FAILURE / SAFETY BOUNDARY TESTS
# =====================================================================
def test_missing_document_and_missing_clinical_notes_reports_both():
    """Verify a case missing both a document and required clinical
    notes reports both categories, not just one."""
    # TEST-002I
    case = make_case(supporting_documentation=["SYN-DOC-A"], clinical_notes=None)
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"],
        clinical_notes_required=True,
    )

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == ["SYN-DOC-B"]
    assert "clinical_notes" in result.missing_fields
    assert result.is_complete is False


def test_rule_evaluation_does_not_mutate_case():
    """Verify running the completeness rule never modifies the case
    object it was given — the rule must only read, never write."""
    # TEST-002J
    case = make_case(supporting_documentation=["SYN-DOC-A"], clinical_notes=None)
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"],
        clinical_notes_required=True,
    )

    original_documentation = list(case.supporting_documentation)
    original_notes = case.clinical_notes

    evaluate_completeness(case, requirements)

    assert case.supporting_documentation == original_documentation
    assert case.clinical_notes == original_notes
