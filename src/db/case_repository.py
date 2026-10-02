# File Name: case_repository.py
# Purpose: Implements the minimal persistence-only repository for updating prior_authorization_cases status/closure fields, and for reading a case's durable identity fields (Step 24B-3A) for resume validation.
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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import PriorAuthorizationCaseORM


class PersistenceError(Exception):
    """Raised when a repository read/write operation fails. Mirrors
    src/db/repository.py's exception of the same name and role -- never
    carries raw database driver text, which could contain configuration
    details."""


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
