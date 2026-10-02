# File Name: dependencies.py
# Purpose: Builds the SQL Server session factory, repository instances, AI provider, and FHIR-style client the API layer injects into endpoints.
# Creation Date: 2026-09-24
# Author: K.Kashiwagi
#
# Module Explanation:
# Before Task 23C-7A, src/api/app.py's one endpoint (/cases/validate)
# never touched a database at all. This is the first API-layer database
# wiring in the project, added only because POST /human-review/decisions
# needs it. It reuses the exact same secure configuration chain already
# used everywhere else in this project (src/db/reference_data.py's
# _run_from_cli(), tests/test_workflow_orchestrator_integration.py):
# load_dotenv -> load_database_settings -> create_sql_server_engine --
# never a second connection-string implementation, and the connection
# string is never read anywhere in this file itself (that happens
# exactly once, inside src/db/engine.py).
#
# FastAPI dependency-injection pattern:
# get_session_factory() builds the engine/sessionmaker exactly once per
# process (functools.lru_cache) rather than per request -- opening a new
# SQL Server connection pool on every request would be wasteful and is
# not how SQLAlchemy engines are meant to be used. The repository
# dependency functions below each take that same cached session_factory,
# so every repository used by one request shares the same underlying
# engine. Tests override get_session_factory via
# app.dependency_overrides (see tests/test_api_human_review_decisions.py)
# to point at an isolated offline SQLite engine instead -- no real SQL
# Server connection is ever made by ordinary pytest.
#
# AI PROVIDER DEPENDENCY (Task 24B-4C):
# get_ai_provider() reuses the existing, already-approved Azure OpenAI
# configuration/factory chain (src/config/settings.py's
# load_azure_openai_settings(), src/ai/client_factory.py's
# create_azure_openai_provider()) unchanged -- this is not a second AI
# construction path. Cached exactly like get_session_factory(), for the
# same reason (building an SDK client once per process, not per
# request). Tests override it with MockAIAnalysisProvider, exactly like
# every other AI-touching test in this project already does.
#
# FHIR CLIENT DEPENDENCY -- FAIL-CLOSED BY DESIGN (Task 24B-4C):
# get_fhir_client() intentionally has NO working default implementation.
# FHIRStyleClient (src/integrations/fhir_client.py) accepts only
# http_client/base_url and has no authentication/token/header mechanism
# at all today, and this project has no approved, authenticated FHIR
# integration contract yet (confirmed by Task 24B-4B's contract review:
# zero production construction sites anywhere before this task). Per
# the Universal Least-Privilege Escalation Boundary (docs/security.md
# Section 7 / CLAUDE.md: "Not explicitly allowed = DENY"), constructing
# a live, unauthenticated outbound FHIR client by default here would
# silently create exactly the kind of unapproved integration that rule
# forbids. get_fhir_client() therefore always raises
# FHIRIntegrationNotConfiguredError -- every real request to
# POST /workflows/{trace_id}/resume that reaches this dependency without
# an override fails closed, safely, before any outbound call is ever
# attempted (see src/api/app.py's exception handler for how this is
# reported over HTTP). Tests override it via app.dependency_overrides
# with an offline FHIRStyleClient backed by httpx.MockTransport (see
# tests/test_api_workflow_resume.py) -- never a live network call.
# Implementing a real, authenticated default is future work (Phase 2 /
# productionization) and is explicitly NOT done here.
# =====================================================================

from collections.abc import Callable
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from src.ai.client_factory import create_azure_openai_provider
from src.ai.provider import AIAnalysisProvider
from src.config.database import load_database_settings
from src.config.settings import load_azure_openai_settings
from src.db.case_repository import CaseRepository
from src.db.engine import create_sql_server_engine
from src.db.human_review_repository import HumanReviewRepository
from src.db.repository import AuditRepository
from src.integrations.fhir_client import FHIRStyleClient


