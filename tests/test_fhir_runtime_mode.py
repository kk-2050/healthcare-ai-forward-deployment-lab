# File Name: test_fhir_runtime_mode.py
# Purpose: Tests the Task 25C FHIR_MODE settings loader, the synthetic local runtime, and get_fhir_client()'s mode branching -- all offline, zero network.
# Creation Date: 2026-10-02
# Author: K.Kashiwagi
#
# Module Explanation:
# Covers three layers in one file, since all three exist only to serve
# one small feature (the Task 25C synthetic FHIR runtime mode):
# src/config/fhir_settings.py (FHIR_MODE parsing/validation),
# src/integrations/synthetic_fhir_runtime.py (the zero-network
# synthetic client factory), and src/api/dependencies.py's
# get_fhir_client() (the mode branch). FastAPI-level tests proving the
# real dependency path end to end live in tests/test_api_workflow_start.py
# and tests/test_api_workflow_resume.py instead, next to every other
# test for those two endpoints.

import httpx
import pytest
from pydantic import ValidationError

from src.api.dependencies import FHIRIntegrationNotConfiguredError, get_fhir_client
from src.config.fhir_settings import FHIRRuntimeSettings, load_fhir_runtime_settings
from src.integrations.fhir_client import FHIRStyleClient
from src.integrations.synthetic_fhir_runtime import build_synthetic_fhir_client


# =====================================================================
# SETTINGS LOADER TESTS
# Purpose:
# Protect FHIR_MODE parsing/validation in isolation from any process
# environment or local .env -- every test here passes an explicit
# `env` mapping, exactly mirroring load_database_settings()/
# load_azure_openai_settings()'s existing test convention.
# =====================================================================
def test_missing_fhir_mode_defaults_to_disabled():
    """Verify an environment with no FHIR_MODE key at all resolves to
    the safe default, disabled."""
    settings = load_fhir_runtime_settings(env={})
    assert settings.mode == "disabled"


def test_blank_fhir_mode_defaults_to_disabled():
    """Verify FHIR_MODE="" (present but blank) resolves to disabled,
    the same as if it were absent -- "not configured" and "explicitly
    disabled" are deliberately the same safe outcome."""
    settings = load_fhir_runtime_settings(env={"FHIR_MODE": ""})
    assert settings.mode == "disabled"


@pytest.mark.parametrize("raw_value", ["disabled", "DISABLED", " Disabled ", "  disabled"])
def test_disabled_variants_resolve_to_disabled(raw_value):
    """Verify disabled is recognized case-insensitively and with
    surrounding whitespace stripped."""
    settings = load_fhir_runtime_settings(env={"FHIR_MODE": raw_value})
    assert settings.mode == "disabled"


@pytest.mark.parametrize("raw_value", ["synthetic", "SYNTHETIC", " Synthetic "])
def test_synthetic_variants_resolve_to_synthetic(raw_value):
    """Verify synthetic is recognized case-insensitively and with
    surrounding whitespace stripped."""
    settings = load_fhir_runtime_settings(env={"FHIR_MODE": raw_value})
    assert settings.mode == "synthetic"


@pytest.mark.parametrize("raw_value", ["live", "LIVE", " Live "])
def test_live_variants_resolve_to_live(raw_value):
    """Verify live is recognized case-insensitively and with
    surrounding whitespace stripped -- recognizing the word is not the
    same as implementing it (see get_fhir_client() tests below)."""
    settings = load_fhir_runtime_settings(env={"FHIR_MODE": raw_value})
    assert settings.mode == "live"


def test_invalid_fhir_mode_raises_validation_error():
    """Verify an unrecognized value is a hard configuration error, not
    a silent fallback to disabled or synthetic."""
    with pytest.raises(ValidationError):
        load_fhir_runtime_settings(env={"FHIR_MODE": "bogus"})


def test_settings_reads_real_os_environ_when_no_mapping_supplied(monkeypatch):
    """Verify the loader falls back to the real process environment
    only when no explicit mapping is supplied -- this is the one test
    that intentionally touches os.environ, and it fully controls the
    value it sets, so it stays deterministic regardless of any local
    .env."""
    monkeypatch.setenv("FHIR_MODE", "synthetic")
    settings = load_fhir_runtime_settings()
    assert settings.mode == "synthetic"


def test_settings_model_forbids_unknown_fields():
    """Verify FHIRRuntimeSettings rejects an unexpected field rather
    than silently ignoring it -- the same extra="forbid" discipline
    already used by DatabaseSettings/AzureOpenAISettings."""
    with pytest.raises(ValidationError):
        FHIRRuntimeSettings(mode="disabled", base_url="https://example.invalid")


