# File Name: test_azure_provider.py
# Purpose: Tests the Azure OpenAI provider adapter offline using a fake SDK-boundary client only.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect AzureOpenAIAnalysisProvider — the adapter that
# will eventually call Azure OpenAI's Responses API. No test here makes
# a live network call. Instead, every test injects a small fake client
# that only mimics the shape of `client.responses.parse(...)`. This
# fake is an SDK-boundary test double (it stands in for the OpenAI
# Python SDK object itself), which is a different, lower-level thing
# than MockAIAnalysisProvider (an application-level AIAnalysisProvider
# test double used elsewhere in the project) — this file does not
# create another one of those.

import inspect

import pytest
from pydantic import ValidationError

from src.ai import azure_provider
from src.ai.azure_provider import AzureOpenAIAnalysisProvider
from src.ai.contracts import AIAnalysisRequest, AIAnalysisResult
from src.ai.service import run_ai_analysis
from src.models.ai import AITask


# =====================================================================
# FAKE SDK CLIENT (OFFLINE TEST DOUBLE)
# Purpose:
# Stands in for the real OpenAI/Azure OpenAI client so tests can run
# without any network access or credentials.
# =====================================================================
class _FakeParsedResponse:
    """Mimics the small part of the SDK's ParsedResponse this project
    actually uses: the `output_parsed` attribute."""

    def __init__(self, output_parsed):
        self.output_parsed = output_parsed


class _FakeResponsesResource:
    """
    Mimics `client.responses` well enough to test the adapter.

    Records every call to `.parse(...)` (arguments and a running call
    count) and returns a configured `_FakeParsedResponse`, or raises a
    configured exception instead, so tests can trigger both the
    success and failure paths without a real API.
    """

    def __init__(self, output_parsed=None, exception: Exception | None = None):
        self._output_parsed = output_parsed
        self._exception = exception
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)

        if self._exception is not None:
            raise self._exception

        return _FakeParsedResponse(self._output_parsed)


class _FakeOpenAIClient:
    """A minimal stand-in for an OpenAI-compatible client object,
    exposing only the `.responses` resource this adapter uses."""

    def __init__(self, output_parsed=None, exception: Exception | None = None):
        self.responses = _FakeResponsesResource(
            output_parsed=output_parsed, exception=exception
        )


def make_request(**overrides):
    """A minimal, fully valid synthetic AIAnalysisRequest."""
    data = {
        "case_id": "SYN-CASE-001",
        "tasks": [AITask.SUMMARIZE_NARRATIVE],
        "clinical_notes": "SYN-NOTE-001: synthetic narrative for testing only.",
    }
    data.update(overrides)
    return AIAnalysisRequest(**data)


# =====================================================================
# REQUEST-SHAPE TESTS
# =====================================================================
def test_provider_calls_parse_exactly_once():
    """Verify one analyze() call results in exactly one
    responses.parse() call — no retries or duplicate calls hidden in
    this adapter."""
    # TEST-008A
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(make_request())

    assert len(client.responses.calls) == 1


def test_deployment_name_is_passed_as_model():
    """Verify the externally supplied deployment name is sent as the
    `model` argument, proving the deployment is injected, not
    hard-coded."""
    # TEST-008B
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-002")

    provider.analyze(make_request())

    assert client.responses.calls[0]["model"] == "SYN-DEPLOYMENT-002"


def test_ai_analysis_result_is_passed_as_text_format():
    """Verify AIAnalysisResult (the project's existing output contract)
    is passed as text_format, not a duplicate schema."""
    # TEST-008C
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(make_request())

    assert client.responses.calls[0]["text_format"] is AIAnalysisResult


# =====================================================================
# MINIMUM-NECESSARY INPUT TESTS
# =====================================================================
def test_requested_tasks_are_included_in_model_input():
    """Verify the requested AITask values appear in the model input, so
    the model knows what work to do."""
    # TEST-008D
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.IDENTIFY_AMBIGUITY])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(make_request(tasks=[AITask.IDENTIFY_AMBIGUITY]))

    sent_input = client.responses.calls[0]["input"]
    assert AITask.IDENTIFY_AMBIGUITY.value in sent_input


def test_clinical_notes_are_included_in_model_input():
    """Verify the clinical notes text is included in the model input,
    since that is the data the requested tasks analyze."""
    # TEST-008E
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(make_request(clinical_notes="SYN-NOTE-UNIQUE-MARKER-001"))

    sent_input = client.responses.calls[0]["input"]
    assert "SYN-NOTE-UNIQUE-MARKER-001" in sent_input


def test_case_id_is_not_included_in_model_input():
    """
    Verify that workflow trace metadata is not included in the model
    input because the AI does not need it for language analysis.
    """
    # TEST-008F
    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(make_request(case_id="SYN-CASE-DO-NOT-SEND"))

    sent_input = client.responses.calls[0]["input"]
    assert "SYN-CASE-DO-NOT-SEND" not in sent_input


def test_unrelated_case_identifiers_cannot_be_sent():
    """Verify AIAnalysisRequest itself has no member_id, provider_id,
    or other case identifiers — so the adapter has no way to send them
    even by mistake, because they simply do not exist on the request."""
    # TEST-008G
    assert set(AIAnalysisRequest.model_fields.keys()) == {
        "case_id",
        "tasks",
        "clinical_notes",
    }


