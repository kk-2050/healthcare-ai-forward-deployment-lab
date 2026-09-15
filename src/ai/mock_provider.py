# File Name: mock_provider.py
# Purpose: Provides a deterministic, offline test double for AIAnalysisProvider; used only by the test suite.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.ai.contracts import AIAnalysisRequest

# =====================================================================
# MOCKED / TEST DOUBLE PROVIDER
# Purpose:
# Stands in for a real AI provider during tests so the whole test suite
# can run offline, deterministically, and without any API cost.
#
# Why:
# The project needs to prove that the AI service and the LangGraph
# workflow handle success, malformed output, and provider failure
# correctly — without ever depending on a live model.
#
# Important Notes:
# - This is MOCKED / a TEST DOUBLE. It is not a live LLM implementation
#   and does not "think" or interpret text — it only returns whatever
#   response or exception the test configured ahead of time.
# - Do not add keyword heuristics or any logic here that pretends to be
#   AI reasoning; that would defeat the purpose of a deterministic test
#   double.
# =====================================================================


class MockAIAnalysisProvider:
    """
    A test-only stand-in for a real AIAnalysisProvider.

    Configure it with either `response` (the raw value analyze() should
    return) or `exception` (an error analyze() should raise), then use
    `last_request` to check what the caller sent it.
    """

    def __init__(self, response: object = None, exception: Exception | None = None):
        self._response = response
        self._exception = exception
        # Records the most recent request this mock received, so tests
        # can assert exactly what was sent to the "provider" without a
        # real network call.
        self.last_request: AIAnalysisRequest | None = None

    def analyze(self, request: AIAnalysisRequest) -> object:
        self.last_request = request

        if self._exception is not None:
            raise self._exception

        return self._response
