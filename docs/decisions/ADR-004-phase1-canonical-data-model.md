<!--
File Name: ADR-004-phase1-canonical-data-model.md
Purpose: Records the decision to adopt a canonical 36-table Phase 1 relational data model as the design baseline for database persistence.
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# ADR-004: Phase 1 Canonical Relational Data Model

## Status
Accepted / Approved Design Baseline

## Context
The Prior Authorization workflow needs durable storage that preserves
the project's deterministic-first architecture: deterministic facts,
deterministic rule results, AI inference, human decisions, and audit
history must remain clearly separated rather than blended into a
single table or column. The workflow must stay fully auditable and
traceable, must support Human-in-the-Loop review as the safety
escalation path, and must use synthetic healthcare data only — no real
PHI/PII. Persistence for Phase 1 uses Microsoft SQL Server (see
[[ADR-003-sql-server.md]]), running locally.

The current implementation persists only two tables (`workflow_runs`
and `audit_events`, added in the SQL persistence and audit foundation
work) as a minimal prototype. Before further persistence work expands
this schema, a complete relational design was produced and reviewed
against the actual repository (Python enums, workflow states, AI
contracts, and integration models) across two rounds of gap analysis,
converging on an approved v2.2 design baseline.

## Decision
Adopt a canonical **36-table** Phase 1 relational data model as the
design baseline for database persistence. Key elements of the design:

- **3NF-first** normalization, with intentional denormalization used
  only where documented.
- Clear separation of responsibility across table categories: Fact
  (e.g. cases, diagnoses, documents), Rule (deterministic rule
  evaluations), AI (validated structured AI analysis output), Human
  (human review tasks and outcomes), and Audit (append-only audit
  events).
- A **Case → Workflow Run → Audit Event** hierarchy: a Prior
  Authorization case may have many workflow runs, and each workflow
  run may produce many audit events.
- Organizational master data (clients, departments, locations,
  countries) remains in scope for Phase 1.
- **Case Close is not the same as Logical Delete.** Business closure
  (`case_status_code = CLOSED` with closure metadata) and row-level
  logical deletion (`is_deleted` with delete metadata) are distinct,
  independently tracked lifecycle actions.
- Every persistent table except `audit_events` carries the same nine
  standard lifecycle/control fields (`is_deleted`, `created_at_utc`,
  `created_by`, `updated_at_utc`, `updated_by`, `deleted_at_utc`,
  `deleted_by`, `delete_reason_code`, `delete_reason_text`).
- `audit_events` is **immutable and append-only**; corrections are
  recorded as new events, never as updates or deletes to an existing
  event.
- Two documented, intentional denormalizations exist for audit
  queryability: `audit_events.case_id` (normalized path is
  `trace_id → workflow_runs.trace_id → workflow_runs.case_id`) and
  `audit_events.event_category_code` (normalized path is
  `event_type_code → event_types.event_type_code →
  event_types.event_category_code`), each paired with a composite
  foreign key back to its normalized source to preserve consistency.
- Raw FHIR-style payloads are **not** persisted; only integration
  status, result/failure classification, timing, and safe metadata are
  stored. Raw LLM prompts and provider responses are **not**
  persisted. Only validated, Pydantic-checked structured AI output may
  be persisted.
- Implementation proceeds **incrementally through Waves** (Wave 0
  migration planning through Wave 6 relational hardening), not as a
  single migration.

Full rationale, the complete table inventory, field-level definitions,
seed/reference data, and constraint/index design are recorded in
[[../database/data_model.md]], [[../database/data_dictionary.md]],
[[../database/reference_data.md]], and
[[../database/constraints_and_indexes.md]].

**This ADR records the design baseline only. It does not assert that
all 36 tables are implemented.** As of this decision, the implemented
persistence foundation remains the original two tables (`workflow_runs`,
`audit_events`) with a minimal field set; migration to the canonical
model happens Wave by Wave.

## Consequences
- Stronger traceability: every case, workflow run, deterministic
  evaluation, integration call, AI analysis, human review, and audit
  event has an explicit, queryable relational home.
- Significantly more tables than a minimal prototype schema, which
  increases the surface area to build, test, and maintain.
- More seed/reference data to manage and keep reconciled with the
  application's Python enums and contracts (workflow statuses,
  failure categories, reasons, AI task types, and similar
  vocabularies).
- Explicit migration work is required to move from the current
  two-table persistence foundation to the target schema; this work is
  planned as Wave 0 (migration planning and contract preservation)
  before any schema expansion begins.
- Establishes a clearer path toward productionization (e.g. audit
  immutability enforced at the database-role level, Alembic-based
  migrations) without requiring that path to be built now.

## Related
- [[ADR-003-sql-server.md]]
- [[ADR-001-deterministic-first.md]]
- [[../architecture.md]]
- [[../security.md]]
- [[../database/data_model.md]]
- [[../database/data_dictionary.md]]
- [[../database/reference_data.md]]
- [[../database/constraints_and_indexes.md]]
