# File Name: test_case_intake_service.py
# Purpose: Tests src/workflow/case_intake_service.py's fresh-case client validation, duplicate/safe-retry resolution, atomic claim, and claim compensation, plus the supporting src/db/case_repository.py additions, using an in-memory SQLite test double.
# Creation Date: 2026-10-01
# Author: K.Kashiwagi
#
# Module Explanation:
# These tests protect Task 25B's fresh-case intake boundary
# (POST /workflows's application-level service). They cover both the
# service function itself (start_new_case_workflow()) and the
# repository methods it depends on (CaseRepository.client_exists(),
# get_case_intake_identity(), create_case(),
# transition_case_status_conditionally(); AuditRepository.
# case_has_workflow_run()). Every test runs against an in-memory SQLite
# engine and an offline FHIRStyleClient/MockAIAnalysisProvider -- never
# a live network call, never a live AI call. These tests do not re-prove
# run_prior_authorization_workflow()'s own graph/business logic -- that
# is already covered by tests/test_workflow_orchestrator.py. This file
# only proves the fresh-intake boundary itself: client validation, the
# six-field duplicate/safe-retry decision, the atomic IN_PROGRESS claim,
# and claim compensation.

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.workflow.orchestrator as orchestrator_module
from src.ai.mock_provider import MockAIAnalysisProvider
from src.db.base import create_database_schema
from src.db.case_repository import (
    CaseAlreadyExistsError,
    CaseRepository,
    ClientNotFoundError,
    PersistedCaseIntakeIdentity,
    PersistenceError,
)
from src.db.human_review_repository import HumanReviewRepository
from src.db.models import PriorAuthorizationCaseORM, WorkflowRunORM
from src.db.repository import AuditRepository
from src.db.repository import PersistenceError as WorkflowPersistenceError
from src.integrations.fhir_client import FHIRStyleClient
from src.models.ai import AIProcessingRequirements
from src.models.case import PriorAuthorizationCase
from src.models.rules import CompletenessRequirements
from src.workflow.case_intake_service import start_new_case_workflow
from src.workflow.orchestrator import OrchestratorError

_WORKFLOW_DEFINITION_ID = "SYN-WORKFLOW-DEF-INTAKE-001"
_CLIENT_ID = "cli_intake_test_001"
_CASE_ID = "case_intake_test_001"
_MEMBER_ID = "SYN-MEMBER-INTAKE"
_PROVIDER_ID = "SYN-PROVIDER-INTAKE"
_REQUESTED_SERVICE_CODE = "SYN-LUMBAR-MRI"
_DIAGNOSIS_CODE = "SYN-LOW-BACK-PAIN"
_REQUESTED_DATE = date(2026, 1, 15)


# =====================================================================
# FIXTURES
# =====================================================================
def make_test_engine():
    """In-memory SQLite engine; StaticPool keeps it alive across
    sessions (same convention as every other offline test here)."""
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# clients has no SQLAlchemy ORM class (Wave 1, raw DDL only -- see
# src/db/models.py's Foreign Key Policy), so create_database_schema()
# (Base.metadata.create_all()) never creates it. Mirrors the exact
# convention already established in tests/test_reference_data_loader.py
# for other no-ORM-class Wave 1 tables: a plain CREATE TABLE matching
# the real Wave 1 migration's column names/order
# (migrations/versions/c841e86a8516_create_wave_1_database_foundation.py),
# with only generic, SQLite-compatible types.
_CLIENTS_TABLE_DDL = """
    CREATE TABLE clients (
        client_id TEXT PRIMARY KEY, client_code TEXT NOT NULL,
        client_name TEXT NOT NULL, client_type_code TEXT,
        default_country_code TEXT, default_time_zone TEXT,
        is_active INTEGER NOT NULL, metadata_json TEXT,
        created_at_utc TEXT NOT NULL, created_by TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL, updated_by TEXT NOT NULL,
        is_deleted INTEGER NOT NULL
    )
"""


def make_environment():
    engine = make_test_engine()
    create_database_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(_CLIENTS_TABLE_DDL)
    session_factory = sessionmaker(bind=engine)
    return (
        engine,
        AuditRepository(session_factory=session_factory),
        HumanReviewRepository(session_factory=session_factory),
        CaseRepository(session_factory=session_factory),
    )


