# File Name: models.py
# Purpose: Defines the SQLAlchemy ORM tables for workflow run snapshots and audit events.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

# =====================================================================
# WORKFLOW RUNS TABLE
# Purpose:
# Stores the current state of one workflow run, identified by
# trace_id -- one row per trace_id, updated in place as the run
# progresses.
#
# Why:
# A reviewer or dashboard needs to look up "what is the current status
# of this run?" without replaying every audit event. This table is the
# small, current-state counterpart to the append-only audit_events
# table below.
#
# Important Notes:
# - This table does NOT persist the full PriorAuthorizationCase, raw
#   FHIR content, or raw AI output -- see src/models/audit.py for the
#   exact, minimal fields this row is allowed to carry.
# - trace_id is the primary key: see AuditRepository.save_workflow_run()
#   in src/db/repository.py, which updates the existing row for a
#   trace_id instead of inserting a second one.
# =====================================================================


class WorkflowRunORM(Base):
    """One row per workflow run trace, holding its current snapshot."""

    __tablename__ = "workflow_runs"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(64), nullable=False)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# =====================================================================
# AUDIT EVENTS TABLE
# Purpose:
# Stores one append-only row per audit event, for every workflow trace.
#
# Why:
# Unlike workflow_runs (current state only), this table is meant to
# grow: every meaningful step gets its own row, in occurred_at_utc
# order, so a reviewer can see the full sequence of what happened for
# one trace_id.
#
# Important Notes:
# - trace_id is a logical, application-level relationship to
#   workflow_runs.trace_id, not a physical foreign key. Phase 1 does
#   not need cascading deletes or database-enforced referential
#   integrity for this prototype; a foreign key can be added later if
#   a real production need for it appears. This is a deliberate,
#   documented simplification, not an oversight.
# - No large generic JSON/blob payload column exists here. Every column
#   is a small, specific, structured field -- see src/models/audit.py
#   for the matching application-facing model and the fields that are
#   intentionally excluded.
# - event_id is the primary key: AuditRepository.append_audit_event()
#   must fail, not silently overwrite, if the same event_id is used
#   twice.
# - trace_id is indexed (not just a plain column) so
#   list_audit_events(trace_id) stays efficient as this table grows.
# =====================================================================


class AuditEventORM(Base):
    """One append-only row per audit event."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_trace_id", "trace_id"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_category: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