# =====================================================================
# SYNTHETIC RUNTIME TESTS
# Purpose:
# Protect build_synthetic_fhir_client() in isolation -- these tests
# never go through get_fhir_client() or FastAPI, they call the
# factory directly.
# =====================================================================
def test_synthetic_client_returns_successful_evidence():
    """Verify the synthetic client's get_case_evidence() returns a
    successful outcome with the canonical synthetic evidence -- never
    a failure, never empty evidence."""
    client = build_synthetic_fhir_client()
    outcome = client.get_case_evidence("any-synthetic-case-id")

    assert outcome.success is True
    assert outcome.evidence.requested_service_code == "SYN-LUMBAR-MRI"
    assert outcome.evidence.diagnosis_codes == ["SYN-LOW-BACK-PAIN"]


def test_synthetic_client_is_case_id_independent():
    """Verify the synthetic client returns the identical deterministic
    evidence no matter what case_id is requested -- there is no hidden
    per-case-id branching (Task 25C Decision 1: one scenario only)."""
    client = build_synthetic_fhir_client()

    first = client.get_case_evidence("case-one")
    second = client.get_case_evidence("completely-different-case-two")

    assert first.evidence.model_dump() == second.evidence.model_dump()


def test_synthetic_client_repeated_calls_are_deterministic():
    """Verify calling the same synthetic client twice for the same
    case_id returns equivalent evidence both times -- no randomness,
    no hidden state."""
    client = build_synthetic_fhir_client()

    first = client.get_case_evidence("repeat-case")
    second = client.get_case_evidence("repeat-case")

    assert first.model_dump() == second.model_dump()


def test_synthetic_client_transport_is_mock_transport_only():
    """Verify the synthetic client's httpx.Client has no transport
    other than httpx.MockTransport -- no fallback transport, no real
    network path exists for this client to ever use."""
    client = build_synthetic_fhir_client()

    assert isinstance(client._http_client._transport, httpx.MockTransport)


def test_synthetic_client_never_touches_a_real_socket(monkeypatch):
    """Zero-network proof: fail the test loudly if the synthetic
    client's request ever reaches a real socket-level connection
    attempt. httpx.MockTransport intercepts the request entirely
    in-process, so the real connection machinery below it must never
    be invoked."""

    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "A real network connection was attempted by the synthetic "
            "FHIR client -- MockTransport should have intercepted this "
            "request entirely in-process."
        )

    monkeypatch.setattr("socket.socket.connect", _fail_if_called)

    client = build_synthetic_fhir_client()
    outcome = client.get_case_evidence("zero-network-proof-case")

    assert outcome.success is True


# =====================================================================
# get_fhir_client() DEPENDENCY BRANCHING TESTS
# Purpose:
# Exercise get_fhir_client()'s own real implementation directly
# (never through app.dependency_overrides) -- every test here must
# control FHIR_MODE explicitly so it never depends on a developer's
# local .env (see this project's Task 25C environment-isolation
# requirement).
# =====================================================================
def test_dependency_explicit_disabled_fails_closed(monkeypatch):
    """Verify an explicit FHIR_MODE=disabled raises
    FHIRIntegrationNotConfiguredError -- the process value is set
    directly, so load_dotenv()'s default override=False behavior
    cannot change it regardless of any local .env."""
    monkeypatch.setenv("FHIR_MODE", "disabled")

    with pytest.raises(FHIRIntegrationNotConfiguredError):
        get_fhir_client()


def test_dependency_truly_unset_fails_closed(monkeypatch):
    """Verify FHIR_MODE being genuinely absent (not merely unset in
    this test's own env snapshot) still fails closed -- load_dotenv is
    neutralized so a developer's local .env cannot repopulate the
    variable after it is removed here."""
    monkeypatch.delenv("FHIR_MODE", raising=False)
    monkeypatch.setattr(
        "src.api.dependencies.load_dotenv", lambda *args, **kwargs: None
    )

    with pytest.raises(FHIRIntegrationNotConfiguredError):
        get_fhir_client()


def test_dependency_live_fails_closed(monkeypatch):
    """Verify FHIR_MODE=live raises the same fail-closed exception --
    recognizing the word "live" never means a live client is built."""
    monkeypatch.setenv("FHIR_MODE", "live")

    with pytest.raises(FHIRIntegrationNotConfiguredError):
        get_fhir_client()


def test_dependency_invalid_mode_fails_closed(monkeypatch):
    """Verify an unrecognized FHIR_MODE value raises
    FHIRIntegrationNotConfiguredError (never a bare ValidationError,
    never a 500) -- the settings-layer ValidationError is caught and
    translated, never left to propagate as a different error type."""
    monkeypatch.setenv("FHIR_MODE", "bogus")

    with pytest.raises(FHIRIntegrationNotConfiguredError):
        get_fhir_client()


def test_dependency_synthetic_returns_working_client(monkeypatch):
    """Verify FHIR_MODE=synthetic returns a real, working
    FHIRStyleClient through get_fhir_client()'s own implementation."""
    monkeypatch.setenv("FHIR_MODE", "synthetic")

    client = get_fhir_client()

    assert isinstance(client, FHIRStyleClient)
    outcome = client.get_case_evidence("dependency-synthetic-case")
    assert outcome.success is True
