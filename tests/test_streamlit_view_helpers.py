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

from src.models.human_review import HumanReviewOutcome
from src.workflow.human_review_service import _APPROVED_CLOSE_REASON_CODES
from src.ui.view_helpers import (
    ALLOWED_HUMAN_REVIEW_OUTCOMES,
    CLOSE_CASE_REASON_CODES,
    REVIEWER_ACTOR_TYPE_CODE,
    describe_workflow_status,
    extract_audit_event_rows,
    extract_human_review_summary,
    extract_workflow_summary,
    is_human_review_pending_eligible,
    is_resume_eligible,
    is_same_trace,
    normalize_to_workflow_response_shape,
    requires_close_reason_text,
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


# =====================================================================
# HUMAN REVIEW / RESUME CONTRACT CONSTANTS (Task 26C-2)
# =====================================================================
def test_allowed_human_review_outcomes_matches_real_backend_enum_exactly():
    """Verify the UI's allowed-outcomes list is exactly the real
    HumanReviewOutcome enum -- no more, no fewer, and critically no
    approve/deny value, since none exists in the real enum."""
    real_values = {outcome.value for outcome in HumanReviewOutcome}
    assert set(ALLOWED_HUMAN_REVIEW_OUTCOMES) == real_values


def test_no_approval_or_denial_outcome_exists():
    """Verify no approve/deny/clinical-decision value exists anywhere
    in the allowed outcomes list -- structurally, not just by
    convention."""
    forbidden = {"APPROVE", "DENY", "CLINICAL_APPROVAL", "CLINICAL_DENIAL", "APPROVED", "DENIED"}
    assert forbidden.isdisjoint(ALLOWED_HUMAN_REVIEW_OUTCOMES)


def test_close_case_reason_codes_matches_real_backend_validation_exactly():
    """Verify the UI's CLOSE_CASE reason list is exactly the set
    src/workflow/human_review_service.py itself validates against --
    never a reason the backend would reject, never an invented one."""
    assert set(CLOSE_CASE_REASON_CODES) == set(_APPROVED_CLOSE_REASON_CODES)


def test_reviewer_actor_type_code_matches_existing_test_convention():
    """Verify the fixed reviewer actor type code is the one real,
    already-loaded actor_types value this project's own existing
    Human Review tests already use."""
    assert REVIEWER_ACTOR_TYPE_CODE == "HUMAN_REVIEWER"


def test_requires_close_reason_text_only_for_case_close_other():
    assert requires_close_reason_text("CASE_CLOSE_OTHER") is True
    for code in CLOSE_CASE_REASON_CODES:
        if code != "CASE_CLOSE_OTHER":
            assert requires_close_reason_text(code) is False
    assert requires_close_reason_text(None) is False


# =====================================================================
# ELIGIBILITY / NORMALIZATION LOGIC (Task 26C-2)
# =====================================================================
def test_is_human_review_pending_eligible_true_only_for_exact_status():
    assert is_human_review_pending_eligible({"workflow_status_code": "HUMAN_REVIEW_REQUIRED"}) is True
    assert is_human_review_pending_eligible({"workflow_status_code": "PROCESSING"}) is False
    assert is_human_review_pending_eligible({}) is False


def test_is_resume_eligible_true_only_for_pending_resume():
    assert is_resume_eligible({"workflow_status_code": "PENDING_RESUME"}) is True
    assert is_resume_eligible({"workflow_status_code": "HUMAN_REVIEW_REQUIRED"}) is False
    assert is_resume_eligible({}) is False


def test_is_same_trace_requires_exact_nonempty_match():
    assert is_same_trace("trace_001", "trace_001") is True
    assert is_same_trace("trace_001", "trace_002") is False
    assert is_same_trace("", "") is False
    assert is_same_trace("trace_001", "") is False


def test_normalize_to_workflow_response_shape_from_top_level_fields():
    """Verify a StartWorkflowResponse/ResumeWorkflowResponse/
    WorkflowSnapshotResponse-shaped dict (already carrying top-level
    trace_id/case_id) normalizes to itself."""
    body = {
        "trace_id": "t1", "case_id": "c1",
        "workflow_run": {"workflow_status_code": "COMPLETED"},
        "audit_events": [{"event_type_code": "WORKFLOW_STARTED"}],
    }
    assert normalize_to_workflow_response_shape(body) == body


def test_normalize_to_workflow_response_shape_from_human_review_decision_response():
    """Verify a HumanReviewDecisionResponse-shaped dict (no top-level
    trace_id/case_id) normalizes using workflow_run's own trace_id/
    case_id instead."""
    body = {
        "review": {"review_id": "r1"},
        "workflow_run": {"trace_id": "t1", "case_id": "c1", "workflow_status_code": "PENDING_RESUME"},
        "audit_events": [],
    }

    normalized = normalize_to_workflow_response_shape(body)

    assert normalized["trace_id"] == "t1"
    assert normalized["case_id"] == "c1"
    assert normalized["workflow_run"]["workflow_status_code"] == "PENDING_RESUME"


def test_normalize_to_workflow_response_shape_handles_missing_data_safely():
    assert normalize_to_workflow_response_shape({}) == {
        "trace_id": "", "case_id": "", "workflow_run": {}, "audit_events": [],
    }


def test_extract_human_review_summary_returns_safe_fields_only():
    record = {
        "review_id": "r1", "trace_id": "t1", "case_id": "c1",
        "review_status_code": "REQUESTED", "review_outcome_code": None,
        "reason_code": "HUMAN_REVIEW_FHIR_FAILURE",
        "requested_at_utc": "2026-01-15T00:00:00Z", "completed_at_utc": None,
        "reviewer_reference": "SYN-REVIEWER-001",
        "review_note_text": "should never appear",
    }

    summary = extract_human_review_summary(record)

    assert summary == {
        "review_id": "r1", "trace_id": "t1", "case_id": "c1",
        "review_status_code": "REQUESTED", "review_outcome_code": None,
        "reason_code": "HUMAN_REVIEW_FHIR_FAILURE",
        "requested_at_utc": "2026-01-15T00:00:00Z", "completed_at_utc": None,
    }
    assert "reviewer_reference" not in summary
    assert "review_note_text" not in summary
