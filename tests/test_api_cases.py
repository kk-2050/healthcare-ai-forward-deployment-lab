# File Name: test_api_cases.py
# Purpose: Tests the /cases/validate FastAPI endpoint using synthetic data and the in-process TestClient only.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from fastapi.testclient import TestClient

from src.api.app import app
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.rules.completeness import evaluate_completeness

client = TestClient(app)


def valid_case_payload(**overrides):
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
    data = {
        "required_documentation": [],
        "clinical_notes_required": False,
    }
    data.update(overrides)
    return data


def test_valid_complete_case_returns_200_and_is_complete_true():
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


def test_missing_required_case_field_returns_422():
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
    # TEST-003F
    response = client.post(
        "/cases/validate",
        json={
            "case": valid_case_payload(unexpected_field="not allowed"),
            "requirements": valid_requirements_payload(),
        },
    )

    assert response.status_code == 422


def test_clinical_notes_required_and_missing_returns_200_with_missing_field():
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


def test_endpoint_matches_direct_rule_evaluation():
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


def test_unknown_top_level_request_field_is_rejected():
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
