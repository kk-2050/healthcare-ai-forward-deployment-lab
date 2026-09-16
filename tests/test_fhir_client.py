# File Name: test_fhir_client.py
# Purpose: Tests the synthetic FHIR-style client and evidence extraction entirely offline using httpx.MockTransport.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect FHIRStyleClient and its extraction logic. Every
# test uses httpx.MockTransport, an offline httpx test mechanism that
# never opens a real network socket, and every resource ID/value used
# is synthetic. No real healthcare system, Epic/Cerner integration, or
# public FHIR server is contacted anywhere in this file.

import httpx

from src.integrations.fhir_client import FHIRStyleClient
from src.integrations.fhir_models import (
    FHIRBundle,
    FHIRIntegrationFailureType,
)


# =====================================================================
# SYNTHETIC BUNDLE FIXTURES
# =====================================================================
def valid_entries():
    """A minimal, fully valid synthetic Bundle entry list: one
    ServiceRequest referencing one Condition, plus one
    DocumentReference."""
    return [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "SYN-SR-001",
                "status": "active",
                "intent": "order",
                "code": {
                    "coding": [
                        {
                            "system": "http://example.org/synthetic-codes",
                            "code": "SYN-LUMBAR-MRI",
                            "display": "Lumbar MRI (synthetic)",
                        }
                    ]
                },
                "reasonReference": [{"reference": "Condition/SYN-COND-001"}],
            }
        },
        {
            "resource": {
                "resourceType": "Condition",
                "id": "SYN-COND-001",
                "code": {
                    "coding": [
                        {
                            "system": "http://example.org/synthetic-codes",
                            "code": "SYN-LOW-BACK-PAIN",
                            "display": "Low back pain (synthetic)",
                        }
                    ]
                },
            }
        },
        {
            "resource": {
                "resourceType": "DocumentReference",
                "id": "SYN-DOC-001",
                "status": "current",
                "content": [{"title": "Physical Therapy Summary"}],
            }
        },
    ]


def valid_bundle_json(entry=None):
    """A minimal, fully valid synthetic Bundle JSON body."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": valid_entries() if entry is None else entry,
    }


def make_client(
    json_body=None, status_code=200, raw_content=None, raise_error=None
) -> httpx.Client:
    """
    Builds an httpx.Client backed by httpx.MockTransport -- an offline
    test double that never opens a socket. Exactly one of json_body,
    raw_content, or raise_error should be supplied per test.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error is not None:
            raise raise_error
        if raw_content is not None:
            return httpx.Response(status_code, content=raw_content)
        return httpx.Response(status_code, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# =====================================================================
# VALID BUNDLE TESTS
# =====================================================================
def test_valid_synthetic_bundle_validates():
    """Verify a fully valid synthetic Bundle passes FHIRBundle schema
    validation, proving the small resource subset is modeled
    correctly."""
    # TEST-010A
    bundle = FHIRBundle.model_validate(valid_bundle_json())

    assert bundle.resourceType == "Bundle"
    assert len(bundle.entry) == 3


def test_service_request_code_is_extracted():
    """Verify the requested service code from ServiceRequest.code is
    extracted into the normalized evidence."""
    # TEST-010B
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json()),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is True
    assert outcome.evidence.requested_service_code == "SYN-LUMBAR-MRI"


def test_referenced_condition_diagnosis_code_is_extracted():
    """Verify the diagnosis code from the Condition referenced by
    ServiceRequest.reasonReference is extracted."""
    # TEST-010C
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json()),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is True
    assert outcome.evidence.diagnosis_codes == ["SYN-LOW-BACK-PAIN"]


def test_document_reference_title_is_extracted():
    """Verify the document title from DocumentReference.content is
    extracted into supporting_documentation."""
    # TEST-010D
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json()),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is True
    assert outcome.evidence.supporting_documentation == [
        "Physical Therapy Summary"
    ]


def test_source_resource_ids_are_retained_for_traceability():
    """Verify every contributing resource ID (ServiceRequest, Condition,
    DocumentReference) is retained, so the evidence can be traced back
    to the exact resources it came from."""
    # TEST-010E
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json()),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is True
    assert set(outcome.evidence.source_resource_ids) == {
        "SYN-SR-001",
        "SYN-COND-001",
        "SYN-DOC-001",
    }


# =====================================================================
# SCHEMA / STRUCTURE FAILURE TESTS
# =====================================================================
def test_unsupported_resource_type_is_rejected():
    """Verify a resource type outside the approved subset (e.g.
    "Patient") is rejected as UNSUPPORTED_RESOURCE_TYPE, never silently
    accepted or ignored."""
    # TEST-010F
    entry = [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "SYN-PATIENT-001",
            }
        }
    ]
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json(entry=entry)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert (
        outcome.failure_type == FHIRIntegrationFailureType.UNSUPPORTED_RESOURCE_TYPE
    )
    assert outcome.evidence is None


def test_missing_service_request_fails_safely():
    """Verify a Bundle with no ServiceRequest resource fails safely
    with MISSING_SERVICE_REQUEST, instead of returning empty or
    guessed evidence."""
    # TEST-010G
    entry = [e for e in valid_entries() if e["resource"]["resourceType"] != "ServiceRequest"]
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json(entry=entry)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert outcome.failure_type == FHIRIntegrationFailureType.MISSING_SERVICE_REQUEST
    assert outcome.evidence is None