def insert_client(engine, client_id: str = _CLIENT_ID, *, is_active: bool = True, is_deleted: bool = False) -> None:
    """Raw SQL insert -- clients has no SQLAlchemy ORM class (Wave 1,
    raw DDL only)."""
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        from sqlalchemy import text

        session.execute(
            text(
                "INSERT INTO clients "
                "(client_id, client_code, client_name, client_type_code, "
                "default_country_code, default_time_zone, is_active, metadata_json, "
                "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
                "VALUES (:client_id, :client_code, :client_name, NULL, NULL, NULL, "
                ":is_active, NULL, :now, 'SYSTEM', :now, 'SYSTEM', :is_deleted)"
            ),
            {
                "client_id": client_id,
                "client_code": "INTAKE_TEST_CLIENT",
                "client_name": "Intake Test Client (synthetic)",
                "is_active": 1 if is_active else 0,
                "is_deleted": 1 if is_deleted else 0,
                "now": now,
            },
        )
        session.commit()


def make_case(**overrides) -> PriorAuthorizationCase:
    data = {
        "case_id": _CASE_ID,
        "member_id": _MEMBER_ID,
        "provider_id": _PROVIDER_ID,
        "requested_service_code": _REQUESTED_SERVICE_CODE,
        "diagnosis_code": _DIAGNOSIS_CODE,
        "requested_date": _REQUESTED_DATE,
    }
    data.update(overrides)
    return PriorAuthorizationCase(**data)


def make_requirements(**overrides) -> CompletenessRequirements:
    data = {"required_documentation": [], "clinical_notes_required": False}
    data.update(overrides)
    return CompletenessRequirements(**data)


def _valid_fhir_bundle_json():
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "ServiceRequest",
                    "id": "SYN-SR-INTAKE-001",
                    "status": "active",
                    "intent": "order",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _REQUESTED_SERVICE_CODE,
                                "display": "Lumbar MRI (synthetic)",
                            }
                        ]
                    },
                    "reasonReference": [{"reference": "Condition/SYN-COND-INTAKE-001"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "SYN-COND-INTAKE-001",
                    "code": {
                        "coding": [
                            {
                                "system": "http://example.org/synthetic-codes",
                                "code": _DIAGNOSIS_CODE,
                                "display": "Low back pain (synthetic)",
                            }
                        ]
                    },
                }
            },
        ],
    }


def make_success_fhir_client() -> FHIRStyleClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_valid_fhir_bundle_json())

    return FHIRStyleClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://synthetic-fhir-style.example.internal",
    )


def make_ai_provider(**kwargs) -> MockAIAnalysisProvider:
    if not kwargs:
        kwargs = {"response": {"completed_tasks": []}}
    return MockAIAnalysisProvider(**kwargs)


class _FailFirstSaveWorkflowRunRepository(AuditRepository):
    """
    Wraps a real AuditRepository, failing only its FIRST
    save_workflow_run() call -- this is run_prior_authorization_workflow()'s
    own very first write (confirmed directly from
    src/workflow/orchestrator.py: it runs before build_case_workflow_graph()
    and before graph.invoke()), so this is the genuine "workflow start
    failed before any workflow_runs row was ever created" moment the
    claim-compensation tests below need to simulate. Every later call
    (including any retry) behaves exactly like the real repository.
    """

    def __init__(self, session_factory):
        super().__init__(session_factory=session_factory)
        self._save_calls = 0

    def save_workflow_run(self, snapshot, *, session=None):
        self._save_calls += 1
        if self._save_calls == 1:
            raise WorkflowPersistenceError(
                "synthetic failure before the first workflow_runs write"
            )
        return super().save_workflow_run(snapshot, session=session)


