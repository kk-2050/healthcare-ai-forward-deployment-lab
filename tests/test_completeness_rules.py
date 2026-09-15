# File Name: test_completeness_rules.py
# Purpose: Tests deterministic completeness evaluation for validated synthetic prior authorization cases.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from datetime import date

from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness


def make_case(**overrides):
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


def test_no_requirements_case_is_complete():
    # TEST-002A
    case = make_case()
    requirements = CompletenessRequirements()

    result = evaluate_completeness(case, requirements)

    assert result.is_complete is True
    assert result.missing_fields == []
    assert result.missing_documentation == []


def test_all_required_documents_present_case_is_complete():
    # TEST-002B
    case = make_case(supporting_documentation=["SYN-DOC-A", "SYN-DOC-B"])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.is_complete is True
    assert result.missing_documentation == []


def test_one_missing_required_document_is_reported():
    # TEST-002C
    case = make_case(supporting_documentation=["SYN-DOC-A"])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == ["SYN-DOC-B"]
    assert result.is_complete is False


def test_multiple_missing_required_documents_are_reported():
    # TEST-002D
    case = make_case(supporting_documentation=[])
    requirements = CompletenessRequirements(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B", "SYN-DOC-C"]
    )

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == ["SYN-DOC-A", "SYN-DOC-B", "SYN-DOC-C"]
    assert result.is_complete is False


def test_clinical_notes_required_and_none_is_reported_missing():
    # TEST-002E
    case = make_case(clinical_notes=None)
    requirements = CompletenessRequirements(clinical_notes_required=True)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" in result.missing_fields
    assert result.is_complete is False


def test_clinical_notes_required_and_blank_is_reported_missing():
    # TEST-002F
    case = make_case(clinical_notes="   ")
    requirements = CompletenessRequirements(clinical_notes_required=True)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" in result.missing_fields
    assert result.is_complete is False


def test_clinical_notes_not_required_and_absent_is_not_reported():
    # TEST-002G
    case = make_case(clinical_notes=None)
    requirements = CompletenessRequirements(clinical_notes_required=False)

    result = evaluate_completeness(case, requirements)

    assert "clinical_notes" not in result.missing_fields
    assert result.is_complete is True


def test_extra_documentation_does_not_invalidate_complete_case():
    # TEST-002H
    case = make_case(supporting_documentation=["SYN-DOC-A", "SYN-DOC-EXTRA"])
    requirements = CompletenessRequirements(required_documentation=["SYN-DOC-A"])

    result = evaluate_completeness(case, requirements)

    assert result.missing_documentation == []
    assert result.is_complete is True


def test_missing_document_and_missing_clinical_notes_reports_both():
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
