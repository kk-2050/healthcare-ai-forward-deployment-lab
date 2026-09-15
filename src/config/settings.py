# File Name: settings.py
# Purpose: Defines and loads the validated Azure OpenAI configuration used by the client factory.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

# Security policy, not a project-specific address: only hosts ending in
# one of these suffixes are ever accepted as an Azure OpenAI endpoint.
# The actual resource name prefix (e.g. "my-resource") always comes
# from external configuration and is never written here.
_ALLOWED_ENDPOINT_HOST_SUFFIXES = (
    ".openai.azure.com",
    ".services.ai.azure.com",
)

# The only request paths this project's client actually uses. An empty
# path or "/" is the bare resource root; "/openai/v1" and "/openai/v1/"
# are the normalized Azure OpenAI v1 base path (see
# src/ai/client_factory.py). Anything else is rejected.
_ALLOWED_ENDPOINT_PATHS = ("", "/", "/openai/v1", "/openai/v1/")

# =====================================================================
# AZURE OPENAI SETTINGS
# Purpose:
# Defines the three values the project needs to talk to an Azure
# OpenAI resource: the endpoint, the API key, and the deployment name.
# Rejects anything missing, blank, or malformed before any code tries
# to use it.
#
# Why:
# Task 14's AzureOpenAIAnalysisProvider deliberately does not read
# environment variables, load a key, or build an endpoint itself — it
# only accepts an already-configured client and a deployment name.
# This class is where "environment variable -> validated value"
# happens instead, so that concern lives in exactly one place.
#
# Important Notes:
# - api_key is a Pydantic SecretStr, not a plain str. Its real value is
#   hidden from repr()/str() and only ever read back out with
#   `.get_secret_value()` — and that should happen in exactly one
#   place: src/ai/client_factory.py, when building the SDK client.
# - This class does not read environment variables itself; see
#   load_azure_openai_settings() below for that.
# =====================================================================


class AzureOpenAISettings(BaseModel):
    """
    Validated Azure OpenAI configuration for the current prototype.

    Authentication scope for this prototype is API-key only. Microsoft
    Entra ID / managed identity is a planned production improvement and
    is NOT implemented here — see the Authentication section in this
    file's module docstring-equivalent comments below and in
    docs/production_roadmap.md.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Must be an https:// Azure OpenAI resource endpoint, e.g.
    # "https://synthetic-resource.openai.azure.com/". Validated below —
    # a blank, missing, or non-https value is rejected.
    endpoint: str = Field(min_length=1)

    # The Azure OpenAI API key. Wrapped in SecretStr so it never
    # appears in logs, error messages, or accidental print()/repr()
    # calls of this settings object.
    api_key: SecretStr = Field(min_length=1)

    # The Azure OpenAI deployment to use. This is separate from the
    # endpoint and is passed straight through to
    # AzureOpenAIAnalysisProvider — it is never embedded in the base
    # URL (see src/ai/client_factory.py).
    deployment_name: str = Field(min_length=1)

    @field_validator("endpoint")
    @classmethod
    def validate_azure_openai_endpoint(cls, value: str) -> str:
        # =============================================================
        # ENDPOINT HOST VALIDATION
        # What:
        # Checks that the configured endpoint points to an expected
        # Azure OpenAI resource host (an *.openai.azure.com or
        # *.services.ai.azure.com hostname), uses https://, carries no
        # embedded credentials/query/fragment, and uses only a path
        # this project actually calls.
        #
        # Why:
        # The API key configured alongside this endpoint will later be
        # sent to whatever host is here. Restricting the hostname to
        # the project's actual Azure OpenAI resource pattern reduces
        # the risk of a configuration mistake accidentally sending the
        # credential to an unrelated, or a deliberately deceptive
        # look-alike, server (e.g. "openai.azure.com.evil.example").
        #
        # Important Notes:
        # - The actual endpoint value (the specific resource name) is
        #   always external configuration — nothing real is hard-coded
        #   here. The two suffixes below are security policy (which
        #   kinds of hosts are ever acceptable), not a project-specific
        #   resource address.
        # - Custom APIM gateways or other proxy hosts are NOT supported
        #   by this Phase 1 validation. If that is needed later, add it
        #   as an explicit, separate configuration mode — do not
        #   weaken this check to make room for it.
        # =============================================================
        parsed = urlparse(value)

        if parsed.scheme != "https":
            raise ValueError("AZURE_OPENAI_ENDPOINT must use https://")

        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT must not contain user/password "
                "information"
            )

        if parsed.query:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT must not contain a query string"
            )

        if parsed.fragment:
            raise ValueError("AZURE_OPENAI_ENDPOINT must not contain a fragment")

        # `.hostname` (unlike `.netloc`) is already lower-cased and
        # excludes any userinfo/port, so the suffix check below cannot
        # be bypassed with mixed case or a "user@" prefix. Requiring
        # the suffix to start with "." also guarantees a non-empty
        # resource-name prefix exists before it (a bare
        # "openai.azure.com" host is shorter than the suffix itself and
        # is rejected automatically), and endswith() is anchored to the
        # real end of the string, so an extra domain tacked on after
        # the expected suffix (a look-alike host) is rejected too.
        hostname = parsed.hostname
        if not hostname or not hostname.endswith(_ALLOWED_ENDPOINT_HOST_SUFFIXES):
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT host must be a resource host ending "
                "with .openai.azure.com or .services.ai.azure.com"
            )

        if parsed.path not in _ALLOWED_ENDPOINT_PATHS:
            raise ValueError(
                'AZURE_OPENAI_ENDPOINT path must be empty, "/", '
                '"/openai/v1", or "/openai/v1/"'
            )

        return value


# =====================================================================
# ENVIRONMENT LOADER
# Purpose:
# Reads the three required Azure OpenAI variable names from an
# environment-like mapping and validates them into AzureOpenAISettings.
#
# Why no automatic .env loading:
# This function reads from plain environment variables (or an injected
# mapping in tests) and never calls a .env-loading library itself. That
# keeps it working the same way in a local shell, CI/CD, a container,
# or a future cloud secret manager — all of those already know how to
# populate process environment variables. A local ".env" convenience
# loader can be added later as a separate, explicit entry point if
# needed; it must never be hidden inside this shared configuration
# function.
#
# Important Notes:
# - Only AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and
#   AZURE_OPENAI_DEPLOYMENT are read.
# - AZURE_OPENAI_API_VERSION is intentionally NOT read. The current
#   Azure OpenAI v1 client path (see client_factory.py) does not use
#   it; see .env.example for why the variable name is still kept.
# - This function never creates a .env file and never prints the
#   values it reads.
# =====================================================================
def load_azure_openai_settings(
    env: Mapping[str, str] | None = None,
) -> AzureOpenAISettings:
    """
    Loads and validates Azure OpenAI settings from an environment-like
    source.

    If `env` is not supplied, reads from the real process environment
    (os.environ). Tests should always supply an explicit `env` mapping
    instead of relying on the process environment, so tests stay
    isolated and repeatable.

    Raises a Pydantic ValidationError if a required value is missing,
    blank, or invalid — this function does not silently fall back to a
    default.
    """
    source = os.environ if env is None else env

    return AzureOpenAISettings(
        endpoint=source.get("AZURE_OPENAI_ENDPOINT", ""),
        api_key=source.get("AZURE_OPENAI_API_KEY", ""),
        deployment_name=source.get("AZURE_OPENAI_DEPLOYMENT", ""),
    )