def call_start_new_case_workflow(
    *,
    workflow_repository,
    human_review_repository,
    case_repository,
    session_factory,
    client_id=_CLIENT_ID,
    case=None,
    fhir_client=None,
):
    return start_new_case_workflow(
        client_id=client_id,
        case=case or make_case(),
        completeness_requirements=make_requirements(),
        ai_processing_requirements=AIProcessingRequirements(),
        ai_provider=make_ai_provider(),
        fhir_client=fhir_client or make_success_fhir_client(),
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=session_factory,
        workflow_definition_id=_WORKFLOW_DEFINITION_ID,
    )


# =====================================================================
# CLIENT VALIDATION TESTS
# =====================================================================
def test_active_client_accepted():
    """Verifies an active, non-deleted client allows a fresh workflow
    to start -- the baseline happy path for client validation."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)

    result = call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    assert workflow_repository.get_workflow_run(result.trace_id) is not None


def test_unknown_client_rejected():
    """Verifies a client_id with no clients row at all raises
    ClientNotFoundError, never silently creating one."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()

    with pytest.raises(ClientNotFoundError):
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )


def test_inactive_client_rejected():
    """Verifies a client that exists but is_active=0 is treated as not
    found -- a deactivated client cannot submit a new case."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine, is_active=False)

    with pytest.raises(ClientNotFoundError):
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )


def test_deleted_client_rejected():
    """Verifies a client that exists but is_deleted=1 is treated as not
    found."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine, is_deleted=True)

    with pytest.raises(ClientNotFoundError):
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )


# =====================================================================
# IDENTITY / DUPLICATE TESTS
# =====================================================================
def test_fresh_case_persisted_once():
    """Verifies a fresh case is persisted exactly once."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)

    call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with sessionmaker(bind=engine)() as session:
        count = session.query(PriorAuthorizationCaseORM).filter_by(case_id=_CASE_ID).count()
    assert count == 1


def test_intake_identity_includes_client_id():
    """Verifies get_case_intake_identity() returns client_id -- the
    field Task 24's PersistedCaseIdentity deliberately does not have."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    identity = case_repository.get_case_intake_identity(_CASE_ID)
    assert isinstance(identity, PersistedCaseIntakeIdentity)
    assert identity.client_id == _CLIENT_ID


def test_existing_case_with_workflow_run_conflicts():
    """Verifies a case that already has a workflow run cannot be used
    for a new intake, regardless of identity match."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )
    assert excinfo.value.reason_category == "EXISTING_WORKFLOW_RUN"


def test_safe_retry_claim_succeeds_when_six_fields_match():
    """Verifies an existing OPEN case with zero workflow runs and all
    six matching intake identity fields is claimed and the workflow
    starts -- the safe-retry path. The zero-run precondition is reached
    by a first call whose very first persistence write fails (so no
    workflow_runs row is ever created) and is then compensated, exactly
    like the dedicated compensation test below -- this test's own focus
    is that the resulting state is correctly treated as a safe retry."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    session_factory = sessionmaker(bind=engine)

    failing_workflow_repository = _FailFirstSaveWorkflowRunRepository(session_factory)
    with pytest.raises(WorkflowPersistenceError):
        call_start_new_case_workflow(
            workflow_repository=failing_workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=session_factory,
        )

    # Case now exists, zero workflow runs (compensation reverted the
    # claim), identity matches exactly -> safe retry.
    result = call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=session_factory,
    )
    assert workflow_repository.get_workflow_run(result.trace_id) is not None

    with sessionmaker(bind=engine)() as session:
        count = session.query(PriorAuthorizationCaseORM).filter_by(case_id=_CASE_ID).count()
    assert count == 1


def test_different_client_id_conflicts_even_with_matching_case_fields():
    """Verifies that matching the five case-identity fields is NOT
    enough if client_id differs -- a case belonging to one client must
    never be treated as another client's safe retry."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine, client_id=_CLIENT_ID)
    insert_client(engine, client_id="cli_other_client_001")
    # Insert the case directly, OPEN, zero runs, owned by _CLIENT_ID.
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID,
                client_id=_CLIENT_ID,
                case_status_code="OPEN",
                member_id=_MEMBER_ID,
                provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE,
                requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
            client_id="cli_other_client_001",
        )
    assert excinfo.value.reason_category == "IDENTITY_MISMATCH"


def test_other_durable_field_mismatch_conflicts():
    """Verifies a mismatch on a durable field other than client_id
    (here, provider_id) is also a conflict, not a safe retry."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID,
                client_id=_CLIENT_ID,
                case_status_code="OPEN",
                member_id=_MEMBER_ID,
                provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE,
                requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
            case=make_case(provider_id="SYN-PROVIDER-DIFFERENT"),
        )
    assert excinfo.value.reason_category == "IDENTITY_MISMATCH"


