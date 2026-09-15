# File Name: test_case_model.py
# Purpose: Tests schema validation for the PriorAuthorizationCase model using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

import pytest
from pydantic import ValidationError

from src.models.case import PriorAuthorizationCase


def valid_case_data():
    return {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-SERVICE-001",
        "diagnosis_code": "SYN-DX-001",
        "requested_date": "2026-01-15",
    }


def test_valid_synthetic_case_is_accepted():
    # TEST-001A
    case = PriorAuthorizationCase(**valid_case_data())

    assert case.case_id == "SYN-CASE-001"
    assert case.member_id == "SYN-MEMBER-001"
    assert case.provider_id == "SYN-PROVIDER-001"
    assert case.requested_service_code == "SYN-SERVICE-001"
    assert case.diagnosis_code == "SYN-DX-001"
    assert case.requested_date.isoformat() == "2026-01-15"


def test_missing_required_field_raises_validation_error():
    # TEST-001B
    data = valid_case_data()
    del data["case_id"]

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_invalid_requested_date_raises_validation_error():
    # TEST-001C
    data = valid_case_data()
    data["requested_date"] = "not-a-date"

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_blank_required_string_is_rejected_after_whitespace_handling():
    # TEST-001D
    data = valid_case_data()
    data["member_id"] = "   "

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_clinical_notes_may_be_omitted():
    # TEST-001E
    data = valid_case_data()

    case = PriorAuthorizationCase(**data)

    assert case.clinical_notes is None


def test_supporting_documentation_defaults_to_empty_list():
    # TEST-001F
    data = valid_case_data()

    case = PriorAuthorizationCase(**data)

    assert case.supporting_documentation == []


def test_unknown_extra_field_is_rejected():
    # TEST-001G
    data = valid_case_data()
    data["unexpected_field"] = "not allowed"

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_instances_do_not_share_mutable_supporting_documentation_list():
    # TEST-001H
    case_one = PriorAuthorizationCase(**valid_case_data())
    case_two = PriorAuthorizationCase(**valid_case_data())

    case_one.supporting_documentation.append("SYN-DOC-001")

    assert case_one.supporting_documentation == ["SYN-DOC-001"]
    assert case_two.supporting_documentation == []


def test_required_string_field_whitespace_is_stripped():
    # TEST-001I
    data = valid_case_data()
    data["case_id"] = "  SYN-CASE-001  "

    case = PriorAuthorizationCase(**data)

    assert case.case_id == "SYN-CASE-001"


def test_clinical_notes_explicit_none_is_accepted():
    # TEST-001J
    data = valid_case_data()
    data["clinical_notes"] = None

    case = PriorAuthorizationCase(**data)

    assert case.clinical_notes is None
