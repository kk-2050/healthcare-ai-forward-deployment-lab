# File Name: demo_data.py
# Purpose: Builds the one canonical synthetic demo case payload the Streamlit UI pre-populates for POST /workflows.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# Returns plain, JSON-serializable dict data shaped exactly like
# src/models/workflow_api.py's StartWorkflowRequest (client_id, case,
# completeness_requirements, ai_processing_requirements) -- no field
# here was invented; every key matches that model (and the
# PriorAuthorizationCase/CompletenessRequirements/
# AIProcessingRequirements models it composes) exactly. This module
# never imports those Pydantic models directly: Streamlit sends plain
# JSON over HTTP to FastAPI, which is the only place that validates it
# (see src/ui/api_client.py) -- never a second, UI-side copy of the
# backend's own validation.
#
# WHY THESE EXACT VALUES:
# client_id="cli_demo_001" is the one canonical synthetic demo client
# scripts/setup_demo_client.py creates (Task 26B) -- an operator must
# run that script against their local database before this payload can
# succeed against a real backend. requested_service_code=
# "SYN-LUMBAR-MRI" and diagnosis_code="SYN-LOW-BACK-PAIN" match the one
# fixed evidence Bundle src/integrations/synthetic_fhir_runtime.py
# returns under FHIR_MODE=synthetic (Task 25C) -- using these same
# values is what lets this demo case reach an ordinary COMPLETED
# disposition instead of an evidence-mismatch Human Review route.
#
# Every other identifier below is a fixed, clearly synthetic
# placeholder -- no real person, provider, or organization is named,
# and no real date belonging to an actual person is used.
#
# Only one deterministic default scenario is built here (Task 26C-1)
# -- no hidden alternate-scenario switch exists in this module.

from copy import deepcopy

CANONICAL_CLIENT_ID = "cli_demo_001"
CANONICAL_CASE_ID = "case_demo_001"
CANONICAL_MEMBER_ID = "SYN-MEMBER-DEMO-001"
CANONICAL_PROVIDER_ID = "SYN-PROVIDER-DEMO-001"
CANONICAL_SERVICE_CODE = "SYN-LUMBAR-MRI"
CANONICAL_DIAGNOSIS_CODE = "SYN-LOW-BACK-PAIN"
CANONICAL_REQUESTED_DATE = "2026-01-15"

_CANONICAL_PAYLOAD = {
    "client_id": CANONICAL_CLIENT_ID,
    "case": {
        "case_id": CANONICAL_CASE_ID,
        "member_id": CANONICAL_MEMBER_ID,
        "provider_id": CANONICAL_PROVIDER_ID,
        "requested_service_code": CANONICAL_SERVICE_CODE,
        "diagnosis_code": CANONICAL_DIAGNOSIS_CODE,
        "requested_date": CANONICAL_REQUESTED_DATE,
        "supporting_documentation": [],
        "clinical_notes": None,
    },
    "completeness_requirements": {
        "required_documentation": [],
        "clinical_notes_required": False,
    },
    "ai_processing_requirements": {
        "tasks": [],
    },
}


def build_canonical_demo_payload() -> dict:
    """
    Returns the one canonical synthetic demo payload for
    POST /workflows, shaped exactly like StartWorkflowRequest.

    Returns a fresh deep copy every call, so a caller editing the
    result (e.g. the Streamlit form) can never accidentally mutate
    this module's own canonical constant.
    """
    return deepcopy(_CANONICAL_PAYLOAD)


__all__ = [
    "CANONICAL_CLIENT_ID",
    "CANONICAL_CASE_ID",
    "CANONICAL_MEMBER_ID",
    "CANONICAL_PROVIDER_ID",
    "CANONICAL_SERVICE_CODE",
    "CANONICAL_DIAGNOSIS_CODE",
    "CANONICAL_REQUESTED_DATE",
    "build_canonical_demo_payload",
]