def test_safe_retry_never_inserts_second_case_row():
    """Verifies the safe-retry path updates the existing case's status
    in place rather than ever inserting a second row for the same
    case_id."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID,
                client_id=_CLIENT_ID,
                case_status_code="OPEN",
                member_id=_MEMBER_ID,
                provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE,
                requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI",
                opened_at_utc=now,
                created_at_utc=now,
                created_by="SYSTEM",
                updated_at_utc=now,
                updated_by="SYSTEM",
            )
        )
        session.commit()

    call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with sessionmaker(bind=engine)() as session:
        count = session.query(PriorAuthorizationCaseORM).filter_by(case_id=_CASE_ID).count()
    assert count == 1


# =====================================================================
# ATOMIC CLAIM TESTS (repository-level)
# =====================================================================
def test_conditional_claim_succeeds_once():
    """Verifies transition_case_status_conditionally() succeeds exactly
    when the expected status matches."""
    engine, _workflow_repository, _human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID, client_id=_CLIENT_ID, case_status_code="OPEN",
                member_id=_MEMBER_ID, provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE, requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI", opened_at_utc=now, created_at_utc=now,
                created_by="SYSTEM", updated_at_utc=now, updated_by="SYSTEM",
            )
        )
        session.commit()

    claimed = case_repository.transition_case_status_conditionally(
        _CASE_ID, expected_status="OPEN", new_status="IN_PROGRESS",
        updated_at_utc=now, updated_by="SYSTEM",
    )
    assert claimed is True
    assert case_repository.get_case_status_code(_CASE_ID) == "IN_PROGRESS"


def test_second_concurrent_equivalent_claim_affects_zero_rows():
    """Verifies a second claim attempt, after the first already
    succeeded, is refused (0 rows) -- simulating a concurrent duplicate
    request arriving just after the first won the race."""
    engine, _workflow_repository, _human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID, client_id=_CLIENT_ID, case_status_code="OPEN",
                member_id=_MEMBER_ID, provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE, requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI", opened_at_utc=now, created_at_utc=now,
                created_by="SYSTEM", updated_at_utc=now, updated_by="SYSTEM",
            )
        )
        session.commit()

    first = case_repository.transition_case_status_conditionally(
        _CASE_ID, expected_status="OPEN", new_status="IN_PROGRESS",
        updated_at_utc=now, updated_by="SYSTEM",
    )
    second = case_repository.transition_case_status_conditionally(
        _CASE_ID, expected_status="OPEN", new_status="IN_PROGRESS",
        updated_at_utc=now, updated_by="SYSTEM",
    )
    assert first is True
    assert second is False


def test_failed_claim_in_service_becomes_conflict():
    """Verifies that if a concurrent claim already won (simulated by
    directly stealing the claim before the service's own attempt), the
    service reports CaseAlreadyExistsError, never a silent retry or a
    second run."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID, client_id=_CLIENT_ID, case_status_code="OPEN",
                member_id=_MEMBER_ID, provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE, requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI", opened_at_utc=now, created_at_utc=now,
                created_by="SYSTEM", updated_at_utc=now, updated_by="SYSTEM",
            )
        )
        session.commit()

    # A concurrent request "wins" by claiming first.
    case_repository.transition_case_status_conditionally(
        _CASE_ID, expected_status="OPEN", new_status="IN_PROGRESS",
        updated_at_utc=now, updated_by="CONCURRENT_REQUEST",
    )

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )
    assert excinfo.value.reason_category == "CASE_CLAIM_CONFLICT"


