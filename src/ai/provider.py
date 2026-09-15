# File Name: provider.py
# Purpose: Defines the minimal provider interface for pluggable AI-analysis providers; no live provider implementation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from typing import Protocol

from src.ai.contracts import AIAnalysisRequest


class AIAnalysisProvider(Protocol):
    def analyze(self, request: AIAnalysisRequest) -> object:
        ...
