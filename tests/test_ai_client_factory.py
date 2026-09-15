# File Name: test_ai_client_factory.py
# Purpose: Tests Azure OpenAI settings loading, endpoint normalization, and client/provider construction offline.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect the configuration layer added in Task 15A:
# AzureOpenAISettings (src/config/settings.py) and the client/provider
# factories (src/ai/client_factory.py). Every test uses synthetic
# configuration values and an injected environment mapping — none of
# them read the real process environment, create a real .env file, or
# make any network/DNS call. Constructing an OpenAI client object is
# allowed and tested here; calling it (making a model request) is not.

import inspect

import pytest
from openai import OpenAI
from pydantic import SecretStr, ValidationError

from src.ai import client_factory
from src.ai.azure_provider import AzureOpenAIAnalysisProvider
from src.ai.client_factory import (
    build_azure_openai_base_url,
    create_azure_openai_client,
    create_azure_openai_provider,
)
from src.config import settings as settings_module
from src.config.settings import AzureOpenAISettings, load_azure_openai_settings


def valid_env(**overrides):
    """A minimal, fully valid synthetic environment mapping."""
    data = {
        "AZURE_OPENAI_ENDPOINT": "https://synthetic-resource.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "synthetic-test-key",
        "AZURE_OPENAI_DEPLOYMENT": "synthetic-deployment",
    }
    data.update(overrides)
    return data


def valid_settings(**overrides) -> AzureOpenAISettings:
    """A minimal, fully valid AzureOpenAISettings built from synthetic values."""
    data = {
        "endpoint": "https://synthetic-resource.openai.azure.com/",
        "api_key": "synthetic-test-key",
        "deployment_name": "synthetic-deployment",
    }
    data.update(overrides)
    return AzureOpenAISettings(**data)


# =====================================================================
# SETTINGS LOADING TESTS
# =====================================================================
def test_valid_environment_mapping_loads_settings():
    """Verify a fully valid, injected environment mapping loads into
    AzureOpenAISettings with the expected values."""
    # TEST-009A
    settings = load_azure_openai_settings(valid_env())

    assert settings.endpoint == "https://synthetic-resource.openai.azure.com/"
    assert settings.deployment_name == "synthetic-deployment"
    assert settings.api_key.get_secret_value() == "synthetic-test-key"


def test_missing_endpoint_fails():
    """Verify settings loading fails when AZURE_OPENAI_ENDPOINT is
    absent — a missing endpoint must never silently produce an unusable
    client later."""
    # TEST-009B
    env = valid_env()
    del env["AZURE_OPENAI_ENDPOINT"]

    with pytest.raises(ValidationError):
        load_azure_openai_settings(env)


def test_missing_api_key_fails():
    """Verify settings loading fails when AZURE_OPENAI_API_KEY is
    absent."""
    # TEST-009C
    env = valid_env()
    del env["AZURE_OPENAI_API_KEY"]

    with pytest.raises(ValidationError):
        load_azure_openai_settings(env)


def test_missing_deployment_fails():
    """Verify settings loading fails when AZURE_OPENAI_DEPLOYMENT is
    absent."""
    # TEST-009D
    env = valid_env()
    del env["AZURE_OPENAI_DEPLOYMENT"]

    with pytest.raises(ValidationError):
        load_azure_openai_settings(env)


def test_blank_endpoint_fails():
    """Verify an empty-string endpoint is rejected, not treated as a
    usable (but empty) configuration value."""
    # TEST-009E
    with pytest.raises(ValidationError):
        load_azure_openai_settings(valid_env(AZURE_OPENAI_ENDPOINT=""))


def test_blank_api_key_fails():
    """Verify an empty-string API key is rejected."""
    # TEST-009F
    with pytest.raises(ValidationError):
        load_azure_openai_settings(valid_env(AZURE_OPENAI_API_KEY=""))


def test_blank_deployment_fails():
    """Verify an empty-string deployment name is rejected."""
    # TEST-009G
    with pytest.raises(ValidationError):
        load_azure_openai_settings(valid_env(AZURE_OPENAI_DEPLOYMENT=""))


def test_non_https_endpoint_fails():
    """Verify a plain http:// endpoint is rejected — Azure OpenAI
    configuration must always use https://."""
    # TEST-009H
    with pytest.raises(ValidationError):
        load_azure_openai_settings(
            valid_env(
                AZURE_OPENAI_ENDPOINT="http://synthetic-resource.openai.azure.com/"
            )
        )


# =====================================================================
# ENDPOINT HOST SECURITY TESTS
#
# These tests protect against the API key later being sent to the
# wrong host by mistake. They only use synthetic resource names — no
# real Azure OpenAI or Microsoft Foundry resource address appears
# anywhere in this file.
# =====================================================================
def test_synthetic_azure_openai_host_is_accepted():
    """
    Verify a normal Azure OpenAI resource host
    ("*.openai.azure.com") is accepted, so legitimate configuration is
    not blocked by the security hardening.
    """
    # TEST-009X
    settings = valid_settings(
        endpoint="https://synthetic-resource.openai.azure.com/"
    )

    assert settings.endpoint == "https://synthetic-resource.openai.azure.com/"