def test_no_two_calls_can_both_proceed_after_same_persisted_claim():
    """Verifies the end-to-end guarantee: once one start_new_case_workflow()
    call has claimed+started a case's workflow, a second call for the
    same case can never also proceed -- it sees the resulting
    workflow_runs row and conflicts."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)

    call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=sessionmaker(bind=engine),
    )

    with pytest.raises(CaseAlreadyExistsError):
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    with sessionmaker(bind=engine)() as session:
        run_count = session.query(WorkflowRunORM).filter_by(case_id=_CASE_ID).count()
    assert run_count == 1


# =====================================================================
# COMPENSATION TESTS
# =====================================================================
def test_claim_reverted_when_workflow_start_fails_before_any_run_created():
    """
    Verifies that if workflow startup fails before any workflow_runs
    row is created, the case's IN_PROGRESS claim is reverted to OPEN --
    and an identical retry afterward succeeds.

    run_prior_authorization_workflow()'s own first write is
    repository.save_workflow_run() (confirmed directly in
    src/workflow/orchestrator.py: it runs before build_case_workflow_graph()
    and before graph.invoke()) -- so that call failing is the genuine
    "before any workflow_runs row was ever created" moment, simulated
    here via _FailFirstSaveWorkflowRunRepository rather than a failure
    injected later in the call (which would already have a row).
    """
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)
    session_factory = sessionmaker(bind=engine)

    failing_workflow_repository = _FailFirstSaveWorkflowRunRepository(session_factory)
    with pytest.raises(WorkflowPersistenceError):
        call_start_new_case_workflow(
            workflow_repository=failing_workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=session_factory,
        )

    # Case remains persisted, reverted back to OPEN, zero runs.
    assert case_repository.get_case_status_code(_CASE_ID) == "OPEN"
    assert workflow_repository.case_has_workflow_run(_CASE_ID) is False

    result = call_start_new_case_workflow(
        workflow_repository=workflow_repository,
        human_review_repository=human_review_repository,
        case_repository=case_repository,
        session_factory=session_factory,
    )
    assert workflow_repository.get_workflow_run(result.trace_id) is not None


def test_claim_not_reverted_when_a_run_already_exists(monkeypatch):
    """Verifies that once run_prior_authorization_workflow() has
    created a workflow_runs row (even a FAILED one), a later failure
    inside that same call never reverts the claim -- the case keeps its
    real history, and a later fresh-intake attempt must conflict.

    The case_status_code the orchestrator itself resolves the FAILED
    disposition to (OPEN, per the Task 25B-1 lifecycle correction) is a
    SEPARATE fact from "was the claim reverted": case_has_workflow_run()
    -- not case_status_code -- is what case_intake_service.py's
    compensation step and duplicate check actually key off, so this
    OPEN value is not itself evidence the claim was reverted."""
    engine, workflow_repository, human_review_repository, case_repository = make_environment()
    insert_client(engine)

    class _RaisingGraph:
        def invoke(self, state):
            raise RuntimeError("synthetic graph invocation failure")

    monkeypatch.setattr(
        orchestrator_module, "build_case_workflow_graph", lambda *a, **k: _RaisingGraph()
    )

    with pytest.raises(OrchestratorError):
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )

    # A workflow_runs row was created (marked FAILED by the
    # orchestrator's own existing safety net) before the failure -- the
    # claim must NOT be reverted. The orchestrator's own FAILED
    # disposition handling (Task 25B-1) resolves case_status_code to
    # OPEN itself (the case is not clinically closed by a technical
    # failure); this is a genuine, correct case-status write, not a
    # claim reversion -- case_has_workflow_run() being True is what
    # actually proves the claim was not reverted.
    assert workflow_repository.case_has_workflow_run(_CASE_ID) is True
    assert case_repository.get_case_status_code(_CASE_ID) == "OPEN"

    monkeypatch.undo()

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        call_start_new_case_workflow(
            workflow_repository=workflow_repository,
            human_review_repository=human_review_repository,
            case_repository=case_repository,
            session_factory=sessionmaker(bind=engine),
        )
    assert excinfo.value.reason_category == "EXISTING_WORKFLOW_RUN"


# =====================================================================
# CONCURRENT CASE-CREATION RACE TESTS (repository-level, create_case())
# =====================================================================
def test_integrity_error_with_row_now_existing_is_concurrent_duplicate():
    """Verifies that if create_case()'s own INSERT hits an
    IntegrityError and the case now genuinely exists (simulated here by
    a real pre-existing row with the same case_id), this is classified
    as CONCURRENT_CASE_CREATION, never a generic persistence failure."""
    engine, _workflow_repository, _human_review_repository, case_repository = make_environment()
    insert_client(engine)
    now = datetime.now(timezone.utc)
    with sessionmaker(bind=engine)() as session:
        session.add(
            PriorAuthorizationCaseORM(
                case_id=_CASE_ID, client_id=_CLIENT_ID, case_status_code="IN_PROGRESS",
                member_id=_MEMBER_ID, provider_id=_PROVIDER_ID,
                requested_service_code=_REQUESTED_SERVICE_CODE, requested_date=_REQUESTED_DATE,
                source_component_code="FASTAPI", opened_at_utc=now, created_at_utc=now,
                created_by="SYSTEM", updated_at_utc=now, updated_by="SYSTEM",
            )
        )
        session.commit()

    with pytest.raises(CaseAlreadyExistsError) as excinfo:
        case_repository.create_case(
            case=make_case(), client_id=_CLIENT_ID, created_by="SYSTEM", opened_at_utc=now
        )
    assert excinfo.value.reason_category == "CONCURRENT_CASE_CREATION"


def test_non_integrity_sqlalchemy_error_raises_persistence_error_directly():
    """Verifies a non-IntegrityError SQLAlchemyError during create_case()
    is always reported as PersistenceError directly -- never
    reinterpreted as a duplicate."""
    engine, _workflow_repository, _human_review_repository, _case_repository = make_environment()
    insert_client(engine)
    real_session_factory = sessionmaker(bind=engine)

    class _CommitFailsSession:
        def __init__(self, real_session):
            self._real = real_session

        def add(self, obj):
            self._real.add(obj)

        def commit(self):
            raise SQLAlchemyError("synthetic non-integrity failure")

        def rollback(self):
            self._real.rollback()

        def close(self):
            self._real.close()

        def get(self, *args, **kwargs):
            return self._real.get(*args, **kwargs)

    def failing_session_factory():
        return _CommitFailsSession(real_session_factory())

    failing_case_repository = CaseRepository(session_factory=failing_session_factory)

    with pytest.raises(PersistenceError):
        failing_case_repository.create_case(
            case=make_case(),
            client_id=_CLIENT_ID,
            created_by="SYSTEM",
            opened_at_utc=datetime.now(timezone.utc),
        )


def test_integrity_error_reread_failure_raises_persistence_error():
    """Verifies that if create_case()'s own INSERT hits an
    IntegrityError and the subsequent concurrency re-check itself fails,
    this is reported as PersistenceError -- never guessed as a
    duplicate, since whether the case actually exists could not be
    confirmed."""
    engine, _workflow_repository, _human_review_repository, _case_repository = make_environment()
    insert_client(engine)
    real_session_factory = sessionmaker(bind=engine)
    call_count = {"n": 0}

    class _IntegrityThenGetFailsSession:
        def __init__(self, real_session, raise_integrity: bool):
            self._real = real_session
            self._raise_integrity = raise_integrity

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()
            return False

        def add(self, obj):
            self._real.add(obj)

        def commit(self):
            if self._raise_integrity:
                raise IntegrityError("stmt", {}, Exception("synthetic PK violation"))
            self._real.commit()

        def rollback(self):
            self._real.rollback()

        def close(self):
            self._real.close()

        def get(self, *args, **kwargs):
            raise SQLAlchemyError("synthetic reread failure")

    def failing_session_factory():
        call_count["n"] += 1
        return _IntegrityThenGetFailsSession(real_session_factory(), raise_integrity=call_count["n"] == 1)

    failing_case_repository = CaseRepository(session_factory=failing_session_factory)

    with pytest.raises(PersistenceError):
        failing_case_repository.create_case(
            case=make_case(),
            client_id=_CLIENT_ID,
            created_by="SYSTEM",
            opened_at_utc=datetime.now(timezone.utc),
        )
