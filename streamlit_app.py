# File Name: streamlit_app.py
# Purpose: Phase 1 Streamlit UI shell -- a thin HTTP/JSON client over the existing FastAPI backend.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# This file is the only place src/ui/api_client.py is used. It never
# imports LangGraph, a workflow service, a repository, a SQLAlchemy
# session, a FHIR client, or the AI provider -- every backend action
# goes through one HTTP call to the existing FastAPI application (see
# src/api/app.py). This keeps the real architecture boundary
# (Streamlit -> FastAPI -> everything else) structurally true, not
# just documented.
#
# THREE PRIMARY AREAS (Task 26A's approved information architecture --
# unchanged by Task 26C-2; Human Review and Resume live inside
# Healthcare Case Processing, never as a fourth top-level page):
# 1. Client Requirement Intake -- MOCKED / UI-ONLY. Demonstrates FDE
#    requirements discovery/translation; st.session_state only, never
#    persisted, never sent to any backend.
# 2. Healthcare Case Processing -- the real, implemented path: a
#    canonical synthetic demo case submitted to POST /workflows, plus
#    (Task 26C-2) discovering a pending Human Review, submitting a
#    decision, and resuming the same run/trace when eligible.
# 3. Audit & Technical View -- the latest response snapshot already
#    held in session state, plus (Task 26C-2) an explicit "Refresh
#    Workflow State" action that durably re-fetches the current state
#    via GET /workflows/{trace_id}.
#
# SAFETY BOUNDARY (unchanged by Task 26C-2):
# - Human Review outcomes are restricted to the four real
#   HumanReviewOutcome values (src/ui/view_helpers.py's
#   ALLOWED_HUMAN_REVIEW_OUTCOMES, copied verbatim from
#   src/models/human_review.py) -- no approve/deny control exists or
#   could exist, since no such value exists in the real backend enum.
# - Resume is only ever offered when the backend's own last-known
#   workflow_status_code is PENDING_RESUME, and a Resume response
#   whose trace_id does not match the one being continued is treated
#   as an unsafe/inconsistent result, never silently accepted.
# - The HTTP error boundary (Task 26C-1B) is unchanged: every
#   non-2xx/connection/timeout failure is mapped to a fixed, local,
#   safe message -- never the backend's own response text.

import os
from datetime import datetime, timezone

import streamlit as st

from src.ui.api_client import APIClient, APIClientError
from src.ui.demo_data import build_canonical_demo_payload
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

_DEFAULT_FASTAPI_BASE_URL = "http://127.0.0.1:8000"
_DEFAULT_SYNTHETIC_REVIEWER_REFERENCE = "SYN-REVIEWER-001"

_REQUIREMENT_INTAKE_FIELDS = (
    ("client_request", "Client Request"),
    ("business_goal", "Business Goal"),
    ("stakeholders", "Stakeholders"),
    ("functional_requirements", "Functional Requirements"),
    ("technical_requirements", "Technical Requirements"),
    ("missing_information", "Missing Information"),
    ("risks", "Risks"),
    ("acceptance_criteria", "Acceptance Criteria"),
)

_NOT_FOUND_LOCAL_MESSAGES = {
    "workflow": (
        "No workflow run was found for this trace ID yet. Submit a case "
        "first, or confirm the trace ID is correct."
    ),
    "pending_review": (
        "No pending Human Review was found for this trace ID. The case may "
        "not require review, or a decision may already have been recorded."
    ),
}


@st.cache_resource
def _get_api_client() -> APIClient:
    """Builds (once per Streamlit session process) the one API client
    this app uses, pointed at FASTAPI_BASE_URL -- never a
    machine-specific hard-coded address."""
    base_url = os.environ.get("FASTAPI_BASE_URL", _DEFAULT_FASTAPI_BASE_URL)
    return APIClient(base_url=base_url)