def test_synthetic_foundry_host_is_accepted():
    """
    Verify a Microsoft Foundry resource host
    ("*.services.ai.azure.com") is accepted as an alternate, equally
    valid Azure OpenAI resource pattern.
    """
    # TEST-009Y
    settings = valid_settings(
        endpoint="https://synthetic-resource.services.ai.azure.com/"
    )

    assert (
        settings.endpoint == "https://synthetic-resource.services.ai.azure.com/"
    )


def test_unrelated_https_host_is_rejected():
    """
    Verify that an API key cannot be configured to use an unrelated
    HTTPS host by mistake.
    """
    # TEST-009Z
    with pytest.raises(ValidationError):
        valid_settings(endpoint="https://example.com/")


def test_lookalike_host_is_rejected():
    """
    Verify a host that merely contains the expected suffix, but does
    not end with it, is rejected — a deceptive host like
    "...azure.com.evil.example" must not be treated as a trusted Azure
    OpenAI resource just because it contains the right text somewhere.
    """
    # TEST-009AA
    with pytest.raises(ValidationError):
        valid_settings(
            endpoint="https://synthetic-resource.openai.azure.com.evil.example/"
        )


def test_host_without_resource_prefix_is_rejected():
    """
    Verify the bare suffix host with no resource name in front of it
    ("openai.azure.com") is rejected — a real Azure OpenAI endpoint
    always has a specific resource name before the suffix.
    """
    # TEST-009AB
    with pytest.raises(ValidationError):
        valid_settings(endpoint="https://openai.azure.com/")


def test_url_with_user_info_is_rejected():
    """
    Verify a URL containing embedded username/password information is
    rejected — user-info syntax is not a legitimate way to configure
    this endpoint and could be used to disguise the real target host.
    """
    # TEST-009AC
    with pytest.raises(ValidationError):
        valid_settings(
            endpoint="https://synthetic-user:synthetic-pass@"
            "synthetic-resource.openai.azure.com/"
        )


def test_url_with_query_string_is_rejected():
    """Verify a URL containing a query string is rejected — the
    endpoint must be a plain resource address, not a request with
    parameters attached."""
    # TEST-009AD
    with pytest.raises(ValidationError):
        valid_settings(
            endpoint="https://synthetic-resource.openai.azure.com/?foo=bar"
        )


def test_url_with_fragment_is_rejected():
    """Verify a URL containing a fragment is rejected."""
    # TEST-009AE
    with pytest.raises(ValidationError):
        valid_settings(
            endpoint="https://synthetic-resource.openai.azure.com/#frag"
        )


def test_unexpected_path_is_rejected():
    """
    Verify a path this project never calls (anything other than empty,
    "/", "/openai/v1", or "/openai/v1/") is rejected, so configuration
    cannot silently point at some other, unexpected API path.
    """
    # TEST-009AF
    with pytest.raises(ValidationError):
        valid_settings(
            endpoint="https://synthetic-resource.openai.azure.com/some/other/path"
        )


# =====================================================================
# SECRET HANDLING TESTS
# =====================================================================
def test_api_key_is_secret_str():
    """Verify api_key is stored as a Pydantic SecretStr, not a plain
    string, so it gets automatic masking everywhere it might be
    displayed."""
    # TEST-009I
    settings = valid_settings()

    assert isinstance(settings.api_key, SecretStr)


def test_api_key_is_hidden_from_repr():
    """Verify the real API key value never appears in repr(settings) —
    a stray debug repr() call must not leak the secret."""
    # TEST-009J
    settings = valid_settings(api_key="synthetic-unique-marker-001")

    assert "synthetic-unique-marker-001" not in repr(settings)


def test_api_key_is_hidden_from_str():
    """Verify the real API key value never appears in str(settings)."""
    # TEST-009K
    settings = valid_settings(api_key="synthetic-unique-marker-002")

    assert "synthetic-unique-marker-002" not in str(settings)


# =====================================================================
# ENDPOINT NORMALIZATION TESTS
# =====================================================================
def test_base_url_ends_with_openai_v1():
    """Verify the normalized base URL always ends with
    "/openai/v1/", the path the Azure OpenAI v1 client needs."""
    # TEST-009L
    base_url = build_azure_openai_base_url(
        "https://synthetic-resource.openai.azure.com"
    )

    assert base_url == "https://synthetic-resource.openai.azure.com/openai/v1/"


def test_trailing_slash_does_not_produce_double_slash():
    """Verify an endpoint that already ends with a trailing slash does
    not produce "//" when the suffix is appended."""
    # TEST-009M
    base_url = build_azure_openai_base_url(
        "https://synthetic-resource.openai.azure.com/"
    )

    assert "//" not in base_url.replace("https://", "", 1)
    assert base_url == "https://synthetic-resource.openai.azure.com/openai/v1/"


