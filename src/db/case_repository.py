# File Name: case_repository.py
# Purpose: Implements the minimal persistence-only repository for updating prior_authorization_cases status/closure fields, reading a case's durable identity fields for resume validation, and (Task 25B) fresh-case intake: client existence, intake identity, creation, and the atomic workflow-start claim.
# Creation Date: 2026-09-22
# Author: K.Kashiwagi
#
# Module Explanation:
# The smallest repository needed for Step 23C-2B2: setting
# prior_authorization_cases.case_status_code (and, when closing a case,
# closed_at_utc/closed_by/close_reason_code/close_reason_text) as part
# of an atomic Human Review decision transition. This repository is
# persistence-only and contains NO business interpretation of what a
# given Human Review outcome should mean for case state -- e.g. it has
# no knowledge that "REQUEST_MORE_INFORMATION means
# case_status_code=PENDING_INFORMATION"; that mapping lives entirely in
# src/workflow/human_review_service.py, which is the only caller
# expected to decide what values to pass here. Mirrors
# AuditRepository/HumanReviewRepository's session_factory injection and
# optional caller-owned session= pattern exactly, so it works against
# any configured engine (real SQL Server or an isolated offline SQLite
# engine in tests) with no code change.
#
# TASK 25B ADDITION -- FRESH-CASE INTAKE:
# client_exists(), get_case_intake_identity(), create_case(), and
# transition_case_status_conditionally() support src/workflow/
# case_intake_service.py's fresh-case workflow-start boundary
# (POST /workflows). These are deliberately kept separate from Task
# 24's get_case_identity()/PersistedCaseIdentity, which the resume path
# uses and which this addition must never broaden or replace --
# resume's eligibility check does not need or compare client_id, and
# fresh intake's six-field identity (including client_id) is a
# genuinely different contract for a genuinely different boundary.
#
# ATOMIC WORKFLOW-START CLAIM:
# transition_case_status_conditionally() is a race-safe conditional
# UPDATE -- the exact same design already proven in
# AuditRepository.claim_workflow_run_for_resume() (Task 24B-2/24B-4A),
# applied here to prior_authorization_cases.case_status_code instead of
# workflow_runs. It reuses the already-approved, already-loaded
# "IN_PROGRESS" case status (case_statuses, loaded since Task 22, never
# previously set by any code path) as the claim target -- no migration,
# no new reference-data value, no change to src/workflow/orchestrator.py.
# Used bidirectionally: OPEN -> IN_PROGRESS claims a case for a fresh
# workflow start; IN_PROGRESS -> OPEN reverts that claim if workflow
# startup fails before any workflow_runs row was ever created (see
# case_intake_service.py's compensation step).

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import PriorAuthorizationCaseORM
from src.models.case import PriorAuthorizationCase


class PersistenceError(Exception):
    """Raised when a repository read/write operation fails. Mirrors
    src/db/repository.py's exception of the same name and role -- never
    carries raw database driver text, which could contain configuration
    details."""


class ClientNotFoundError(Exception):
    """
    Raised when a supplied client_id does not identify an existing,
    active, non-deleted clients row (Task 25B).

    This project's clients table has no onboarding/creation path
    through this API -- a missing or inactive client is always a
    caller error, never silently created or silently treated as
    usable.
    """


class CaseAlreadyExistsError(Exception):
    """
    Raised when a fresh-intake request's case_id cannot be used for a
    new intake (Task 25B) -- the case already has at least one
    workflow_runs row, it disagrees with the request on client_id or
    another durable identity field, a concurrent request already
    claimed it, or a concurrent request already created it.

    Carries only a safe internal reason_category -- never a
    cross-client identifier or a clinical value. The HTTP layer must
    map every reason_category to the SAME fixed public message; the
    category exists for safe internal diagnosis only, never for the
    caller.
    """

    def __init__(self, reason_category: str):
        self.reason_category = reason_category
        super().__init__(
            "Case already exists and cannot be used for a new intake "
            f"(reason_category={reason_category})."
        )