def _init_session_state() -> None:
    """Initializes every session_state key this app uses, exactly
    once. Keeps session state to the minimum: UI/session identifiers
    and the latest response snapshots only -- never a DB session,
    secret, or raw FHIR/LLM payload (none of which this app ever
    receives in the first place). resume_available is deliberately NOT
    stored here -- it is derived fresh from latest_workflow_response on
    every render (see is_resume_eligible())."""
    if "requirements_intake" not in st.session_state:
        st.session_state["requirements_intake"] = {key: "" for key, _ in _REQUIREMENT_INTAKE_FIELDS}
    if "current_case_request" not in st.session_state:
        st.session_state["current_case_request"] = build_canonical_demo_payload()
    if "current_case_id" not in st.session_state:
        st.session_state["current_case_id"] = None
    if "current_trace_id" not in st.session_state:
        st.session_state["current_trace_id"] = None
    if "latest_workflow_response" not in st.session_state:
        st.session_state["latest_workflow_response"] = None
    if "pending_human_review" not in st.session_state:
        st.session_state["pending_human_review"] = None
    if "latest_human_review_response" not in st.session_state:
        st.session_state["latest_human_review_response"] = None
    if "last_ui_message" not in st.session_state:
        st.session_state["last_ui_message"] = None


def _set_message(level: str, text: str) -> None:
    st.session_state["last_ui_message"] = (level, text)


def _store_workflow_response(response_body: dict) -> None:
    """Normalizes any of the four workflow-bearing response shapes
    into one consistent {trace_id, case_id, workflow_run, audit_events}
    shape before storing it -- so every renderer/eligibility check
    works the same regardless of which endpoint produced the
    response."""
    st.session_state["latest_workflow_response"] = normalize_to_workflow_response_shape(response_body)


def _current_workflow_summary() -> dict:
    response = st.session_state["latest_workflow_response"]
    return extract_workflow_summary(response) if response else {}


def _render_requirement_intake() -> None:
    st.header("Client Requirement Intake")
    st.warning(
        "MOCKED / UI-ONLY -- this section demonstrates requirements "
        "discovery and translation for this portfolio project. Nothing "
        "entered here is persisted or sent to any backend in Phase 1."
    )

    intake = st.session_state["requirements_intake"]
    for key, label in _REQUIREMENT_INTAKE_FIELDS:
        intake[key] = st.text_area(label, value=intake[key], key=f"intake_{key}")


def _render_case_processing() -> None:
    st.header("Healthcare Case Processing")
    st.caption("IMPLEMENTED BACKEND / STREAMLIT CLIENT")
    st.info("Synthetic Data Only -- no real PHI/PII is used anywhere in this demo.")

    request = st.session_state["current_case_request"]
    case = request["case"]
    completeness = request["completeness_requirements"]

    request["client_id"] = st.text_input("Client ID", value=request["client_id"])
    case["case_id"] = st.text_input("Case ID", value=case["case_id"])
    case["member_id"] = st.text_input("Member ID", value=case["member_id"])
    case["provider_id"] = st.text_input("Provider ID", value=case["provider_id"])
    case["requested_service_code"] = st.text_input(
        "Requested Service Code", value=case["requested_service_code"]
    )
    case["diagnosis_code"] = st.text_input("Diagnosis Code", value=case["diagnosis_code"])
    case["requested_date"] = st.text_input(
        "Requested Date (YYYY-MM-DD)", value=case["requested_date"]
    )
    completeness["clinical_notes_required"] = st.checkbox(
        "Clinical notes required", value=completeness["clinical_notes_required"]
    )

    if st.button("Process Case", type="primary"):
        client = _get_api_client()
        try:
            response_body = client.start_workflow(request)
        except APIClientError as error:
            _set_message("error", error.message)
        else:
            _store_workflow_response(response_body)
            st.session_state["current_case_id"] = response_body.get("case_id")
            st.session_state["current_trace_id"] = response_body.get("trace_id")
            st.session_state["pending_human_review"] = None
            st.session_state["latest_human_review_response"] = None
            _set_message("success", "The case was submitted successfully.")

    _render_last_message()
    _render_workflow_result(st.session_state["latest_workflow_response"])

    workflow_summary = _current_workflow_summary()
    _render_human_review_section(workflow_summary)
    _render_resume_section(workflow_summary)


def _render_last_message() -> None:
    last_message = st.session_state["last_ui_message"]
    if last_message is not None:
        level, text = last_message
        getattr(st, level)(text)