def test_existing_openai_v1_suffix_is_not_duplicated():
    """Verify an endpoint that already includes "/openai/v1/" is not
    given the suffix a second time."""
    # TEST-009N
    base_url = build_azure_openai_base_url(
        "https://synthetic-resource.openai.azure.com/openai/v1/"
    )

    assert base_url == "https://synthetic-resource.openai.azure.com/openai/v1/"
    assert base_url.count("openai/v1") == 1


def test_deployment_name_is_not_part_of_base_url():
    """Verify the deployment name never appears inside the client's
    base URL — the deployment is passed to the provider separately, not
    embedded in the endpoint path."""
    # TEST-009O
    settings = valid_settings(deployment_name="synthetic-unique-deployment-001")

    client = create_azure_openai_client(settings)

    assert "synthetic-unique-deployment-001" not in str(client.base_url)


# =====================================================================
# ENVIRONMENT LOADER BEHAVIOR TESTS
# =====================================================================
def test_api_version_variable_is_ignored():
    """Verify AZURE_OPENAI_API_VERSION has no effect on the loaded
    settings — the current Azure OpenAI v1 client path does not use
    it."""
    # TEST-009P
    env_without_version = valid_env()
    env_with_version = valid_env(AZURE_OPENAI_API_VERSION="2099-01-01-preview")

    settings_without = load_azure_openai_settings(env_without_version)
    settings_with = load_azure_openai_settings(env_with_version)

    assert settings_without.endpoint == settings_with.endpoint
    assert settings_without.deployment_name == settings_with.deployment_name
    assert (
        settings_without.api_key.get_secret_value()
        == settings_with.api_key.get_secret_value()
    )


def test_injected_mapping_is_used_instead_of_process_environment(monkeypatch):
    """Verify an explicitly injected mapping is used for loading
    settings, so tests never depend on (or are affected by) whatever is
    actually set in the real process environment."""
    # TEST-009Q
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://real-looking-value.example.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "should-not-be-used")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "should-not-be-used")

    settings = load_azure_openai_settings(valid_env())

    assert settings.endpoint == "https://synthetic-resource.openai.azure.com/"
    assert settings.deployment_name == "synthetic-deployment"


# =====================================================================
# CLIENT FACTORY TESTS
# =====================================================================
def test_client_factory_returns_an_openai_client():
    """Verify create_azure_openai_client() returns an actual OpenAI SDK
    client instance."""
    # TEST-009R
    client = create_azure_openai_client(valid_settings())

    assert isinstance(client, OpenAI)


def test_creating_the_client_performs_no_network_request(monkeypatch):
    """
    Verify building the OpenAI client never opens a network socket.

    Patches socket.socket.connect to raise if called, proving client
    construction is offline — only calling a request method (which
    Task 15A never does) would need a real connection.
    """
    # TEST-009S
    import socket

    def _blocked_connect(self, *args, **kwargs):
        raise AssertionError("network connection attempted during client construction")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

    client = create_azure_openai_client(valid_settings())

    assert isinstance(client, OpenAI)


def test_client_construction_does_not_mutate_settings():
    """Verify building the client never changes the settings object it
    was given."""
    # TEST-009T
    settings = valid_settings()
    original_endpoint = settings.endpoint
    original_deployment = settings.deployment_name
    original_key = settings.api_key.get_secret_value()

    create_azure_openai_client(settings)

    assert settings.endpoint == original_endpoint
    assert settings.deployment_name == original_deployment
    assert settings.api_key.get_secret_value() == original_key


# =====================================================================
# PROVIDER FACTORY TESTS
# =====================================================================
def test_provider_factory_returns_azure_provider():
    """Verify create_azure_openai_provider() returns an
    AzureOpenAIAnalysisProvider, ready to inject into run_ai_analysis()
    or the workflow."""
    # TEST-009U
    provider = create_azure_openai_provider(valid_settings())

    assert isinstance(provider, AzureOpenAIAnalysisProvider)


def test_provider_factory_passes_configured_deployment_name():
    """Verify the provider built by the factory is wired to the exact
    deployment name from settings, not a default or placeholder."""
    # TEST-009V
    settings = valid_settings(deployment_name="synthetic-unique-deployment-002")

    provider = create_azure_openai_provider(settings)

    assert provider._deployment_name == "synthetic-unique-deployment-002"


# =====================================================================
# SAFETY / SCOPE TESTS
# =====================================================================
def test_no_ptu_configuration_is_introduced():
    """Verify no Provisioned Throughput (PTU) configuration exists
    anywhere in the configuration or client-factory source — this
    prototype uses standard pay-as-you-go consumption only."""
    # TEST-009W
    forbidden_markers = [
        "ptu",
        "provisioned throughput",
        "provisioned_throughput",
        "reserved_throughput",
        "reserved throughput",
    ]

    combined_source = (
        inspect.getsource(settings_module) + inspect.getsource(client_factory)
    ).lower()

    for marker in forbidden_markers:
        assert marker not in combined_source
