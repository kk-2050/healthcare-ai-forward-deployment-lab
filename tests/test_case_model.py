# File Name: test_case_model.py
# Purpose: Tests schema validation for the PriorAuthorizationCase model using synthetic data only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the very first line of defense in the project:
# PriorAuthorizationCase must reject malformed synthetic input before
# any business rule, AI step, or API endpoint ever sees it.

import pytest
from pydantic import ValidationError

from src.models.case import PriorAuthorizationCase


def valid_case_data():
    """A minimal, fully valid synthetic case payload used as a baseline
    for tests that then tweak one field at a time."""
    return {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-SERVICE-001",
        "diagnosis_code": "SYN-DX-001",
        "requested_date": "2026-01-15",
    }


# =====================================================================
# VALID INPUT TESTS
# =====================================================================
def test_valid_synthetic_case_is_accepted():
    """Verify a fully valid synthetic case is accepted and every field
    round-trips correctly."""
    # TEST-001A
    case = PriorAuthorizationCase(**valid_case_data())

    assert case.case_id == "SYN-CASE-001"
    assert case.member_id == "SYN-MEMBER-001"
    assert case.provider_id == "SYN-PROVIDER-001"
    assert case.requested_service_code == "SYN-SERVICE-001"
    assert case.diagnosis_code == "SYN-DX-001"
    assert case.requested_date.isoformat() == "2026-01-15"


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_missing_required_field_raises_validation_error():
    """Verify a case missing a required field is rejected instead of
    silently accepted with a blank value."""
    # TEST-001B
    data = valid_case_data()
    del data["case_id"]

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_invalid_requested_date_raises_validation_error():
    """Verify a non-date string for requested_date is rejected rather
    than stored as-is."""
    # TEST-001C
    data = valid_case_data()
    data["requested_date"] = "not-a-date"

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_blank_required_string_is_rejected_after_whitespace_handling():
    """Verify a required field that is only whitespace is rejected, not
    accepted as if it were meaningful text."""
    # TEST-001D
    data = valid_case_data()
    data["member_id"] = "   "

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


def test_unknown_extra_field_is_rejected():
    """Verify an unexpected field is rejected outright, so a typo or an
    unapproved client field can never be silently ignored."""
    # TEST-001G
    data = valid_case_data()
    data["unexpected_field"] = "not allowed"

    with pytest.raises(ValidationError):
        PriorAuthorizationCase(**data)


# =====================================================================
# OPTIONAL / DEFAULT FIELD TESTS
# =====================================================================
def test_clinical_notes_may_be_omitted():
    """Verify clinical_notes is optional and defaults to None when not
    supplied."""
    # TEST-001E
    data = valid_case_data()

    case = PriorAuthorizationCase(**data)

    assert case.clinical_notes is None


def test_supporting_documentation_defaults_to_empty_list():
    """Verify supporting_documentation defaults to an empty list rather
    than requiring the caller to always supply one."""
    # TEST-001F
    data = valid_case_data()

    case = PriorAuthorizationCase(**data)

    assert case.supporting_documentation == []


def test_clinical_notes_explicit_none_is_accepted():
    """Verify explicitly passing clinical_notes=None is accepted the
    same way as omitting it."""
    # TEST-001J
    data = valid_case_data()
    data["clinical_notes"] = None

    case = PriorAuthorizationCase(**data)

    assert case.clinical_notes is None


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_instances_do_not_share_mutable_supporting_documentation_list():
    """Verify each case gets its own independent list object, so
    appending a document to one case can never leak into another case
    (a classic Python mutable-default-argument bug this model avoids
    via default_factory)."""
    # TEST-001H
    case_one = PriorAuthorizationCase(**valid_case_data())
    case_two = PriorAuthorizationCase(**valid_case_data())

    case_one.supporting_documentation.append("SYN-DOC-001")

    assert case_one.supporting_documentation == ["SYN-DOC-001"]
    assert case_two.supporting_documentation == []


def test_required_string_field_whitespace_is_stripped():
    """Verify leading/trailing whitespace is stripped from required
    string fields before they are stored, so "  X  " and "X" are
    treated the same."""
    # TEST-001I
    data = valid_case_data()
    data["case_id"] = "  SYN-CASE-001  "

    case = PriorAuthorizationCase(**data)

    assert case.case_id == "SYN-CASE-001"
