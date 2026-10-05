# File Name: synthetic_fhir_runtime.py
# Purpose: Builds a zero-network, synthetic-only FHIRStyleClient for Phase 1 local prototype/demo use (FHIR_MODE=synthetic).
# Creation Date: 2026-10-02
# Author: K.Kashiwagi
#
# Module Explanation:
# This is Phase 1 LOCAL PROTOTYPE/DEMO INFRASTRUCTURE ONLY -- it is NOT
# a production FHIR integration, and it is never used unless a
# developer explicitly sets FHIR_MODE=synthetic (see
# src/config/fhir_settings.py and src/api/dependencies.py's
# get_fhir_client()). It exists so the real intended path --
# Streamlit -> FastAPI -> get_fhir_client() -> LangGraph -- has a
# working local client to exercise, without ever constructing an
# unauthenticated live client (which this project has no approved
# contract for).
#
# WHY MockTransport:
# httpx.MockTransport is a stable, public httpx API for swapping the
# transport layer with an in-process, synchronous handler function --
# not a test-only trick. Using it here means FHIRStyleClient
# (src/integrations/fhir_client.py) needs no change at all: it already
# only ever talks to whatever httpx.Client it is constructed with.
# Because MockTransport never opens a socket, resolves DNS, or
# negotiates TLS, there is no outbound network capability here by
# construction -- not "disabled by configuration," but structurally
# absent. There is exactly one transport (MockTransport) and no
# fallback transport of any kind.
#
# WHAT THIS MODULE SUPPLIES, AND WHAT IT DOES NOT:
# build_synthetic_fhir_client() always returns the one deterministic,
# synthetic happy-path Bundle described below, for any case_id --
# evidence only. It never decides, approves, or denies anything; the
# workflow's own deterministic rules, AI step, and Human Review
# boundary make every actual decision, exactly as they already do for
# a real FHIR response. A demo case whose own submitted service/
# diagnosis codes do not match this fixed evidence will correctly be
# routed by the existing, unmodified evidence-consistency check to
# Human Review -- that is expected, not a defect of this module.

import httpx

from src.integrations.fhir_client import FHIRStyleClient

# A fixed, non-resolvable placeholder host -- never read from
# configuration, never a real or production-shaped domain. The same
# convention this project's own offline tests already use for their
# synthetic FHIR base URLs.
_SYNTHETIC_BASE_URL = "https://synthetic-fhir-style.example.internal"

# The one deterministic synthetic happy-path Bundle this runtime ever
# returns (Task 25C, Decision 1 -- no second scenario, no failure
# simulation here). Matches the canonical synthetic codes already used
# throughout this project's offline test fixtures, so a demo case
# submitted with these same codes completes the workflow's happy path.
_SYNTHETIC_BUNDLE = {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [
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
    ],
}


def _synthetic_handler(request: httpx.Request) -> httpx.Response:
    """Returns the one fixed synthetic Bundle for every request,
    regardless of case_id -- deterministic, no state, no branching."""
    return httpx.Response(httpx.codes.OK, json=_SYNTHETIC_BUNDLE)


def build_synthetic_fhir_client() -> FHIRStyleClient:
    """
    Builds a FHIRStyleClient whose only transport is an in-process
    httpx.MockTransport -- zero outbound network capability, synthetic
    data only. See this module's docstring for why this is safe and
    appropriate for Phase 1 prototype/demo use only.

    FHIRStyleClient itself is reused completely unchanged: this
    function only controls how it is constructed, never what it does.
    """
    http_client = httpx.Client(transport=httpx.MockTransport(_synthetic_handler))
    return FHIRStyleClient(http_client=http_client, base_url=_SYNTHETIC_BASE_URL)


__all__ = ["build_synthetic_fhir_client"]
