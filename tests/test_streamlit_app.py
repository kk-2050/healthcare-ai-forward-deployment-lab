# File Name: test_streamlit_app.py
# Purpose: A few stable Streamlit AppTest smoke checks for streamlit_app.py -- never a real backend/network call.
# Creation Date: 2026-10-05
# Author: K.Kashiwagi
#
# Module Explanation:
# Streamlit 1.63.0's streamlit.testing.v1.AppTest runs the app
# in-process against a scripted render -- confirmed directly against
# this project's installed version before relying on it. Kept
# deliberately small (a handful of stable structural checks) rather
# than exhaustive UI automation, per this project's own preference for
# testing extracted pure logic (see tests/test_streamlit_api_client.py/
# test_streamlit_view_helpers.py/test_streamlit_demo_data.py) over
# fragile browser-style automation. No test here clicks "Process Case"
# -- doing so would attempt a real HTTP call to FASTAPI_BASE_URL, which
# these tests must never do.

from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP_PATH = Path(__file__).resolve().parent.parent / "streamlit_app.py"


def run_app() -> AppTest:
    at = AppTest.from_file(str(_APP_PATH))
    at.run()
    return at


def test_app_starts_without_exception():
    """Verify the app renders its default page with no exception."""
    at = run_app()
    assert not at.exception


def test_three_primary_navigation_areas_are_visible():
    """Verify the sidebar navigation offers exactly the three Task 26A
    primary areas, in order."""
    at = run_app()
    options = at.sidebar.radio[0].options
    assert options == [
        "Client Requirement Intake",
        "Healthcare Case Processing",
        "Audit & Technical View",
    ]


def test_requirement_intake_is_labeled_mocked_ui_only():
    """Verify the default page (Client Requirement Intake) visibly
    states MOCKED / UI-ONLY."""
    at = run_app()
    warnings = [w.value for w in at.warning]
    assert any("MOCKED / UI-ONLY" in text for text in warnings)


def test_case_processing_identifies_synthetic_data_only():
    """Verify the Healthcare Case Processing page visibly states
    synthetic data only, and does not render without exception."""
    at = run_app()
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()

    assert not at.exception
    info_texts = [i.value for i in at.info]
    assert any("Synthetic Data Only" in text for text in info_texts)
    captions = [c.value for c in at.caption]
    assert "IMPLEMENTED BACKEND / STREAMLIT CLIENT" in captions


def test_audit_view_is_labeled_durable_backend_snapshot_available():
    """Verify the Audit & Technical View page visibly states a durable
    backend snapshot capability exists (Task 26C-2)."""
    at = run_app()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()

    assert not at.exception
    captions = [c.value for c in at.caption]
    assert "DURABLE BACKEND SNAPSHOT AVAILABLE" in captions


def test_no_backend_call_occurs_merely_by_rendering():
    """Verify navigating through every page without clicking "Process
    Case" never populates latest_workflow_response -- proving no HTTP
    call happens merely by rendering the app."""
    at = run_app()
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()
    at.sidebar.radio[0].set_value("Client Requirement Intake").run()

    assert at.session_state["latest_workflow_response"] is None


# =====================================================================
# HUMAN REVIEW / RESUME SECTION SMOKE CHECKS (Task 26C-2)
# Purpose:
# A handful of stable structural checks against pre-seeded
# session_state -- never clicking a button that would attempt a real
# HTTP call. Most behavior is covered by the pure-function tests in
# test_streamlit_view_helpers.py/test_streamlit_api_client.py; these
# checks only prove the page wires that logic into visible elements
# correctly.
# =====================================================================
def _seed_human_review_required_state(at: AppTest, *, with_pending_review: bool) -> AppTest:
    at.session_state["current_trace_id"] = "trace_demo_001"
    at.session_state["latest_workflow_response"] = {
        "trace_id": "trace_demo_001",
        "case_id": "case_demo_001",
        "workflow_run": {
            "workflow_status_code": "HUMAN_REVIEW_REQUIRED",
            "next_action_code": "ROUTE_HUMAN_REVIEW",
            "human_review_required": True,
        },
        "audit_events": [],
    }
    if with_pending_review:
        at.session_state["pending_human_review"] = {
            "review_id": "review_demo_001",
            "trace_id": "trace_demo_001",
            "case_id": "case_demo_001",
            "review_status_code": "REQUESTED",
            "review_outcome_code": None,
            "reason_code": "HUMAN_REVIEW_FHIR_FAILURE",
            "requested_at_utc": "2026-01-15T00:00:00Z",
            "completed_at_utc": None,
        }
    return at


