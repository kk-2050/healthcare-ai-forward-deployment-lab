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

_SAFE_HUMAN_REVIEW_FIELDS = (
    "review_id",
    "trace_id",
    "case_id",
    "review_status_code",
    "review_outcome_code",
    "reason_code",
    "requested_at_utc",
    "completed_at_utc",
)

# The four real HumanReviewOutcome values (src/models/human_review.py),
# copied verbatim -- never a fifth "approve"/"deny" value. No such
# value exists in the real backend enum, so none can appear here
# either; this tuple is this project's own confirmation of that fact,
# not an independent decision.
ALLOWED_HUMAN_REVIEW_OUTCOMES = (
    "CONTINUE_WORKFLOW",
    "REQUEST_MORE_INFORMATION",
    "ESCALATE",
    "CLOSE_CASE",
)

# The six real CASE_CLOSE_* reason codes already approved and loaded
# (docs/database/reference_data.md; enforced by
# src/workflow/human_review_service.py) -- copied verbatim, never
# invented. CASE_CLOSE_OTHER additionally requires close_reason_text
# (enforced by the backend; the UI mirrors that requirement below).
CLOSE_CASE_REASON_CODES = (
    "CASE_CLOSE_COMPLETED",
    "CASE_CLOSE_REQUEST_WITHDRAWN",
    "CASE_CLOSE_DUPLICATE",
    "CASE_CLOSE_SUPERSEDED",
    "CASE_CLOSE_ADMINISTRATIVE",
    "CASE_CLOSE_OTHER",
)

# The one real, already-loaded actor_types row this project's own
# existing Human Review tests already use for a reviewer
# (docs/database/reference_data.md §12). Fixed, not user-editable --
# Streamlit never invents a new actor type the backend might reject.
REVIEWER_ACTOR_TYPE_CODE = "HUMAN_REVIEWER"


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


def extract_human_review_summary(record: dict) -> dict:
    """
    Returns an allow-listed subset of a HumanReviewRecord-shaped dict
    (the direct response of GET /human-review/pending/{trace_id} or
    the `review` field of a Human Review decision response) -- never
    reviewer_reference/review_note_text or any other field outside the
    allowlist, even though HumanReviewRecord itself already has no
    unsafe field.
    """
    return _filter_to_safe_fields(record, _SAFE_HUMAN_REVIEW_FIELDS)


def normalize_to_workflow_response_shape(response_body: dict) -> dict:
    """
    Returns {trace_id, case_id, workflow_run, audit_events} built
    reliably from ANY of this project's four workflow-bearing response
    shapes (StartWorkflowResponse, ResumeWorkflowResponse,
    WorkflowSnapshotResponse -- all already exactly this shape -- or
    HumanReviewDecisionResponse, which carries workflow_run/
    audit_events but not top-level trace_id/case_id). Falls back to
    workflow_run's own trace_id/case_id when the top level does not
    have them, so every caller can use extract_workflow_summary()/
    extract_audit_event_rows() uniformly regardless of which endpoint
    produced the response.
    """
    workflow_run = response_body.get("workflow_run") or {}
    return {
        "trace_id": response_body.get("trace_id") or workflow_run.get("trace_id", ""),
        "case_id": response_body.get("case_id") or workflow_run.get("case_id", ""),
        "workflow_run": workflow_run,
        "audit_events": response_body.get("audit_events") or [],
    }


def is_human_review_pending_eligible(workflow_summary: dict) -> bool:
    """
    True only when the current workflow_status_code is genuinely
    HUMAN_REVIEW_REQUIRED -- the one signal the backend itself uses to
    mean "automated processing is paused for a reviewer" (see
    docs/database/reference_data.md §3). Never inferred from any other
    field.
    """
    return workflow_summary.get("workflow_status_code") == "HUMAN_REVIEW_REQUIRED"


def is_resume_eligible(workflow_summary: dict) -> bool:
    """
    True only when the current workflow_status_code is PENDING_RESUME
    -- the one state resume_workflow() itself requires (set only by a
    CONTINUE_WORKFLOW Human Review decision). Never inferred from any
    other field, and never assumed merely because a decision was just
    submitted -- the caller must use the value the backend actually
    returned.
    """
    return workflow_summary.get("workflow_status_code") == "PENDING_RESUME"


def is_same_trace(expected_trace_id: str, returned_trace_id: str) -> bool:
    """
    True only when a response's own trace_id exactly matches the
    trace_id the caller expected to continue -- used to refuse to
    silently accept an unexpected trace_id as a safe same-run
    continuation (Resume must never be treated as succeeding against
    the wrong run).
    """
    return bool(expected_trace_id) and expected_trace_id == returned_trace_id


def requires_close_reason_text(close_reason_code: str | None) -> bool:
    """
    True only for CASE_CLOSE_OTHER -- the one close reason the backend
    itself requires accompanying explanatory text for (see
    src/workflow/human_review_service.py's own validation). Every
    other approved CASE_CLOSE_* code needs no additional text.
    """
    return close_reason_code == "CASE_CLOSE_OTHER"


__all__ = [
    "ALLOWED_HUMAN_REVIEW_OUTCOMES",
    "CLOSE_CASE_REASON_CODES",
    "REVIEWER_ACTOR_TYPE_CODE",
    "extract_workflow_summary",
    "extract_audit_event_rows",
    "extract_human_review_summary",
    "normalize_to_workflow_response_shape",
    "describe_workflow_status",
    "is_human_review_pending_eligible",
    "is_resume_eligible",
    "is_same_trace",
    "requires_close_reason_text",
]
