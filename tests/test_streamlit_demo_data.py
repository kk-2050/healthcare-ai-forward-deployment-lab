# File Name: test_streamlit_demo_data.py
# Purpose: Tests src/ui/demo_data.py's canonical synthetic demo payload builder.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the one canonical demo payload the Streamlit UI
# pre-populates: it must match the Task 25C synthetic FHIR evidence
# codes, use the Task 26B canonical demo client_id, contain only
# synthetic identifiers, and validate against the real
# StartWorkflowRequest model -- never a shape this project's own
# backend would actually reject.

from src.models.workflow_api import StartWorkflowRequest
from src.ui.demo_data import (
    CANONICAL_CLIENT_ID,
    CANONICAL_DIAGNOSIS_CODE,
    CANONICAL_SERVICE_CODE,
    build_canonical_demo_payload,
)


def test_canonical_client_id_matches_task_26b_demo_client():
    """Verify the payload uses the exact client_id
    scripts/setup_demo_client.py (Task 26B) creates."""
    payload = build_canonical_demo_payload()
    assert payload["client_id"] == "cli_demo_001"
    assert CANONICAL_CLIENT_ID == "cli_demo_001"


def test_canonical_service_and_diagnosis_codes_match_synthetic_fhir_evidence():
    """Verify the payload's requested_service_code/diagnosis_code match
    the one fixed Bundle src/integrations/synthetic_fhir_runtime.py
    (Task 25C) returns -- required for the demo to reach an ordinary
    COMPLETED disposition instead of an evidence mismatch."""
    payload = build_canonical_demo_payload()
    assert payload["case"]["requested_service_code"] == "SYN-LUMBAR-MRI"
    assert payload["case"]["diagnosis_code"] == "SYN-LOW-BACK-PAIN"
    assert CANONICAL_SERVICE_CODE == "SYN-LUMBAR-MRI"
    assert CANONICAL_DIAGNOSIS_CODE == "SYN-LOW-BACK-PAIN"


def test_payload_validates_against_real_start_workflow_request():
    """Verify the payload is accepted, unmodified, by the real
    StartWorkflowRequest model -- proving no field was invented and no
    required field is missing."""
    payload = build_canonical_demo_payload()
    request = StartWorkflowRequest(**payload)
    assert request.client_id == "cli_demo_001"


def test_payload_is_deterministic_across_calls():
    """Verify two calls return equal (but independent) payloads -- no
    randomness, no hidden per-call variation."""
    first = build_canonical_demo_payload()
    second = build_canonical_demo_payload()
    assert first == second


def test_payload_calls_return_independent_copies():
    """Verify mutating one call's result never affects a later call --
    each call must return its own independent copy."""
    first = build_canonical_demo_payload()
    first["case"]["case_id"] = "mutated"

    second = build_canonical_demo_payload()

    assert second["case"]["case_id"] == "case_demo_001"


def test_every_identifier_is_clearly_synthetic():
    """Verify every identifier field uses a clearly synthetic prefix --
    no real person/provider/organization name."""
    payload = build_canonical_demo_payload()
    case = payload["case"]
    assert case["member_id"].startswith("SYN-")
    assert case["provider_id"].startswith("SYN-")
    assert payload["client_id"].startswith("cli_demo")


def test_no_hidden_alternate_scenario_fields():
    """Verify the payload contains only the exact keys
    StartWorkflowRequest/PriorAuthorizationCase/CompletenessRequirements/
    AIProcessingRequirements define -- no invented scenario-switch key."""
    payload = build_canonical_demo_payload()
    assert set(payload.keys()) == {
        "client_id", "case", "completeness_requirements", "ai_processing_requirements",
    }
    assert set(payload["case"].keys()) == {
        "case_id", "member_id", "provider_id", "requested_service_code",
        "diagnosis_code", "requested_date", "supporting_documentation", "clinical_notes",
    }
