# File Name: view_helpers.py
# Purpose: Pure, Streamlit-independent helpers that extract only safe, display-ready fields from a FastAPI response body.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# These functions take plain dict data already returned by
# src/ui/api_client.py (itself already a parsed StartWorkflowResponse
# JSON body) and return only an explicit allow-listed subset of
# fields -- never the whole response passed through unfiltered. This
# is a defense-in-depth filter: today's response models
# (src/models/workflow_api.py, src/models/audit.py) already have no
# final_state/raw-FHIR/raw-LLM/secret field to begin with, but this
# module makes "what Streamlit is allowed to show" an explicit,
# testable allowlist rather than an implicit assumption about what the
# backend currently happens to return.
#
# No Streamlit import here on purpose -- every function is a plain,
# independently testable function of its input, with no UI framework
# dependency.

_SAFE_WORKFLOW_RUN_FIELDS = (
    "workflow_status_code",
    "next_action_code",
    "human_review_required",
    "failure_category_code",
    "started_at_utc",
    "completed_at_utc",
)

_SAFE_AUDIT_EVENT_FIELDS = (
    "event_type_code",
    "event_category_code",
    "result_code",
    "failure_category_code",
    "reason_code",
    "occurred_at_utc",
)


def _filter_to_safe_fields(data: dict, allowed_fields: tuple[str, ...]) -> dict:
    """Returns a new dict containing only the keys in allowed_fields
    that are actually present in data -- never a key outside the
    allowlist, even if the input happens to contain one."""
    return {key: data[key] for key in allowed_fields if key in data}


def extract_workflow_summary(response_body: dict) -> dict:
    """
    Returns the safe, top-level case/trace identity plus an
    allow-listed subset of the workflow_run snapshot, from a
    StartWorkflowResponse-shaped dict.

    Returns an empty dict's worth of identity fields (case_id="",
    trace_id="") if the expected keys are absent, rather than raising
    -- callers decide how to render a missing/malformed response.
    """
    workflow_run = response_body.get("workflow_run") or {}
    summary = {
        "case_id": response_body.get("case_id", ""),
        "trace_id": response_body.get("trace_id", ""),
    }
    summary.update(_filter_to_safe_fields(workflow_run, _SAFE_WORKFLOW_RUN_FIELDS))
    return summary


def extract_audit_event_rows(response_body: dict) -> list[dict]:
    """
    Returns the audit_events list from a StartWorkflowResponse-shaped
    dict, with each event reduced to only its safe, allow-listed
    fields -- in the same order the backend already returned them
    (already deterministically ordered by the repository).
    """
    events = response_body.get("audit_events") or []
    return [_filter_to_safe_fields(event, _SAFE_AUDIT_EVENT_FIELDS) for event in events]


def describe_workflow_status(workflow_status_code: str | None) -> str:
    """
    Returns a short, professional, plain-English description of a
    workflow_status_code -- for display only, never a substitute for
    the code itself (which is always shown alongside this text).

    Deliberately conservative: an unrecognized or missing code returns
    a generic "Status: <code>" line rather than guessing at a meaning
    this project has not reviewed.
    """
    descriptions = {
        "PROCESSING": "The workflow is actively processing.",
        "COMPLETED": "The workflow has finished automated processing.",
        "HUMAN_REVIEW_REQUIRED": "Automated processing is paused for a human reviewer.",
        "PENDING_RESUME": "A reviewer decision was recorded; the workflow has not yet resumed.",
        "FAILED": "The workflow failed unsafely and did not complete.",
    }
    if not workflow_status_code:
        return "Status is not yet known."
    return descriptions.get(workflow_status_code, f"Status: {workflow_status_code}")


__all__ = [
    "extract_workflow_summary",
    "extract_audit_event_rows",
    "describe_workflow_status",
]