def test_broken_condition_reference_fails_safely():
    """Verify a ServiceRequest.reasonReference pointing at a Condition
    that does not exist in the Bundle fails safely with
    BROKEN_CONDITION_REFERENCE, rather than silently skipping the
    missing diagnosis."""
    # TEST-010H
    entries = valid_entries()
    for e in entries:
        if e["resource"]["resourceType"] == "ServiceRequest":
            e["resource"]["reasonReference"] = [
                {"reference": "Condition/SYN-COND-DOES-NOT-EXIST"}
            ]

    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json(entry=entries)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert (
        outcome.failure_type == FHIRIntegrationFailureType.BROKEN_CONDITION_REFERENCE
    )
    assert outcome.evidence is None


def test_malformed_json_fails_safely():
    """Verify a response body that is not valid JSON fails safely with
    MALFORMED_JSON."""
    # TEST-010I
    client = FHIRStyleClient(
        http_client=make_client(raw_content=b"{not valid json"),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert outcome.failure_type == FHIRIntegrationFailureType.MALFORMED_JSON
    assert outcome.evidence is None


def test_invalid_fhir_style_schema_fails_safely():
    """Verify valid JSON that does not match the expected FHIR-style
    schema (e.g. a ServiceRequest missing a required field) fails
    safely with INVALID_SCHEMA."""
    # TEST-010J
    entry = [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "SYN-SR-001",
                # "status" and "intent" are required and missing here.
                "code": {"coding": []},
            }
        }
    ]
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json(entry=entry)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert outcome.failure_type == FHIRIntegrationFailureType.INVALID_SCHEMA
    assert outcome.evidence is None


# =====================================================================
# TRANSPORT / HTTP FAILURE TESTS
# =====================================================================
def test_http_500_fails_safely():
    """Verify an HTTP 500 response fails safely with HTTP_ERROR,
    instead of trying to parse an error body as a Bundle."""
    # TEST-010K
    client = FHIRStyleClient(
        http_client=make_client(json_body={"error": "synthetic failure"}, status_code=500),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert outcome.failure_type == FHIRIntegrationFailureType.HTTP_ERROR
    assert outcome.evidence is None


def test_http_timeout_fails_safely():
    """Verify a simulated network timeout/client error fails safely
    with HTTP_ERROR, rather than raising an unhandled exception."""
    # TEST-010L
    client = FHIRStyleClient(
        http_client=make_client(
            raise_error=httpx.ConnectTimeout("synthetic timeout")
        ),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is False
    assert outcome.failure_type == FHIRIntegrationFailureType.HTTP_ERROR
    assert outcome.evidence is None


# =====================================================================
# SAFETY BOUNDARY TESTS
# =====================================================================
def test_no_fabricated_evidence_is_returned_on_failure():
    """Verify every failure path returns evidence=None -- this client
    must never invent placeholder or partial evidence when the real
    data cannot be reliably retrieved."""
    # TEST-010M
    failing_clients = [
        FHIRStyleClient(
            http_client=make_client(status_code=500, json_body={}),
            base_url="https://synthetic-fhir-style.example.internal",
        ),
        FHIRStyleClient(
            http_client=make_client(raw_content=b"not json"),
            base_url="https://synthetic-fhir-style.example.internal",
        ),
    ]

    for client in failing_clients:
        outcome = client.get_case_evidence("SYN-CASE-001")
        assert outcome.success is False
        assert outcome.evidence is None


def test_synthetic_case_id_is_used_in_request_path():
    """Verify the case ID is placed into the request URL path, so the
    integration boundary actually asks for the specific case it was
    given."""
    # TEST-010N
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json=valid_bundle_json())

    client = FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    client.get_case_evidence("SYN-CASE-001")

    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/fhir-style/cases/SYN-CASE-001")


def test_no_real_network_call_is_required():
    """
    Verify the entire client can be exercised using only
    httpx.MockTransport -- no real network access, DNS resolution, or
    live healthcare/FHIR server is ever required to test this code.
    """
    # TEST-010O
    client = FHIRStyleClient(
        http_client=make_client(json_body=valid_bundle_json()),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    outcome = client.get_case_evidence("SYN-CASE-001")

    assert outcome.success is True


def test_response_object_is_not_mutated():
    """Verify parsing the response never mutates the raw response/JSON
    object the transport produced -- extraction is read-only."""
    # TEST-010P
    body = valid_bundle_json()
    original_entry_count = len(body["entry"])

    client = FHIRStyleClient(
        http_client=make_client(json_body=body),
        base_url="https://synthetic-fhir-style.example.internal",
    )

    client.get_case_evidence("SYN-CASE-001")

    assert len(body["entry"]) == original_entry_count


def test_no_ai_or_llm_code_is_called():
    """Verify the FHIR-style integration module imports nothing from
    src/ai/* -- extraction is purely deterministic and must never
    depend on an LLM or AI service."""
    # TEST-010Q
    from src.integrations import fhir_client

    module_source_imports = fhir_client.__file__

    with open(module_source_imports, encoding="utf-8") as f:
        source = f.read()

    assert "src.ai" not in source
    assert "openai" not in source.lower()


def test_no_approval_denial_field_exists_in_normalized_evidence():
    """Verify FHIRCaseEvidence contains only extracted facts -- no
    approval, denial, medical-necessity, or payer-decision field, since
    this integration boundary must never make or imply a clinical
    decision."""
    # TEST-010R
    from src.integrations.fhir_models import FHIRCaseEvidence

    assert set(FHIRCaseEvidence.model_fields.keys()) == {
        "service_request_id",
        "requested_service_code",
        "diagnosis_codes",
        "supporting_documentation",
        "source_resource_ids",
    }
