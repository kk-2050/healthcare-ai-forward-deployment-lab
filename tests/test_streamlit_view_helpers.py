# File Name: test_streamlit_view_helpers.py
# Purpose: Tests src/ui/view_helpers.py's safe field-extraction/formatting helpers.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the one explicit allowlist deciding what
# Streamlit is permitted to render from a FastAPI response body --
# proving no field outside that allowlist is ever surfaced, even if
# the input dict happens to contain one (e.g. a hypothetical future
# backend change that adds a new field).

from src.ui.view_helpers import (
    describe_workflow_status,
    extract_audit_event_rows,
    extract_workflow_summary,
)


def make_response_body(**overrides) -> dict:
    data = {
        "trace_id": "trace_001",
        "case_id": "case_001",
        "workflow_run": {
            "workflow_status_code": "COMPLETED",
            "next_action_code": "COMPLETE_WORKFLOW",
            "human_review_required": False,
            "failure_category_code": None,
            "started_at_utc": "2026-01-15T00:00:00Z",
            "completed_at_utc": "2026-01-15T00:00:05Z",
        },
        "audit_events": [
            {
                "event_type_code": "WORKFLOW_STARTED",
                "event_category_code": "WORKFLOW",
                "result_code": "SUCCESS",
                "failure_category_code": None,
                "reason_code": None,
                "occurred_at_utc": "2026-01-15T00:00:00Z",
            },
        ],
    }
    data.update(overrides)
    return data


def test_extract_workflow_summary_returns_expected_fields():
    """Verify the summary contains exactly the identity fields plus
    the allow-listed workflow_run fields."""
    summary = extract_workflow_summary(make_response_body())

    assert summary == {
        "case_id": "case_001",
        "trace_id": "trace_001",
        "workflow_status_code": "COMPLETED",
        "next_action_code": "COMPLETE_WORKFLOW",
        "human_review_required": False,
        "failure_category_code": None,
        "started_at_utc": "2026-01-15T00:00:00Z",
        "completed_at_utc": "2026-01-15T00:00:05Z",
    }


def test_extract_workflow_summary_handles_missing_keys_safely():
    """Verify a malformed/empty response body produces empty identity
    fields rather than raising."""
    summary = extract_workflow_summary({})

    assert summary["case_id"] == ""
    assert summary["trace_id"] == ""
    assert "workflow_status_code" not in summary


def test_extract_workflow_summary_never_leaks_unlisted_fields():
    """Verify a field outside the allowlist (simulating final_state or
    a raw FHIR/LLM key) is never included, even if present in the
    input."""
    body = make_response_body()
    body["workflow_run"]["final_state"] = {"evidence": "should never appear"}
    body["workflow_run"]["raw_fhir_bundle"] = {"resourceType": "Bundle"}

    summary = extract_workflow_summary(body)

    assert "final_state" not in summary
    assert "raw_fhir_bundle" not in summary


def test_extract_audit_event_rows_returns_safe_fields_only():
    """Verify each audit event row contains only the allow-listed
    fields, in the same order as the input list."""
    rows = extract_audit_event_rows(make_response_body())

    assert rows == [
        {
            "event_type_code": "WORKFLOW_STARTED",
            "event_category_code": "WORKFLOW",
            "result_code": "SUCCESS",
            "failure_category_code": None,
            "reason_code": None,
            "occurred_at_utc": "2026-01-15T00:00:00Z",
        }
    ]


def test_extract_audit_event_rows_never_leaks_unlisted_fields():
    """Verify a raw FHIR/LLM-shaped key on an individual event is never
    surfaced."""
    body = make_response_body()
    body["audit_events"][0]["raw_llm_response"] = "should never appear"

    rows = extract_audit_event_rows(body)

    assert "raw_llm_response" not in rows[0]


def test_extract_audit_event_rows_handles_missing_list_safely():
    """Verify a response body with no audit_events key returns an
    empty list rather than raising."""
    assert extract_audit_event_rows({}) == []


def test_describe_workflow_status_known_codes():
    """Verify known workflow_status_code values get their reviewed
    plain-English description."""
    assert "paused" in describe_workflow_status("HUMAN_REVIEW_REQUIRED").lower()
    assert "finished" in describe_workflow_status("COMPLETED").lower()


def test_describe_workflow_status_unknown_code_is_conservative():
    """Verify an unrecognized code is never given an invented
    description -- it falls back to a generic, literal statement."""
    assert describe_workflow_status("SOME_FUTURE_CODE") == "Status: SOME_FUTURE_CODE"


def test_describe_workflow_status_missing_code():
    """Verify a missing/None status code gets a safe generic
    message."""
    assert describe_workflow_status(None) == "Status is not yet known."