@dataclass(frozen=True)
class PersistedCaseIdentity:
    """The durable identity fields prior_authorization_cases actually
    stores for one case (Step 24B-3A). Deliberately NOT the full
    PriorAuthorizationCase shape: diagnosis_code,
    supporting_documentation, and clinical_notes are never persisted
    here (data minimization, confirmed by this table's own schema --
    see docs from Step 24A/24B-1), so there is no durable value to
    expose for any of them. Used only to compare a caller-supplied case
    against what is actually stored, never to reconstruct a full case."""

    case_id: str
    member_id: str
    provider_id: str
    requested_service_code: str
    requested_date: date


@dataclass(frozen=True)
class PersistedCaseIntakeIdentity:
    """
    The durable fresh-intake identity fields for one case (Task 25B):
    case_id, client_id, member_id, provider_id, requested_service_code,
    requested_date. Used only by the fresh-intake duplicate/safe-retry
    check in src/workflow/case_intake_service.py -- never by the resume
    path, which has its own, deliberately narrower, PersistedCaseIdentity
    above (no client_id).
    """

    case_id: str
    client_id: str
    member_id: str
    provider_id: str
    requested_service_code: str
    requested_date: date


# =====================================================================
# CASE REPOSITORY
# Purpose:
# Updates a prior_authorization_cases row's status (and, when
# applicable, its closure fields) -- persistence only, no business
# decision-making.
#
# Important Notes:
# - update_case_status() is a pure field-setter: it writes exactly the
#   values it is given, with no interpretation of what those values
#   should be for a given situation.
# - CALLER-OWNED TRANSACTIONS: pass session= to participate in a
#   caller-owned shared transaction (e.g. the same one updating
#   human_reviews/workflow_runs/audit_events for one atomic Human
#   Review decision -- see src/workflow/human_review_service.py)
#   instead of this repository opening/committing its own. When session
#   is omitted, this repository opens its own session and commits or
#   rolls back within that single call, exactly like
#   AuditRepository/HumanReviewRepository's default behavior.
# =====================================================================
class CaseRepository:
    """Repository for prior_authorization_cases status/closure field
    updates."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def _resolve_session(self, session: Session | None) -> tuple[Session, bool]:
        """Returns (session, owns_session) -- identical pattern to
        AuditRepository/HumanReviewRepository's own helper of the same
        name."""
        if session is not None:
            return session, False
        return self._session_factory(), True

    def update_case_status(
        self,
        *,
        case_id: str,
        case_status_code: str,
        updated_by: str,
        updated_at_utc: datetime,
        closed_at_utc: datetime | None = None,
        closed_by: str | None = None,
        close_reason_code: str | None = None,
        close_reason_text: str | None = None,
        session: Session | None = None,
    ) -> None:
        """
        Updates one case's case_status_code, and -- only when supplied
        -- its closure fields. Raises PersistenceError if case_id does
        not exist.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                existing = active_session.get(PriorAuthorizationCaseORM, case_id)
                if existing is None:
                    raise PersistenceError(
                        "Failed to update case status (case_id not found)."
                    )

                existing.case_status_code = case_status_code
                existing.updated_at_utc = updated_at_utc
                existing.updated_by = updated_by
                if closed_at_utc is not None:
                    existing.closed_at_utc = closed_at_utc
                if closed_by is not None:
                    existing.closed_by = closed_by
                if close_reason_code is not None:
                    existing.close_reason_code = close_reason_code
                if close_reason_text is not None:
                    existing.close_reason_text = close_reason_text

                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
            except PersistenceError:
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError("Failed to update case status.") from error
        finally:
            if owns_session:
                active_session.close()

    def get_case_status_code(self, case_id: str) -> str | None:
        """Retrieves one case's current case_status_code, or None if
        the case does not exist. Read-only convenience for callers/
        tests that need to verify case state without a full case-read
        model."""
        with self._session_factory() as session:
            try:
                existing = session.get(PriorAuthorizationCaseORM, case_id)
            except SQLAlchemyError as error:
                raise PersistenceError("Failed to retrieve case.") from error

        return existing.case_status_code if existing is not None else None

    def get_case_identity(self, case_id: str) -> PersistedCaseIdentity | None:
        """
        Retrieves one case's durable identity fields (case_id,
        member_id, provider_id, requested_service_code,
        requested_date), or None if the case does not exist.

        Read-only convenience for callers (Step 24B-3A: resume
        eligibility's case-identity validation) that need to compare a
        caller-supplied PriorAuthorizationCase against exactly what is
        durably persisted -- never the full row, and never a field this
        project intentionally does not persist.
        """
        with self._session_factory() as session:
            try:
                existing = session.get(PriorAuthorizationCaseORM, case_id)
            except SQLAlchemyError as error:
                raise PersistenceError("Failed to retrieve case identity.") from error

        if existing is None:
            return None
        return PersistedCaseIdentity(
            case_id=existing.case_id,
            member_id=existing.member_id,
            provider_id=existing.provider_id,
            requested_service_code=existing.requested_service_code,
            requested_date=existing.requested_date,
        )

    # =================================================================
    # FRESH-CASE INTAKE (Task 25B)
    # Purpose:
    # Supports POST /workflows's fresh-case workflow-start boundary:
    # confirming the caller-supplied client exists, reading a case's
    # intake identity for duplicate/safe-retry comparison, creating a
    # brand-new case row, and atomically claiming/releasing an existing
    # case for workflow processing. None of these methods make any
    # business decision about what to do with the result -- that
    # belongs entirely to src/workflow/case_intake_service.py.
    # =================================================================
    def client_exists(self, client_id: str) -> bool:
        """
        Returns True only if client_id identifies an active,
        non-deleted clients row.

        clients has no SQLAlchemy ORM class (Wave 1, raw DDL only --
        see src/db/models.py's Foreign Key Policy), so this reads it
        through a parameterized text() statement, the same pattern
        src/db/reference_data.py already uses for other no-ORM-class
        Wave 1 tables -- never string-formatted SQL.
        """
        with self._session_factory() as session:
            try:
                count = session.execute(
                    text(
                        "SELECT COUNT(*) FROM clients WHERE client_id = :client_id "
                        "AND is_active = 1 AND is_deleted = 0"
                    ),
                    {"client_id": client_id},
                ).scalar_one()
            except SQLAlchemyError as error:
                raise PersistenceError("Failed to check client existence.") from error
        return count > 0

    def get_case_intake_identity(
        self, case_id: str
    ) -> PersistedCaseIntakeIdentity | None:
        """
        Retrieves one case's durable fresh-intake identity -- case_id,
        client_id, member_id, provider_id, requested_service_code,
        requested_date -- or None if the case does not exist.

        The dataclass is built while the session is still open (inside
        this method's own `with` block), so every field is read from a
        live, attached ORM instance -- not from one that has already
        been detached by the session closing.
        """
        with self._session_factory() as session:
            try:
                existing = session.get(PriorAuthorizationCaseORM, case_id)
            except SQLAlchemyError as error:
                raise PersistenceError(
                    "Failed to retrieve case intake identity."
                ) from error

            if existing is None:
                return None
            return PersistedCaseIntakeIdentity(
                case_id=existing.case_id,
                client_id=existing.client_id,
                member_id=existing.member_id,
                provider_id=existing.provider_id,
                requested_service_code=existing.requested_service_code,
                requested_date=existing.requested_date,
            )

    def create_case(
        self,
        *,
        case: PriorAuthorizationCase,
        client_id: str,
        created_by: str,
        opened_at_utc: datetime,
        session: Session | None = None,
    ) -> None:
        """
        Creates a new prior_authorization_cases row for a fresh intake,
        with case_status_code="IN_PROGRESS" -- this insertion IS the
        fresh-intake claim (see this module's docstring); the case_id
        primary key is what makes two concurrent creates for the same
        case_id impossible to both succeed.

        Failure handling distinguishes a genuine concurrent-duplicate
        race from an unrelated persistence failure by BEHAVIOR, never
        by inspecting vendor-specific SQL Server/SQLite error text:

        - An IntegrityError during the insert triggers a rollback and a
          fresh re-read of case_id. If the row now exists, this was a
          concurrent duplicate create -- raises
          CaseAlreadyExistsError("CONCURRENT_CASE_CREATION"). If it
          still does not exist, the failure was unrelated -- raises
          PersistenceError. If that re-read itself fails, this is also
          reported as PersistenceError -- never guessed as a duplicate.
        - Any other SQLAlchemyError is always reported as
          PersistenceError directly, never reinterpreted as a
          duplicate.
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                active_session.add(
                    PriorAuthorizationCaseORM(
                        case_id=case.case_id,
                        client_id=client_id,
                        department_id=None,
                        location_id=None,
                        case_status_code="IN_PROGRESS",
                        member_id=case.member_id,
                        provider_id=case.provider_id,
                        requested_service_code=case.requested_service_code,
                        requested_date=case.requested_date,
                        source_component_code="FASTAPI",
                        opened_at_utc=opened_at_utc,
                        closed_at_utc=None,
                        closed_by=None,
                        close_reason_code=None,
                        close_reason_text=None,
                        clinical_notes_present=bool(
                            case.clinical_notes and case.clinical_notes.strip()
                        ),
                        schema_version="1",
                        metadata_json=None,
                        created_at_utc=opened_at_utc,
                        created_by=created_by,
                        updated_at_utc=opened_at_utc,
                        updated_by=created_by,
                        is_deleted=False,
                        deleted_at_utc=None,
                        deleted_by=None,
                        delete_reason_code=None,
                        delete_reason_text=None,
                    )
                )
                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
            except IntegrityError as error:
                if not owns_session:
                    # A caller-owned shared session cannot be safely
                    # rolled back and re-queried here without affecting
                    # the caller's other pending work -- report plainly
                    # and let the caller manage its own transaction's
                    # fate. (No current caller passes session= to this
                    # method; case creation is always its own
                    # independently-committed write -- see
                    # src/workflow/case_intake_service.py.)
                    raise PersistenceError(
                        "Failed to create case (integrity error)."
                    ) from error
                active_session.rollback()
                try:
                    reread_exists = self.get_case_intake_identity(case.case_id)
                except PersistenceError as reread_error:
                    raise PersistenceError(
                        "Failed to create case, and the concurrency "
                        "re-check itself failed."
                    ) from reread_error
                if reread_exists is not None:
                    raise CaseAlreadyExistsError("CONCURRENT_CASE_CREATION") from error
                raise PersistenceError("Failed to create case.") from error
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError("Failed to create case.") from error
        finally:
            if owns_session:
                active_session.close()

    def transition_case_status_conditionally(
        self,
        case_id: str,
        *,
        expected_status: str,
        new_status: str,
        updated_at_utc: datetime,
        updated_by: str,
        session: Session | None = None,
    ) -> bool:
        """
        Race-safely transitions one case's case_status_code via a
        conditional UPDATE -- the exact same design as
        AuditRepository.claim_workflow_run_for_resume() (Task
        24B-2/24B-4A), applied to prior_authorization_cases instead of
        workflow_runs.

        Returns True if exactly one row was transitioned (case_id
        existed with case_status_code == expected_status at UPDATE
        time). Returns False if zero rows were affected -- the
        caller must treat this as a deterministic conflict, never
        retry silently, and never assume what the row's current state
        actually is.

        Used bidirectionally by src/workflow/case_intake_service.py:
        OPEN -> IN_PROGRESS to claim an existing case for a fresh
        workflow start; IN_PROGRESS -> OPEN to revert that claim if
        workflow startup fails before any workflow_runs row exists.

        Pass session= to participate in a caller-owned shared
        transaction instead of this repository opening/committing its
        own (see class docstring).
        """
        active_session, owns_session = self._resolve_session(session)
        try:
            try:
                result = active_session.execute(
                    text(
                        "UPDATE prior_authorization_cases "
                        "SET case_status_code = :new_status, "
                        "updated_at_utc = :updated_at_utc, "
                        "updated_by = :updated_by "
                        "WHERE case_id = :case_id "
                        "AND case_status_code = :expected_status"
                    ),
                    {
                        "new_status": new_status,
                        "updated_at_utc": updated_at_utc,
                        "updated_by": updated_by,
                        "case_id": case_id,
                        "expected_status": expected_status,
                    },
                )
                affected = result.rowcount
                if affected not in (0, 1):
                    raise PersistenceError(
                        "Case status transition affected an unexpected "
                        f"number of rows ({affected}) for case_id="
                        f"{case_id!r}; refusing to treat this as a safe "
                        "transition."
                    )
                transitioned = affected == 1
                if owns_session:
                    active_session.commit()
                else:
                    active_session.flush()
                return transitioned
            except PersistenceError:
                if owns_session:
                    active_session.rollback()
                raise
            except SQLAlchemyError as error:
                if owns_session:
                    active_session.rollback()
                raise PersistenceError(
                    "Failed to transition case status."
                ) from error
        finally:
            if owns_session:
                active_session.close()