def _render_workflow_result(response_body: dict | None) -> None:
    if response_body is None:
        return

    st.subheader("Workflow Result")
    summary = extract_workflow_summary(response_body)
    st.write(f"**Case ID:** {summary.get('case_id', '')}")
    st.write(f"**Trace ID:** {summary.get('trace_id', '')}")
    st.write(f"**Workflow Status:** {summary.get('workflow_status_code', '')}")
    st.write(f"**Next Action:** {summary.get('next_action_code', '')}")
    st.write(f"**Human Review Required:** {summary.get('human_review_required', '')}")
    st.write(f"**Failure Category:** {summary.get('failure_category_code', '')}")
    st.write(f"**Started At:** {summary.get('started_at_utc', '')}")
    st.write(f"**Completed At:** {summary.get('completed_at_utc', '')}")
    st.caption(describe_workflow_status(summary.get("workflow_status_code")))

    st.subheader("Audit Events")
    events = extract_audit_event_rows(response_body)
    if events:
        st.table(events)
    else:
        st.write("No audit events were returned.")


# =====================================================================
# HUMAN REVIEW SECTION (Task 26C-2)
# Purpose:
# Lets the operator discover a pending Human Review by trace_id (never
# by typing a review_id manually) and submit one of the four real,
# approved outcomes. No approval/denial control exists here, and none
# can be added without also adding it to the real backend enum this
# section's outcome list is copied from.
# =====================================================================
def _render_human_review_section(workflow_summary: dict) -> None:
    if not is_human_review_pending_eligible(workflow_summary):
        return

    trace_id = workflow_summary.get("trace_id")
    st.subheader("Human Review")
    st.caption("HUMAN-IN-THE-LOOP")
    st.info(
        "Automated processing is paused for a human reviewer. This project "
        "never lets AI approve or deny a case -- only a human decision, "
        "submitted below, can move this case forward."
    )

    if st.button("Load Pending Human Review"):
        client = _get_api_client()
        try:
            record = client.get_pending_human_review(trace_id)
        except APIClientError as error:
            message = (
                _NOT_FOUND_LOCAL_MESSAGES["pending_review"]
                if error.status_code == 404
                else error.message
            )
            _set_message("error", message)
        else:
            st.session_state["pending_human_review"] = record
            _set_message("success", "The pending Human Review was loaded.")

    pending = st.session_state["pending_human_review"]
    if pending is None or pending.get("trace_id") != trace_id:
        return

    review_summary = extract_human_review_summary(pending)
    st.write(f"**Review ID:** {review_summary.get('review_id', '')}")
    st.write(f"**Review Status:** {review_summary.get('review_status_code', '')}")
    st.write(f"**Reason:** {review_summary.get('reason_code', '')}")
    st.write(f"**Requested At:** {review_summary.get('requested_at_utc', '')}")

    outcome = st.selectbox("Review Outcome", ALLOWED_HUMAN_REVIEW_OUTCOMES)
    reviewer_reference = st.text_input(
        "Reviewer Reference (synthetic only)", value=_DEFAULT_SYNTHETIC_REVIEWER_REFERENCE
    )
    review_note_text = st.text_area("Review Note (optional)", value="")

    close_reason_code = None
    close_reason_text = None
    if outcome == "CLOSE_CASE":
        close_reason_code = st.selectbox("Close Reason", CLOSE_CASE_REASON_CODES)
        if requires_close_reason_text(close_reason_code):
            close_reason_text = st.text_input("Close Reason Text (required for CASE_CLOSE_OTHER)")

    if st.button("Submit Decision", type="primary"):
        payload = {
            "review_id": review_summary.get("review_id"),
            "review_outcome_code": outcome,
            "reviewer_actor_type_code": REVIEWER_ACTOR_TYPE_CODE,
            "reviewer_reference": reviewer_reference,
            "decision_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if review_note_text:
            payload["review_note_text"] = review_note_text
        if outcome == "CLOSE_CASE":
            payload["close_reason_code"] = close_reason_code
            if close_reason_text:
                payload["close_reason_text"] = close_reason_text

        client = _get_api_client()
        try:
            response_body = client.submit_human_review_decision(payload)
        except APIClientError as error:
            _set_message("error", error.message)
        else:
            _store_workflow_response(response_body)
            st.session_state["latest_human_review_response"] = response_body.get("review")
            st.session_state["pending_human_review"] = None
            _set_message("success", "The Human Review decision was recorded.")


# =====================================================================
# RESUME SECTION (Task 26C-2)
# Purpose:
# Continues the SAME persisted workflow run on the SAME trace_id when,
# and only when, the backend's own last-known state says PENDING_RESUME
# -- never a new case, never a new trace, never LangGraph checkpoint
# restoration.
# =====================================================================
def _render_resume_section(workflow_summary: dict) -> None:
    if not is_resume_eligible(workflow_summary):
        return

    trace_id = workflow_summary.get("trace_id")
    st.subheader("Resume")
    st.caption("SAME-RUN / SAME-TRACE CONTINUATION")
    st.info(
        "This continues the same persisted workflow run using the same "
        "trace ID. It is not a new case, not a new trace, and not "
        "LangGraph checkpoint restoration."
    )

    if st.button("Resume Workflow", type="primary"):
        request = st.session_state["current_case_request"]
        resume_body = {
            "case": request["case"],
            "completeness_requirements": request["completeness_requirements"],
            "ai_processing_requirements": request["ai_processing_requirements"],
        }

        client = _get_api_client()
        try:
            response_body = client.resume_workflow(trace_id, resume_body)
        except APIClientError as error:
            _set_message("error", error.message)
        else:
            if not is_same_trace(trace_id, response_body.get("trace_id")):
                _set_message(
                    "error",
                    "The backend returned an unexpected trace ID for this "
                    "resume request. This response was not applied.",
                )
            else:
                _store_workflow_response(response_body)
                st.session_state["pending_human_review"] = None
                st.session_state["latest_human_review_response"] = None
                _set_message("success", "The workflow was resumed successfully.")


def _render_audit_view() -> None:
    st.header("Audit & Technical View")
    st.caption("DURABLE BACKEND SNAPSHOT AVAILABLE")
    st.info(
        "Shows the latest response already received this session. Use "
        "Refresh Workflow State below to durably re-fetch the current "
        "state from the backend for the current trace ID."
    )

    trace_id = st.session_state["current_trace_id"]
    if trace_id and st.button("Refresh Workflow State"):
        client = _get_api_client()
        try:
            response_body = client.get_workflow(trace_id)
        except APIClientError as error:
            message = (
                _NOT_FOUND_LOCAL_MESSAGES["workflow"]
                if error.status_code == 404
                else error.message
            )
            _set_message("error", message)
        else:
            _store_workflow_response(response_body)
            _set_message("success", "DURABLE BACKEND SNAPSHOT -- refreshed from GET /workflows/{trace_id}.")

    _render_last_message()
    _render_workflow_result(st.session_state["latest_workflow_response"])

    pending = st.session_state["pending_human_review"]
    if pending is not None:
        st.subheader("Pending Human Review")
        review_summary = extract_human_review_summary(pending)
        st.write(f"**Review ID:** {review_summary.get('review_id', '')}")
        st.write(f"**Review Status:** {review_summary.get('review_status_code', '')}")
        st.write(f"**Review Outcome:** {review_summary.get('review_outcome_code', '')}")
        st.write(f"**Reason:** {review_summary.get('reason_code', '')}")
        st.write(f"**Requested At:** {review_summary.get('requested_at_utc', '')}")
        st.write(f"**Completed At:** {review_summary.get('completed_at_utc', '')}")


def main() -> None:
    st.set_page_config(page_title="Healthcare AI Forward Deployment Lab")
    _init_session_state()

    st.sidebar.title("Healthcare AI Forward Deployment Lab")
    area = st.sidebar.radio(
        "Navigate",
        (
            "Client Requirement Intake",
            "Healthcare Case Processing",
            "Audit & Technical View",
        ),
    )

    if area == "Client Requirement Intake":
        _render_requirement_intake()
    elif area == "Healthcare Case Processing":
        _render_case_processing()
    else:
        _render_audit_view()

    st.sidebar.caption("Phase 1: A working prototype with a clear path to production.")


main()
