# File Name: setup_demo_client.py
# Purpose: Explicit, idempotent, operator-run local setup script that creates the one canonical synthetic demo client row needed for a local Streamlit/FastAPI demo.
# Creation Date: 2026-10-04
# Author: K.Kashiwagi
#
# Module Explanation:
# POST /workflows requires an existing, active, non-deleted client_id
# (src/workflow/case_intake_service.py's client validation), but
# src/db/reference_data.py deliberately never creates a clients row --
# see that module's own docstring: "never add a client/case/business
# row to it." A durable demo client therefore does not exist in a
# freshly migrated real local SQL Server database by default. This
# script is the one explicit place that gap is closed, for local
# development/demo use only.
#
# THIS SCRIPT IS NEVER CALLED AUTOMATICALLY:
# Not by FastAPI startup, not by Streamlit, not by
# src/db/reference_data.py, not by a migration. It is run manually, by
# an operator's own explicit choice, exactly like every other
# live-database action in this project (see CLAUDE.md's review-then-
# approve discipline). Running it is a setup prerequisite, not
# application runtime behavior.
#
# CANONICAL SYNTHETIC IDENTITY:
# client_id="cli_demo_001", client_code="DEMO_HEALTH",
# client_name="Demo Health Plan" -- reusing the exact example already
# documented (but never loaded) in docs/database/reference_data.md
# Section 2, rather than inventing a new synthetic name. No real
# person, company, or PHI/PII value of any kind.
#
# IDEMPOTENCY / CONFLICT CONTRACT (see ensure_demo_client() below):
# "The client_id already exists" is NOT by itself treated as success --
# an existing row at that client_id is only idempotent success if its
# durable fields (client_code, client_name, is_active, is_deleted)
# exactly match the canonical values. Any mismatch, or a client_code
# collision under a DIFFERENT client_id, is reported as a conflict and
# never written to -- this script never UPDATEs an existing client to
# force a match, and never silently overwrites one.
#
# SAFE ERROR OUTPUT:
# No connection string, SQL statement text, DB host, constraint name,
# traceback, credential, or raw driver/IntegrityError message is ever
# printed by this script -- only the fixed, safe outcome messages
# below. A concurrent-insert IntegrityError is caught, the transaction
# is rolled back, and the row is re-read to decide canonical-match vs.
# conflict by BEHAVIOR, never by parsing vendor-specific error text --
# the same discipline already established in
# src/db/case_repository.py's create_case().

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

_CANONICAL_CLIENT_ID = "cli_demo_001"
_CANONICAL_CLIENT_CODE = "DEMO_HEALTH"
_CANONICAL_CLIENT_NAME = "Demo Health Plan"
_CANONICAL_IS_ACTIVE = True


class DemoClientSetupOutcome(Enum):
    """The possible results of ensure_demo_client() -- never inferred
    from raw driver/exception text, always determined by comparing
    actual row data against the canonical identity above."""

    INSERTED = "INSERTED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class DemoClientSetupResult:
    """outcome is the machine-readable result; message is always a
    fixed, safe, operator-facing string -- never raw SQL/driver text."""

    outcome: DemoClientSetupOutcome
    message: str


