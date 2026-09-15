# File Name: mock_provider.py
# Purpose: Provides a deterministic, offline test double for AIAnalysisProvider; used only by the test suite.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from src.ai.contracts import AIAnalysisRequest


class MockAIAnalysisProvider:
    def __init__(self, response: object = None, exception: Exception | None = None):
        self._response = response
        self._exception = exception
        self.last_request: AIAnalysisRequest | None = None

    def analyze(self, request: AIAnalysisRequest) -> object:
        self.last_request = request

        if self._exception is not None:
            raise self._exception

        return self._response
