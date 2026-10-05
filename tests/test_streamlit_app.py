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


def test_audit_view_is_labeled_latest_response_snapshot():
    """Verify the Audit & Technical View page visibly states it is
    showing a latest-response snapshot, not a durable lookup."""
    at = run_app()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()

    assert not at.exception
    captions = [c.value for c in at.caption]
    assert "LATEST API RESPONSE SNAPSHOT" in captions


def test_no_backend_call_occurs_merely_by_rendering():
    """Verify navigating through every page without clicking "Process
    Case" never populates latest_workflow_response -- proving no HTTP
    call happens merely by rendering the app."""
    at = run_app()
    at.sidebar.radio[0].set_value("Healthcare Case Processing").run()
    at.sidebar.radio[0].set_value("Audit & Technical View").run()
    at.sidebar.radio[0].set_value("Client Requirement Intake").run()

    assert at.session_state["latest_workflow_response"] is None
