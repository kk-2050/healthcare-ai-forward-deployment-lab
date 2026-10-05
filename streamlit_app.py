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
# THREE PRIMARY AREAS (Task 26A's approved information architecture):
# 1. Client Requirement Intake -- MOCKED / UI-ONLY. Demonstrates FDE
#    requirements discovery/translation; st.session_state only, never
#    persisted, never sent to any backend.
# 2. Healthcare Case Processing -- the real, implemented path: a
#    canonical synthetic demo case, editable, submitted to the real
#    POST /workflows endpoint.
# 3. Audit & Technical View -- for Task 26C-1, shows only the latest
#    successful POST /workflows response already held in
#    st.session_state (a snapshot, not a durable lookup -- Task 26C-2
#    adds GET /workflows/{trace_id} for that).
#
# SCOPE (Task 26C-1 only): Human Review decision submission, Resume,
# and durable GET re-fetch are explicitly NOT built here -- see
# CLAUDE.md/README.md for the current PLANNED/NOT IMPLEMENTED status.

import os

import streamlit as st

from src.ui.api_client import APIClient, APIClientError
from src.ui.demo_data import build_canonical_demo_payload
from src.ui.view_helpers import describe_workflow_status, extract_audit_event_rows, extract_workflow_summary

_DEFAULT_FASTAPI_BASE_URL = "http://127.0.0.1:8000"

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
    and the latest response snapshot only -- never a DB session,
    secret, or raw FHIR/LLM payload (none of which this app ever
    receives in the first place)."""
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
    if "last_ui_message" not in st.session_state:
        st.session_state["last_ui_message"] = None


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
            st.session_state["last_ui_message"] = ("error", error.message)
        else:
            st.session_state["latest_workflow_response"] = response_body
            st.session_state["current_case_id"] = response_body.get("case_id")
            st.session_state["current_trace_id"] = response_body.get("trace_id")
            st.session_state["last_ui_message"] = ("success", "The case was submitted successfully.")

    last_message = st.session_state["last_ui_message"]
    if last_message is not None:
        level, text = last_message
        getattr(st, level)(text)

    _render_workflow_result(st.session_state["latest_workflow_response"])


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
    st.caption(describe_workflow_status(summary.get("workflow_status_code")))

    st.subheader("Audit Events")
    events = extract_audit_event_rows(response_body)
    if events:
        st.table(events)
    else:
        st.write("No audit events were returned.")


def _render_audit_view() -> None:
    st.header("Audit & Technical View")
    st.caption("LATEST API RESPONSE SNAPSHOT")
    st.info(
        "This shows only the most recent POST /workflows response already "
        "received this session -- not a durable lookup. A later task adds "
        "GET /workflows/{trace_id} so a past trace_id can be re-fetched."
    )
    _render_workflow_result(st.session_state["latest_workflow_response"])


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
