# File Name: fhir_client.py
# Purpose: Implements a synthetic FHIR-style HTTP client that validates and deterministically extracts case evidence.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

import httpx
from pydantic import ValidationError

from src.integrations.fhir_models import (
    ConditionResource,
    DocumentReferenceResource,
    FHIRBundle,
    FHIRCaseEvidence,
    FHIRIntegrationFailureType,
    FHIRIntegrationOutcome,
    ServiceRequestResource,
)


def _extract_id_from_reference(reference: str) -> str:
    """
    Extracts the resource ID from a FHIR-style reference string.

    A reference such as "Condition/SYN-COND-001" is expected; this
    returns the part after the last "/". No inference or guessing is
    performed — a malformed reference simply produces an ID that will
    not match any resource in the Bundle, which is correctly treated
    as a broken reference by _extract_case_evidence().
    """
    return reference.rsplit("/", 1)[-1]


def _classify_schema_failure(error: ValidationError) -> FHIRIntegrationFailureType:
    """
    Distinguishes "unsupported resource type" from other schema
    problems, using Pydantic's discriminated-union error type
    ("union_tag_invalid") as the signal. Any other validation error
    (a missing field, wrong type, and so on) is reported as a generic
    invalid-schema failure.
    """
    for detail in error.errors():
        if detail["type"] == "union_tag_invalid":
            return FHIRIntegrationFailureType.UNSUPPORTED_RESOURCE_TYPE

    return FHIRIntegrationFailureType.INVALID_SCHEMA


# =====================================================================
# FHIR-STYLE EVIDENCE EXTRACTION
# Purpose:
# Converts a validated FHIRBundle into the small set of facts required
# by the prior-authorization workflow.
#
# Why:
# Healthcare integration data should be normalized deterministically
# before business rules or AI processing use it, and the exact
# resource/reference structure should not leak past this boundary.
#
# Important Notes:
# - This is not a full HL7 FHIR implementation.
# - No AI is used here; every extraction step is a plain, deterministic
#   lookup.
# - Missing references must fail safely; this function never invents
#   evidence. If the ServiceRequest is absent, a referenced Condition
#   cannot be found, or a resource has no coded value, extraction
#   stops and reports a specific failure instead of guessing.
# =====================================================================
def _extract_case_evidence(bundle: FHIRBundle) -> FHIRIntegrationOutcome:
    """Deterministically extracts FHIRCaseEvidence from a validated Bundle."""
    service_requests = [
        entry.resource
        for entry in bundle.entry
        if isinstance(entry.resource, ServiceRequestResource)
    ]
    conditions_by_id = {
        entry.resource.id: entry.resource
        for entry in bundle.entry
        if isinstance(entry.resource, ConditionResource)
    }
    documents = [
        entry.resource
        for entry in bundle.entry
        if isinstance(entry.resource, DocumentReferenceResource)
    ]

    if not service_requests:
        return FHIRIntegrationOutcome(
            success=False,
            failure_type=FHIRIntegrationFailureType.MISSING_SERVICE_REQUEST,
            error_message="No ServiceRequest resource was found in the Bundle.",
        )

    # Only the first ServiceRequest is used. This project models one
    # prior authorization case per Bundle; a Bundle with more than one
    # ServiceRequest is outside this small prototype's scope.
    service_request = service_requests[0]

    if not service_request.code.coding:
        return FHIRIntegrationOutcome(
            success=False,
            failure_type=FHIRIntegrationFailureType.INVALID_SCHEMA,
            error_message="The ServiceRequest resource has no coded service.",
        )

    requested_service_code = service_request.code.coding[0].code

    source_resource_ids: list[str] = [service_request.id]
    diagnosis_codes: list[str] = []

    for reference in service_request.reasonReference:
        condition_id = _extract_id_from_reference(reference.reference)
        condition = conditions_by_id.get(condition_id)

        if condition is None:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=FHIRIntegrationFailureType.BROKEN_CONDITION_REFERENCE,
                error_message=(
                    "A ServiceRequest reasonReference does not resolve to a "
                    "Condition resource in the Bundle."
                ),
            )

        if not condition.code.coding:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=FHIRIntegrationFailureType.INVALID_SCHEMA,
                error_message="A referenced Condition resource has no coded diagnosis.",
            )

        diagnosis_codes.append(condition.code.coding[0].code)
        source_resource_ids.append(condition.id)

    supporting_documentation: list[str] = []
    for document in documents:
        for content in document.content:
            supporting_documentation.append(content.title)
        source_resource_ids.append(document.id)

    evidence = FHIRCaseEvidence(
        service_request_id=service_request.id,
        requested_service_code=requested_service_code,
        diagnosis_codes=diagnosis_codes,
        supporting_documentation=supporting_documentation,
        source_resource_ids=source_resource_ids,
    )

    return FHIRIntegrationOutcome(success=True, evidence=evidence)


# =====================================================================
# FHIR-STYLE CLIENT
# Purpose:
# Requests a synthetic FHIR-style Bundle for one case and turns it into
# validated FHIRCaseEvidence, or a clear failure outcome.
#
# Why:
# Keeping HTTP concerns, schema validation, and fact extraction behind
# one small class means the future LangGraph integration only ever
# needs to call one method and handle one outcome shape — the same
# pattern already used for AI analysis (src/ai/service.py).
#
# Important Notes:
# - The HTTP client is always injected (constructor dependency
#   injection); this class never creates a global HTTP client and
#   never reads environment variables.
# - No real healthcare endpoint is embedded here. base_url is always
#   supplied by the caller, and this class does not claim to implement
#   an official FHIR REST endpoint — GET /fhir-style/cases/{case_id}
#   is a prototype integration endpoint returning FHIR-style resources.
# - On any failure, this class never fabricates evidence: the returned
#   FHIRIntegrationOutcome always has evidence=None on failure.
# =====================================================================
class FHIRStyleClient:
    """
    Retrieves and validates a synthetic FHIR-style Bundle for one case.

    Constructed with an already-configured httpx client and a base
    URL; makes no assumptions about where that URL points, and in
    tests it is always backed by an offline transport (see
    tests/test_fhir_client.py) — never a real network call.
    """

    def __init__(self, *, http_client: httpx.Client, base_url: str):
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")

    def get_case_evidence(self, case_id: str) -> FHIRIntegrationOutcome:
        """
        Fetches and extracts FHIRCaseEvidence for one synthetic case ID.

        Always returns a FHIRIntegrationOutcome — never raises for an
        HTTP error, malformed JSON, or invalid schema. Those are all
        reported as a specific failure_type instead.
        """
        url = f"{self._base_url}/fhir-style/cases/{case_id}"

        try:
            response = self._http_client.get(url)
        except httpx.HTTPError:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=FHIRIntegrationFailureType.HTTP_ERROR,
                error_message="The healthcare integration request failed.",
            )

        if response.status_code != httpx.codes.OK:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=FHIRIntegrationFailureType.HTTP_ERROR,
                error_message="The healthcare integration returned an unexpected status.",
            )

        try:
            raw_bundle = response.json()
        except ValueError:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=FHIRIntegrationFailureType.MALFORMED_JSON,
                error_message="The healthcare integration response was not valid JSON.",
            )

        try:
            bundle = FHIRBundle.model_validate(raw_bundle)
        except ValidationError as error:
            return FHIRIntegrationOutcome(
                success=False,
                failure_type=_classify_schema_failure(error),
                error_message="The healthcare integration response failed schema validation.",
            )

        return _extract_case_evidence(bundle)
