# File Name: provider.py
# Purpose: Defines the minimal provider interface for pluggable AI-analysis providers; no live provider implementation.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from typing import Protocol

from src.ai.contracts import AIAnalysisRequest

# =====================================================================
# AI PROVIDER PROTOCOL
# Purpose:
# Defines the one method any AI provider must implement: analyze().
#
# Why:
# Using a Protocol (structural typing) instead of a base class lets the
# rest of the project (src/ai/service.py, the LangGraph workflow) work
# with any object that has a matching analyze() method — a mocked test
# double today, a real Azure OpenAI-backed provider later — without
# changing calling code.
#
# Important Notes:
# - This file defines an interface only. No live provider (Azure
#   OpenAI or otherwise) is implemented anywhere in this project yet.
# - analyze() returns "object" on purpose: the raw, unvalidated output
#   from the provider. Validation happens separately, in
#   src/ai/service.py, so a provider can never bypass that check.
# =====================================================================


class AIAnalysisProvider(Protocol):
    def analyze(self, request: AIAnalysisRequest) -> object:
        ...
