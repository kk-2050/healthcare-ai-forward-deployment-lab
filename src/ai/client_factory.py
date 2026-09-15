# File Name: client_factory.py
# Purpose: Builds the Azure OpenAI v1 base URL and constructs the OpenAI SDK client and provider from validated settings.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from openai import OpenAI

from src.ai.azure_provider import AzureOpenAIAnalysisProvider
from src.config.settings import AzureOpenAISettings

# The Azure OpenAI v1 API path. See:
# https://learn.microsoft.com/azure/ai-services/openai (Azure OpenAI v1
# API guidance) — the OpenAI Python SDK's plain `OpenAI` client talks
# to Azure OpenAI by pointing `base_url` at "<endpoint>/openai/v1/".
# This path does not use AZURE_OPENAI_API_VERSION.
_AZURE_OPENAI_V1_SUFFIX = "/openai/v1/"


# =====================================================================
# ENDPOINT NORMALIZATION
# Purpose:
# Turns a configured Azure OpenAI endpoint into the exact base URL the
# OpenAI v1 client needs, regardless of how the endpoint was written.
#
# Why:
# Operators may reasonably type the endpoint with or without a
# trailing slash, or may have already appended "/openai/v1/"
# themselves. This function makes the result the same either way, so a
# small formatting difference in configuration can never silently
# produce a broken or duplicated URL.
#
# Important Notes:
# This function assumes the endpoint has already passed
# AzureOpenAISettings' https:// validation — it only reformats a
# string, it does not re-validate the scheme or hostname.
# =====================================================================
def build_azure_openai_base_url(endpoint: str) -> str:
    """
    Normalizes an Azure OpenAI endpoint to "<endpoint>/openai/v1/".

    Removes a trailing slash before appending the suffix, and does not
    append the suffix again if it is already present, so the result is
    the same whether or not the caller included it.
    """
    trimmed = endpoint.strip().rstrip("/")

    if trimmed.endswith("/openai/v1"):
        return trimmed + "/"

    return trimmed + _AZURE_OPENAI_V1_SUFFIX


# =====================================================================
# CLIENT FACTORY
# Purpose:
# Builds a ready-to-use OpenAI SDK client configured for Azure OpenAI's
# v1 API path, from validated settings.
#
# Why:
# This is the one place the API key is ever read out of its SecretStr
# wrapper. Keeping that in a single, small function makes it easy to
# confirm the key is never logged, printed, or otherwise exposed
# anywhere else in the project.
#
# Important Notes:
# - This function only constructs the client object. It performs no
#   network request, no DNS lookup, and no health check — the OpenAI
#   SDK does not contact the server until a request method (such as
#   responses.parse) is actually called.
# - This function never reads os.environ directly; all configuration
#   comes from the AzureOpenAISettings object it is given.
# =====================================================================
def create_azure_openai_client(settings: AzureOpenAISettings) -> OpenAI:
    """
    Creates an OpenAI SDK client pointed at the configured Azure
    OpenAI resource.

    The API key is read from settings.api_key (a SecretStr) only here,
    to pass it to the SDK constructor. No network request is made.
    """
    base_url = build_azure_openai_base_url(settings.endpoint)

    return OpenAI(
        base_url=base_url,
        api_key=settings.api_key.get_secret_value(),
    )


# =====================================================================
# PROVIDER FACTORY
# Purpose:
# A small composition root: builds the OpenAI client and wraps it in
# AzureOpenAIAnalysisProvider, ready to inject into run_ai_analysis()
# or the future live test.
#
# Why:
# This keeps "how do I get a working AIAnalysisProvider" to one
# function call, without needing a dependency-injection framework —
# consistent with how the LangGraph graph factory
# (src/workflow/graph.py) already takes its provider as a plain
# argument.
# =====================================================================
def create_azure_openai_provider(
    settings: AzureOpenAISettings,
) -> AzureOpenAIAnalysisProvider:
    """
    Builds a ready-to-use AzureOpenAIAnalysisProvider from settings.

    Combines create_azure_openai_client() with the configured
    deployment name. Performs no network request.
    """
    client = create_azure_openai_client(settings)

    return AzureOpenAIAnalysisProvider(
        client=client,
        deployment_name=settings.deployment_name,
    )
