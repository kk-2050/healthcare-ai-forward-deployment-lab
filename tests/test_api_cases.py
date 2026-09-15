# File Name: test_api_cases.py
# Purpose: Tests the /cases/validate FastAPI endpoint using synthetic data and the in-process TestClient only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the HTTP boundary of the project: they confirm
# the endpoint validates requests the same way the underlying Pydantic
# models do, reuses the deterministic completeness rule without
# duplicating it, and never calls a real network service. TestClient
# talks to the FastAPI app in-process — no server is started and no
# real HTTP traffic leaves the test process.

from fastapi.testclient import TestClient

from src.api.app import app
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness

client = TestClient(app)


def valid_case_payload(**overrides):
    """A minimal, fully valid synthetic case JSON payload."""
    data = {
        "case_id": "SYN-CASE-001",
        "member_id": "SYN-MEMBER-001",
        "provider_id": "SYN-PROVIDER-001",
        "requested_service_code": "SYN-SERVICE-001",
        "diagnosis_code": "SYN-DX-001",
        "requested_date": "2026-01-15",
    }
    data.update(overrides)
    return data


def valid_requirements_payload(**overrides):
    """A minimal, fully valid completeness-requirements JSON payload."""
    data = {
        "required_documentation": [],
        "clinical_notes_required": False,
    }
    data.update(overrides)
    return data


# =====================================================================
# VALID INPUT TESTS
# =====================================================================
def test_valid_complete_case_returns_200_and_is_complete_true():
    """Verify a valid, complete case returns HTTP 200 with
    is_complete=true and nothing reported missing."""
    # TEST-003A
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_complete"] is True
    assert body["missing_fields"] == []
    assert body["missing_documentation"] == []


def test_valid_incomplete_case_returns_200_and_missing_documentation():
    """Verify a valid but incomplete case still returns HTTP 200 (the
    request itself is well-formed) while reporting exactly what is
    missing."""
    # TEST-003B
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(supporting_documentation=["SYN-DOC-A"]),
            "requirements": valid_requirements_payload(
                required_documentation=["SYN-DOC-A", "SYN-DOC-B"]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_complete"] is False
    assert body["missing_documentation"] == ["SYN-DOC-B"]


def test_clinical_notes_required_and_missing_returns_200_with_missing_field():
    """Verify a case missing required clinical notes is reported in the
    response body rather than causing a request error."""
    # TEST-003G
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(),
            "requirements": valid_requirements_payload(clinical_notes_required=True),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "clinical_notes" in body["missing_fields"]
    assert body["is_complete"] is False


def test_response_contains_input_case_id():
    """Verify the response echoes back the submitted case_id, so a
    caller can match a response to the case it asked about."""
    # TEST-003H
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(case_id="SYN-CASE-999"),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 200
    assert response.json()["case_id"] == "SYN-CASE-999"


# =====================================================================
# VALIDATION FAILURE TESTS
# =====================================================================
def test_missing_required_case_field_returns_422():
    """Verify a request missing a required case field is rejected with
    HTTP 422, matching PriorAuthorizationCase's own validation."""
    # TEST-003C
    case_payload = valid_case_payload()
    del case_payload["case_id"]

    response = client.post(
        "/cases/validate",
        json={
            "case": case_payload,
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 422


def test_blank_required_string_returns_422():
    """Verify a whitespace-only required field is rejected with HTTP
    422, not silently accepted."""
    # TEST-003D
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(member_id="   "),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 422


def test_invalid_requested_date_returns_422():
    """Verify a non-date requested_date value is rejected with HTTP
    422."""
    # TEST-003E
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(requested_date="not-a-date"),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 422


def test_unknown_case_field_returns_422():
    """Verify an unexpected field inside the case payload is rejected
    with HTTP 422 — the API never silently ignores unknown fields."""
    # TEST-003F
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(unexpected_field="not allowed"),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 422


def test_unknown_top_level_request_field_is_rejected():
    """Verify an unexpected top-level field on the request body itself
    (outside "case"/"requirements") is rejected with HTTP 422."""
    # TEST-003J
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(),
            "requirements": valid_requirements_payload(),
            "unexpected_top_level_field": "not allowed",
        },
    )

    assert response.status_code == 422


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_endpoint_matches_direct_rule_evaluation():
    """Verify the endpoint's response is identical to calling
    evaluate_completeness() directly — proving the endpoint reuses the
    deterministic rule rather than re-implementing its own copy."""
    # TEST-003I
    case_data = valid_case_payload(supporting_documentation=["SYN-DOC-A"])
    requirements_data = valid_requirements_payload(
        required_documentation=["SYN-DOC-A", "SYN-DOC-B"],
        clinical_notes_required=True,
    )

    response = client.post(
        "/cases/validate",
        json={"case": case_data, "requirements": requirements_data},
    )

    direct_case = PriorAuthorizationCase(**case_data)
    direct_requirements = CompletenessRequirements(**requirements_data)
    direct_result = evaluate_completeness(direct_case, direct_requirements)

    body = response.json()
    assert body["is_complete"] == direct_result.is_complete
    assert body["missing_fields"] == direct_result.missing_fields
    assert body["missing_documentation"] == direct_result.missing_documentation