def _fetch_client_by_id(session: Session, client_id: str) -> dict | None:
    """Reads the canonical-comparable fields for one client_id, or
    None if it does not exist. Parameterized raw SQL -- clients has no
    SQLAlchemy ORM class (Wave 1, raw DDL only)."""
    row = session.execute(
        text(
            "SELECT client_id, client_code, client_name, is_active, is_deleted "
            "FROM clients WHERE client_id = :client_id"
        ),
        {"client_id": client_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def _fetch_client_by_code(session: Session, client_code: str) -> dict | None:
    """Reads the canonical-comparable fields for whichever client_id
    (if any) currently owns this client_code -- used to detect a
    client_code collision under a different client_id."""
    row = session.execute(
        text(
            "SELECT client_id, client_code, client_name, is_active, is_deleted "
            "FROM clients WHERE client_code = :client_code"
        ),
        {"client_code": client_code},
    ).mappings().first()
    return dict(row) if row is not None else None


def _matches_canonical_identity(row: dict) -> bool:
    """True only if every durable identity/status field exactly
    matches the canonical demo client -- never a partial match."""
    return (
        row["client_id"] == _CANONICAL_CLIENT_ID
        and row["client_code"] == _CANONICAL_CLIENT_CODE
        and row["client_name"] == _CANONICAL_CLIENT_NAME
        and bool(row["is_active"]) == _CANONICAL_IS_ACTIVE
        and bool(row["is_deleted"]) is False
    )


def _insert_canonical_client(session: Session, now: datetime) -> None:
    """Inserts the one canonical synthetic demo client row. Raises
    IntegrityError on a concurrent duplicate -- the caller (see
    ensure_demo_client() below) is responsible for handling that, never
    this function."""
    session.execute(
        text(
            "INSERT INTO clients "
            "(client_id, client_code, client_name, client_type_code, "
            "default_country_code, default_time_zone, is_active, metadata_json, "
            "created_at_utc, created_by, updated_at_utc, updated_by, is_deleted) "
            "VALUES (:client_id, :client_code, :client_name, NULL, NULL, NULL, "
            "1, NULL, :now, 'SYSTEM', :now, 'SYSTEM', 0)"
        ),
        {
            "client_id": _CANONICAL_CLIENT_ID,
            "client_code": _CANONICAL_CLIENT_CODE,
            "client_name": _CANONICAL_CLIENT_NAME,
            "now": now,
        },
    )


# =====================================================================
# ENSURE DEMO CLIENT
# Purpose:
# Implements the full idempotency/conflict contract: insert the
# canonical demo client if and only if doing so cannot silently hide
# or overwrite a different existing row.
#
# Contract (see module docstring for the full rationale):
#   1. No row matches client_id or client_code -> insert, INSERTED.
#   2. A row exists at the canonical client_id and matches every
#      canonical field exactly -> ALREADY_PRESENT, no write.
#   3. A row exists at the canonical client_id but differs in any
#      canonical field -> CONFLICT, no write.
#   4. No row at the canonical client_id, but client_code already
#      belongs to a different client_id -> CONFLICT, no write.
#   5. A concurrent insert races this one (IntegrityError): roll back,
#      re-read by client_id, and resolve by the SAME rules above --
#      never by parsing the raw error text.
# This function never UPDATEs an existing row under any circumstance.
# =====================================================================
def ensure_demo_client(
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
) -> DemoClientSetupResult:
    now = now or datetime.now(timezone.utc)

    with session_factory() as session:
        try:
            existing_by_id = _fetch_client_by_id(session, _CANONICAL_CLIENT_ID)
            if existing_by_id is not None:
                if _matches_canonical_identity(existing_by_id):
                    return DemoClientSetupResult(
                        DemoClientSetupOutcome.ALREADY_PRESENT,
                        "The canonical demo client already exists and matches "
                        "the expected identity. No change made.",
                    )
                return DemoClientSetupResult(
                    DemoClientSetupOutcome.CONFLICT,
                    "A client already exists at this client_id, but its data "
                    "does not match the expected canonical demo client. No "
                    "change made.",
                )

            existing_by_code = _fetch_client_by_code(session, _CANONICAL_CLIENT_CODE)
            if existing_by_code is not None:
                return DemoClientSetupResult(
                    DemoClientSetupOutcome.CONFLICT,
                    "The canonical demo client_code is already in use by a "
                    "different client_id. No change made.",
                )

            _insert_canonical_client(session, now)
            session.commit()
            return DemoClientSetupResult(
                DemoClientSetupOutcome.INSERTED,
                "The canonical demo client was created.",
            )
        except IntegrityError:
            session.rollback()
            try:
                reread = _fetch_client_by_id(session, _CANONICAL_CLIENT_ID)
            except SQLAlchemyError:
                return DemoClientSetupResult(
                    DemoClientSetupOutcome.FAILED,
                    "Setup could not be completed and the result could not "
                    "be confirmed. No change was intentionally made.",
                )
            if reread is not None and _matches_canonical_identity(reread):
                return DemoClientSetupResult(
                    DemoClientSetupOutcome.ALREADY_PRESENT,
                    "The canonical demo client already exists and matches "
                    "the expected identity. No change made.",
                )
            return DemoClientSetupResult(
                DemoClientSetupOutcome.CONFLICT,
                "A conflicting client record already exists. No change made.",
            )
        except SQLAlchemyError:
            session.rollback()
            return DemoClientSetupResult(
                DemoClientSetupOutcome.FAILED,
                "Setup could not be completed due to a database error. No "
                "change was intentionally made.",
            )


def _run_from_cli() -> int:
    """Operator entry point: load the existing secure configuration
    chain (never a second connection-string implementation), run
    ensure_demo_client(), and print only the fixed, safe outcome
    message -- never the resolved connection string, never raw
    exception text."""
    from dotenv import load_dotenv
    from sqlalchemy.orm import sessionmaker

    from src.config.database import load_database_settings
    from src.db.engine import create_sql_server_engine

    load_dotenv()
    settings = load_database_settings()
    engine = create_sql_server_engine(settings)
    session_factory = sessionmaker(bind=engine)

    result = ensure_demo_client(session_factory)
    print(f"{result.outcome.value}: {result.message}")
    return 0 if result.outcome in (
        DemoClientSetupOutcome.INSERTED,
        DemoClientSetupOutcome.ALREADY_PRESENT,
    ) else 1


if __name__ == "__main__":
    sys.exit(_run_from_cli())


__all__ = [
    "DemoClientSetupOutcome",
    "DemoClientSetupResult",
    "ensure_demo_client",
]
