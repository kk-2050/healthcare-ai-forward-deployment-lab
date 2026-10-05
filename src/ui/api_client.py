# File Name: api_client.py
# Purpose: Implements the one small HTTP/JSON client Streamlit uses to talk to the existing FastAPI backend.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# This is the ONLY place Streamlit talks to the backend, and it only
# ever does so over plain HTTP/JSON (httpx) -- never a direct import of
# LangGraph, a workflow service, a repository, a SQLAlchemy session, a
# FHIR client, or the AI provider. Streamlit is an application client
# only; the real architecture boundary (Streamlit -> FastAPI ->
# everything else) is enforced structurally by this module never
# importing anything from src/workflow, src/db, src/integrations, or
# src/ai.
#
# WHY httpx, NOT requests:
# httpx is already a pinned, direct requirements.txt dependency used
# pervasively throughout this project (FHIRStyleClient, every offline
# test's MockTransport); requests is not a declared dependency here.
# Reusing httpx keeps this project on one HTTP library, not two.
#
# ERROR HANDLING PHILOSOPHY:
# Every failure this client can encounter -- a non-2xx HTTP response, a
# connection failure, or a timeout -- is translated into one
# APIClientError carrying only a safe, user-facing message that is
# determined LOCALLY from the HTTP status code alone.
#
# This client never reads, trusts, or displays the backend's own
# response body text (e.g. a JSON "detail" field) for its user-facing
# message, even though today's FastAPI endpoints happen to return
# reviewed, safe, fixed strings there. That is a property of today's
# specific backend implementation, not a guarantee this client may
# rely on -- a future backend change, a different deployment, or an
# unexpected failure mode could put something unsafe in that field,
# and this UI boundary must stay safe regardless. Nothing here ever
# re-raises or displays a raw httpx exception, response body, or
# traceback to the caller.

from __future__ import annotations

import httpx

_DEFAULT_TIMEOUT_SECONDS = 10.0

_FIXED_FALLBACK_MESSAGES: dict[int, str] = {
    422: "The case request is invalid. Review the entered fields and try again.",
    404: "The requested resource was not found.",
    409: "The request conflicts with an existing workflow or case.",
    500: "The backend could not complete the request.",
    503: (
        "The FHIR integration is unavailable. For the approved local "
        "synthetic demo, start FastAPI with FHIR_MODE=synthetic."
    ),
}

_GENERIC_FALLBACK_MESSAGE = "The backend returned an unexpected error."
_CONNECTION_FAILURE_MESSAGE = (
    "FastAPI is unavailable. Confirm that the backend server is running."
)
_TIMEOUT_MESSAGE = "The backend request timed out."


class APIClientError(Exception):
    """
    Raised for every failure this client can encounter -- a non-2xx
    HTTP response, a connection failure, or a timeout.

    message is always a fixed, safe, user-facing string -- never raw
    exception text, a traceback, or backend configuration detail.
    status_code is None for a connection failure or timeout (no HTTP
    response was ever received).
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def map_http_error_response(status_code: int) -> str:
    """
    Resolves the safe, user-facing message for one non-2xx HTTP status
    code -- determined entirely locally, from the status code alone.
    The response body (including any "detail" field) is never read
    for this purpose; see this module's docstring for why. Falls back
    to one generic message for any status code outside the documented
    set (422/404/409/500/503).
    """
    return _FIXED_FALLBACK_MESSAGES.get(status_code, _GENERIC_FALLBACK_MESSAGE)


# =====================================================================
# API CLIENT
# Purpose:
# One small, explicit HTTP/JSON client. Each public method sends one
# request and returns the parsed JSON body on success, or raises
# APIClientError with a safe message on any failure.
#
# Important Notes:
# - base_url/timeout are the only configuration this class accepts --
#   no authentication, no token, no header beyond ordinary JSON
#   content negotiation (see src/ui/api_client.py's module docstring
#   for why no auth exists in Phase 1).
# - Designed so Task 26C-2 can cleanly add get_workflow_snapshot(),
#   get_pending_human_review(), submit_human_review_decision(), and
#   resume_workflow() as additional thin methods following this exact
#   same pattern -- not implemented yet, since Task 26C-1 only needs
#   start_workflow().
# =====================================================================
class APIClient:
    def __init__(self, base_url: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def start_workflow(self, payload: dict) -> dict:
        """
        Calls POST /workflows with the given JSON-serializable payload
        and returns the parsed response body (shaped like
        StartWorkflowResponse) on success (HTTP 201).

        Raises APIClientError with a safe message for any non-2xx
        response, connection failure, or timeout -- never raises a raw
        httpx exception to the caller.
        """
        return self._post("/workflows", payload)

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TimeoutException as error:
            raise APIClientError(_TIMEOUT_MESSAGE) from error
        except httpx.RequestError as error:
            raise APIClientError(_CONNECTION_FAILURE_MESSAGE) from error

        if response.status_code // 100 != 2:
            # The response body (including any "detail" field) is
            # deliberately never read here -- the user-facing message
            # is determined locally from the status code alone (see
            # map_http_error_response()'s own docstring for why).
            raise APIClientError(
                map_http_error_response(response.status_code),
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as error:
            raise APIClientError(_GENERIC_FALLBACK_MESSAGE) from error

    def close(self) -> None:
        self._client.close()


__all__ = [
    "APIClient",
    "APIClientError",
    "map_http_error_response",
]