def test_human_review_section_appears_only_when_required():
    """Verify the Human Review section (and its "Load Pending Human
    Review" button) appears only when the last known workflow state is
    HUMAN_REVIEW_REQUIRED -- not for an ordinary COMPLETED case."""
    at = run_app()
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()
    assert "Load Pending Human Review" not in [b.label for b in at.button]

    at = _seed_human_review_required_state(run_app(), with_pending_review=False)
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()

    assert not at.exception
    assert "Load Pending Human Review" in [b.label for b in at.button]


def test_human_review_decision_form_shows_allowed_outcomes_only_once_loaded():
    """Verify the decision form (with its outcome selectbox) appears
    only once a matching pending review is already in session_state --
    and that the selectbox offers exactly the four real outcomes."""
    at = _seed_human_review_required_state(run_app(), with_pending_review=True)
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()

    assert not at.exception
    assert "Submit Decision" in [b.label for b in at.button]
    outcome_selectboxes = [sb for sb in at.selectbox if "CONTINUE_WORKFLOW" in sb.options]
    assert len(outcome_selectboxes) == 1
    assert outcome_selectboxes[0].options == [
        "CONTINUE_WORKFLOW", "REQUEST_MORE_INFORMATION", "ESCALATE", "CLOSE_CASE",
    ]


def test_no_approve_deny_control_exists_anywhere_on_the_page():
    """Verify no element on the Human Review page offers an
    approve/deny/clinical-decision control, by label or by selectbox
    option -- structurally, not just by absence of a button we
    happened to think of."""
    at = _seed_human_review_required_state(run_app(), with_pending_review=True)
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()

    forbidden_terms = ("approve", "deny", "approval", "denial")
    all_button_labels = " ".join(b.label.lower() for b in at.button)
    all_selectbox_options = " ".join(
        option.lower() for sb in at.selectbox for option in sb.options
    )
    for term in forbidden_terms:
        assert term not in all_button_labels
        assert term not in all_selectbox_options


def test_resume_control_appears_only_for_pending_resume_state():
    """Verify the Resume control appears only when the last known
    workflow state is PENDING_RESUME, never for HUMAN_REVIEW_REQUIRED
    or an ordinary COMPLETED case."""
    at = _seed_human_review_required_state(run_app(), with_pending_review=False)
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()
    assert "Resume Workflow" not in [b.label for b in at.button]

    at = run_app()
    at.session_state["current_trace_id"] = "trace_demo_002"
    at.session_state["latest_workflow_response"] = {
        "trace_id": "trace_demo_002",
        "case_id": "case_demo_002",
        "workflow_run": {"workflow_status_code": "PENDING_RESUME", "next_action_code": "CONTINUE_PROCESSING"},
        "audit_events": [],
    }
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()

    assert not at.exception
    assert "Resume Workflow" in [b.label for b in at.button]


def test_audit_page_shows_refresh_control_when_trace_id_exists():
    """Verify the durable-refresh control appears on the Audit page
    only once a trace_id exists in session_state."""
    at = run_app()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()
    assert "Refresh Workflow State" not in [b.label for b in at.button]

    at = run_app()
    at.session_state["current_trace_id"] = "trace_demo_001"
    at.sidebar.radio[0].set_value("Audit & Technical View").run()

    assert not at.exception
    assert "Refresh Workflow State" in [b.label for b in at.button]


def test_no_backend_call_occurs_with_seeded_state_either():
    """Verify merely rendering pages with pre-seeded Human
    Review/Resume-eligible session_state still issues no HTTP call --
    only clicking a button would, and no test here clicks one."""
    at = _seed_human_review_required_state(run_app(), with_pending_review=True)
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()

    assert not at.exception
    assert at.session_state["pending_human_review"]["review_id"] == "review_demo_001"