# =====================================================================
# OUTPUT / SAFETY BOUNDARY TESTS
# =====================================================================
def test_provider_returns_the_structured_output_parsed_result():
    """Verify analyze() returns exactly what the SDK's output_parsed
    contained, unchanged."""
    # TEST-008H
    expected_result = AIAnalysisResult(
        completed_tasks=[AITask.SUMMARIZE_NARRATIVE],
        summary="SYN-SUMMARY-AZURE-001",
    )
    client = _FakeOpenAIClient(output_parsed=expected_result)
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    result = provider.analyze(make_request())

    assert result is expected_result


def test_provider_does_not_mutate_request():
    """Verify calling analyze() never modifies the AIAnalysisRequest it
    was given."""
    # TEST-008I
    request = make_request(tasks=[AITask.SUMMARIZE_NARRATIVE])
    original_tasks = list(request.tasks)
    original_notes = request.clinical_notes

    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    provider.analyze(request)

    assert request.tasks == original_tasks
    assert request.clinical_notes == original_notes


def test_sdk_exception_propagates_from_provider():
    """Verify a client/SDK exception is allowed to propagate out of
    analyze() rather than being swallowed here — run_ai_analysis() is
    responsible for turning it into a safe PROVIDER_FAILED outcome."""
    # TEST-008J
    client = _FakeOpenAIClient(exception=RuntimeError("synthetic SDK failure"))
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    with pytest.raises(RuntimeError):
        provider.analyze(make_request())


# =====================================================================
# SOURCE-LEVEL SECURITY TESTS
# =====================================================================
def test_provider_source_has_no_embedded_credentials():
    """Verify the adapter's source code never contains an API key,
    token, or other credential literal — credentials must always come
    from an injected, already-configured client."""
    # TEST-008K
    source = inspect.getsource(azure_provider)
    forbidden_markers = [
        "api_key",
        "API_KEY",
        "sk-",
        "Bearer ",
        "os.environ",
        "os.getenv",
        ".env",
    ]
    for marker in forbidden_markers:
        assert marker not in source


def test_provider_source_has_no_hard_coded_azure_endpoint():
    """Verify the adapter's source code never embeds an Azure endpoint
    URL — the endpoint belongs to client construction, a future task."""
    # TEST-008L
    source = inspect.getsource(azure_provider)
    forbidden_markers = ["https://", ".azure.com", ".openai.azure.com"]
    for marker in forbidden_markers:
        assert marker not in source


def test_provider_source_has_no_hard_coded_deployment_value():
    """Verify deployment_name has no default value in the constructor —
    a caller must always supply it, so no deployment name can be
    silently baked into this file."""
    # TEST-008M
    signature = inspect.signature(AzureOpenAIAnalysisProvider.__init__)
    deployment_parameter = signature.parameters["deployment_name"]
    assert deployment_parameter.default is inspect.Parameter.empty

    source = inspect.getsource(azure_provider)
    forbidden_markers = ["gpt-4", "gpt-35", "gpt-3.5", "text-davinci"]
    for marker in forbidden_markers:
        assert marker not in source


def test_instructions_prohibit_autonomous_decisions_and_invention():
    """Verify the fixed model instructions explicitly forbid autonomous
    approval/denial and inventing clinical facts or payer policy — the
    same human-in-the-loop boundary enforced everywhere else in the
    project."""
    # TEST-008N
    instructions = azure_provider._MODEL_INSTRUCTIONS.lower()

    assert "not independently approve" in instructions
    assert "not independently deny" in instructions
    assert "not invent missing clinical facts" in instructions
    assert "not invent payer policy" in instructions


def test_only_validated_ai_task_values_can_reach_the_request():
    """Verify an unsupported task name never reaches this adapter at
    all — AIAnalysisRequest already rejects it before analyze() could
    ever be called, and the tasks that do reach the model input are
    genuine AITask enum members."""
    # TEST-008O
    with pytest.raises(ValidationError):
        AIAnalysisRequest(case_id="SYN-CASE-001", tasks=["not_a_real_task"])

    client = _FakeOpenAIClient(
        output_parsed=AIAnalysisResult(completed_tasks=[AITask.SUMMARIZE_NARRATIVE])
    )
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")
    request = make_request(tasks=[AITask.SUMMARIZE_NARRATIVE])

    provider.analyze(request)

    assert all(isinstance(task, AITask) for task in request.tasks)


# =====================================================================
# OFFLINE INTEGRATION TEST
# =====================================================================
def test_azure_provider_success_flows_through_run_ai_analysis():
    """Verify AzureOpenAIAnalysisProvider works as a drop-in
    AIAnalysisProvider for run_ai_analysis() end to end, offline —
    proving the adapter is compatible with the existing service without
    any workflow or contract changes."""
    expected_result = AIAnalysisResult(
        completed_tasks=[AITask.SUMMARIZE_NARRATIVE],
        summary="SYN-SUMMARY-AZURE-INTEGRATION-001",
    )
    client = _FakeOpenAIClient(output_parsed=expected_result)
    provider = AzureOpenAIAnalysisProvider(client=client, deployment_name="SYN-DEPLOYMENT-001")

    outcome = run_ai_analysis(make_request(), provider)

    assert outcome.success is True
    assert outcome.result.summary == "SYN-SUMMARY-AZURE-INTEGRATION-001"