class FHIRIntegrationNotConfiguredError(Exception):
    """Raised by get_fhir_client() below -- there is no approved,
    authenticated FHIR integration contract yet, so this dependency
    fails closed by design rather than constructing an unauthenticated
    live client. See this module's docstring above."""


@lru_cache(maxsize=1)
def get_session_factory() -> Callable[[], Session]:
    """Builds (once) the sessionmaker bound to the real configured SQL
    Server engine. Overridden in tests -- see module docstring."""
    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    return sessionmaker(bind=engine)


# Every repository dependency below declares its session_factory
# parameter as Depends(get_session_factory) rather than a plain default
# argument -- this is what lets a single
# app.dependency_overrides[get_session_factory] = ... in tests correctly
# cascade to every repository built from it, per FastAPI's own
# dependency-resolution rules. A plain default argument would not
# participate in that override mechanism.
def get_workflow_repository(
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> AuditRepository:
    """Builds an AuditRepository bound to the resolved session_factory."""
    return AuditRepository(session_factory=session_factory)


def get_human_review_repository(
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> HumanReviewRepository:
    """Builds a HumanReviewRepository bound to the resolved
    session_factory."""
    return HumanReviewRepository(session_factory=session_factory)


def get_case_repository(
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> CaseRepository:
    """Builds a CaseRepository bound to the resolved session_factory."""
    return CaseRepository(session_factory=session_factory)


@lru_cache(maxsize=1)
def get_ai_provider() -> AIAnalysisProvider:
    """
    Builds (once) the real AI provider from the existing, already-
    approved Azure OpenAI settings/factory chain -- reuses
    load_azure_openai_settings() (src/config/settings.py) and
    create_azure_openai_provider() (src/ai/client_factory.py) exactly
    as they already exist; this is not a second AI construction path.

    Cached exactly like get_session_factory() above, for the same
    reason: building the underlying SDK client once per process, not
    once per request. Overridden in tests with MockAIAnalysisProvider
    (see tests/test_api_workflow_resume.py) -- no real Azure OpenAI
    call is ever made by ordinary pytest.
    """
    load_dotenv()
    settings = load_azure_openai_settings()
    return create_azure_openai_provider(settings)


def get_fhir_client() -> FHIRStyleClient:
    """
    Default FHIR-style client dependency -- INTENTIONALLY NOT
    IMPLEMENTED. Always raises FHIRIntegrationNotConfiguredError.

    FHIRStyleClient (src/integrations/fhir_client.py) accepts only
    http_client/base_url and has no authentication/token/header
    mechanism today, and this project has no approved, authenticated
    FHIR integration contract yet (Task 24B-4B's contract review found
    zero production construction sites anywhere). Constructing a live
    client here -- even from a configured base_url -- would silently
    enable unauthenticated outbound healthcare-integration traffic,
    which the Universal Least-Privilege Escalation Boundary
    (docs/security.md Section 7 / CLAUDE.md: "Not explicitly allowed =
    DENY") forbids. This dependency therefore fails closed: every real
    request to POST /workflows/{trace_id}/resume that reaches this
    dependency without an override raises immediately, before any
    outbound call is attempted, and before resume_workflow() ever runs.

    Tests override this via
    app.dependency_overrides[get_fhir_client] = ... with an offline
    FHIRStyleClient backed by httpx.MockTransport (see
    tests/test_api_workflow_resume.py) -- FastAPI's dependency_overrides
    mechanism replaces this callable entirely for the life of the
    override, so the override's own return value is used and this
    function's body never runs in those tests.

    Implementing a real, authenticated default (once an approved
    integration contract exists) is future work (Phase 2 /
    productionization) and is explicitly NOT done here.
    """
    raise FHIRIntegrationNotConfiguredError(
        "Live FHIR-style integration is not yet implemented for this "
        "endpoint -- no approved, authenticated FHIR integration "
        "contract exists yet (see Task 24B-4B's contract review)."
    )
