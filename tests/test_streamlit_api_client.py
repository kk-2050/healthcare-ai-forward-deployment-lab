# File Name: test_streamlit_api_client.py
# Purpose: Tests src/ui/api_client.py's HTTP/JSON client and error mapping, using httpx.MockTransport -- never a real network call.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the one place Streamlit talks to FastAPI: every
# request/response path is exercised against an in-process
# httpx.MockTransport handler, never a real server -- no real network
# traffic leaves the test process, and no real FastAPI/SQL Server/
# FHIR/AI is ever touched.

import httpx
import pytest

from src.ui.api_client import APIClient, APIClientError, map_http_error_response


def make_client(handler) -> APIClient:
    """Builds an APIClient whose underlying httpx.Client is backed
    entirely by an in-process MockTransport handler -- the same
    zero-network-capability pattern already used throughout this
    project's offline FHIR tests."""
    client = APIClient(base_url="http://testserver")
    client._client = httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(handler)
    )
    return client


def test_successful_start_workflow_returns_parsed_body():
    """Verify a 201 response's JSON body is returned unchanged."""
    expected_body = {
        "trace_id": "trace_001",
        "case_id": "case_001",
        "workflow_run": {"workflow_status_code": "COMPLETED"},
        "audit_events": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=expected_body)

    client = make_client(handler)

    result = client.start_workflow({"client_id": "cli_demo_001"})

    assert result == expected_body


def test_request_body_sent_correctly():
    """Verify the exact payload passed in is sent as the JSON request
    body, unmodified, to the correct path."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent["path"] = request.url.path
        sent["json"] = json.loads(request.content)
        return httpx.Response(201, json={"trace_id": "t", "case_id": "c", "workflow_run": {}, "audit_events": []})

    client = make_client(handler)
    payload = {"client_id": "cli_demo_001", "case": {"case_id": "case_demo_001"}}

    client.start_workflow(payload)

    assert sent["path"] == "/workflows"
    assert sent["json"] == payload


_UNSAFE_SENTINEL = "UNSAFE_BACKEND_DETAIL_SHOULD_NOT_SURFACE"


@pytest.mark.parametrize(
    "status_code,fixed_message",
    [
        (422, "The case request is invalid. Review the entered fields and try again."),
        (404, "The requested resource was not found."),
        (409, "The request conflicts with an existing workflow or case."),
        (500, "The backend could not complete the request."),
        (
            503,
            "The FHIR integration is unavailable. For the approved local "
            "synthetic demo, start FastAPI with FHIR_MODE=synthetic.",
        ),
    ],
)
def test_fixed_message_used_regardless_of_backend_detail(status_code, fixed_message):
    """Verify each documented status code maps to its fixed, locally-
    controlled message EVEN WHEN the backend's response body contains
    arbitrary "detail" text -- the Streamlit UI boundary must stay
    safe regardless of what a backend happens to return, not merely
    because today's FastAPI endpoints are already reviewed-safe."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": _UNSAFE_SENTINEL})

    client = make_client(handler)

    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})

    assert excinfo.value.message == fixed_message
    assert excinfo.value.status_code == status_code
    assert _UNSAFE_SENTINEL not in excinfo.value.message
    assert _UNSAFE_SENTINEL not in str(excinfo.value)


def test_unmapped_status_code_uses_generic_fallback_regardless_of_detail():
    """Verify a status code outside the documented set still fails
    safely with the generic fallback message, never an unmapped crash
    and never the backend's own arbitrary detail text."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, json={"detail": _UNSAFE_SENTINEL})

    client = make_client(handler)

    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})

    assert excinfo.value.message == "The backend returned an unexpected error."
    assert _UNSAFE_SENTINEL not in excinfo.value.message


def test_raw_backend_detail_never_reaches_error_message():
    """Verify APIClientError.message never contains the backend
    response body's own "detail" text, across every documented status
    code plus one unmapped code -- the central Task 26C-1B safety
    property."""
    sentinels = {
        422: "INTERNAL_VALIDATION_DETAIL_SHOULD_NOT_SURFACE",
        404: "INTERNAL_LOOKUP_DETAIL_SHOULD_NOT_SURFACE",
        409: "INTERNAL_CONFLICT_DETAIL_SHOULD_NOT_SURFACE",
        500: "INTERNAL_SQL_DRIVER_DETAIL_SHOULD_NOT_SURFACE",
        503: "INTERNAL_TRACE_DETAIL_SHOULD_NOT_SURFACE",
        999: "INTERNAL_UNKNOWN_DETAIL_SHOULD_NOT_SURFACE",
    }

    for status_code, sentinel in sentinels.items():
        def handler(request: httpx.Request, _status=status_code, _sentinel=sentinel) -> httpx.Response:
            return httpx.Response(_status, json={"detail": _sentinel})

        client = make_client(handler)
        with pytest.raises(APIClientError) as excinfo:
            client.start_workflow({})

        assert sentinel not in excinfo.value.message
        assert sentinel not in str(excinfo.value)


def test_response_body_is_never_read_for_error_mapping(monkeypatch):
    """Verify the client does not even attempt to parse the error
    response body -- response.json() is never called on a non-2xx
    response, not merely "called but ignored"."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": _UNSAFE_SENTINEL})

    client = make_client(handler)

    def _fail_if_called(self):
        raise AssertionError("response.json() should never be called for a non-2xx response")

    monkeypatch.setattr(httpx.Response, "json", _fail_if_called)

    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})

    assert excinfo.value.message == "The requested resource was not found."


def test_connection_failure_mapped_safely():
    """Verify a connection-level failure (never an HTTP response at
    all) is mapped to the fixed, safe connection message."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic simulated connection failure")

    client = make_client(handler)

    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})

    assert excinfo.value.message == (
        "FastAPI is unavailable. Confirm that the backend server is running."
    )
    assert excinfo.value.status_code is None
    assert "synthetic simulated connection failure" not in str(excinfo.value)


def test_timeout_mapped_safely():
    """Verify a timeout is mapped to the fixed, safe timeout message,
    distinctly from a plain connection failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic simulated timeout")

    client = make_client(handler)

    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})

    assert excinfo.value.message == "The backend request timed out."


def test_raw_exception_text_never_exposed_in_any_mapped_message():
    """Verify no mapped message anywhere ever contains raw httpx
    exception text -- every message is one of the fixed, hand-written
    strings."""
    def connect_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("super secret internal detail")

    client = make_client(connect_handler)
    with pytest.raises(APIClientError) as excinfo:
        client.start_workflow({})
    assert "super secret internal detail" not in excinfo.value.message


def test_map_http_error_response_is_pure_function_of_status_code():
    """Verify the pure mapping function depends only on the status
    code -- it takes no response-body argument at all, structurally
    guaranteeing backend detail can never influence it."""
    assert map_http_error_response(404) == "The requested resource was not found."
    assert map_http_error_response(999) == "The backend returned an unexpected error."
