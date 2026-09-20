<!--
File Name: architecture.md
Purpose: Documents system architecture, workflow, component responsibilities, deterministic/AI/human boundaries, failures, state persistence, and Mermaid diagrams.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# Architecture — Phase 1

## 1. Overview

The system supports a synthetic healthcare Prior Authorization workflow.
It is designed around a **deterministic-first** principle: explicit
validation and business rules do as much work as possible, and an LLM
is invoked only for narrow, language-oriented tasks. Any output that
could affect the case outcome — deterministic or AI-derived — that is
missing, uncertain, or high-impact is routed to a human reviewer before
the workflow completes.

See [decisions/](decisions/) for the formal Architecture Decision
Records behind the choices below.

## 2. Planned Components (Phase 1)

| Layer | Technology | Role |
|-------|-----------|------|
| Frontend | Streamlit | Demonstration UI for submitting/viewing cases and outcomes |
| API | FastAPI + Pydantic | Request validation and API surface |
| Workflow | LangGraph | Explicit state machine for workflow routing (see [ADR-002](decisions/ADR-002-langgraph.md)) |
| AI | Azure OpenAI / Azure AI Foundry | Structured-output LLM calls for language-oriented sub-tasks |
| Integration | REST/JSON, FHIR-style shapes | Synthetic healthcare data interchange |
| Database | Microsoft SQL Server (local) | Case data, workflow state, audit log (see [ADR-003](decisions/ADR-003-sql-server.md)) |
| Testing | pytest | Unit/integration tests for rules and workflow routing |

None of the above is implemented yet — see [README.md](../README.md)
for current status.

## 3. Architecture Principles

1. **Deterministic-first.** Explicit logic is preferred over model
   inference wherever it can reliably do the job.
2. **Validate inputs before AI processing.** No data reaches the LLM
   step without first passing schema validation.
3. **Apply explicit Python business rules before LLM reasoning.**
   Business rules run first; the LLM is invoked only if the rules
   determine it is needed.
4. **Use LLMs only for ambiguity, language understanding,
   summarization, or similar probabilistic tasks** — never for the
   final clinical approval/denial decision.
5. **Important or uncertain cases go to human review.** Missing data,
   low-confidence AI output, or failed validation all route to a human
   reviewer rather than a guessed outcome.
6. **Separate deterministic facts/rules, AI inference, and human
   decisions.** These are distinct, clearly labeled stages in the data
   model and the workflow graph — never blended into a single opaque
   step.
7. **Make workflow states and routing explicit.** The LangGraph state
   machine's nodes and edges are the source of truth for how a case
   moves through the system.
8. **Maintain traceability and audit events.** Every transition and
   decision point is logged for audit purposes.
9. **Fail safely when LLM or healthcare APIs fail.** Failures route to
   human review or a clearly labeled error state — never a silent
   guess.
10. **Preserve workflow state when waiting for human review.** A case
    pending review can be resumed without data loss.
11. **Prefer simple and explainable design.** Favor the more
    explainable option when a design choice is a toss-up.
12. **Do not introduce technology simply because it is popular.** Every
    dependency in the stack is chosen for a specific, stated reason
    (see [decisions/](decisions/)).

## 4. High-Level Workflow

See the workflow diagram in [README.md](../README.md#high-level-workflow).

At a high level: input arrives via the API, is validated, run through
deterministic business rules, optionally augmented by an LLM step with
its own output validation, and — depending on completeness, rule
outcomes, and AI confidence — either continues automatically or is sent
to human review. All outcomes are persisted to SQL Server along with an
audit trail.

## 5. Data Separation Model

The data model distinguishes three categories of information at every
stage of a case:

- **Deterministic facts/rules** — validated input data and the results
  of explicit business-rule evaluation.
- **AI inference** — LLM-derived output (e.g., a summary or
  classification), always tagged as AI-derived and never conflated with
  validated fact.
- **Human decisions** — the reviewer's decision, recorded distinctly
  from both of the above.

This separation is what makes the audit trail meaningful: for any case,
it must be possible to see exactly which facts were supplied, what the
rules concluded, what the AI suggested (if anything), and what a human
ultimately decided.

## 6. Database Design

**Current implementation:** **Wave 1 and Wave 2 of the canonical
database foundation are now physically implemented** — 14 organization/
reference tables (Wave 1) plus 8 case/workflow tables (Wave 2) have
been created on the real local SQL Server database and validated (see
below). The `workflow_runs` and `audit_events` tables, accessed
through the same `AuditRepository` pattern, are now their **canonical**
23/19-column shape — the Task 18A/18B prototype shape was replaced via
a controlled rebuild at the Wave 2 boundary (ADR-006); the prototype's
disposable synthetic rows were intentionally removed, not preserved.
No persistence orchestration wires the LangGraph workflow or the API
to any of these tables yet — the physical schema and repository model
exist, but nothing in `src/workflow/` or `src/api/` writes to them.

**Target Phase 1 design:** a canonical 36-table relational model
(organizational masters, case/workflow persistence, deterministic
rule evaluations, integration execution records, validated AI output,
human review, and immutable audit history), implemented incrementally
through Waves. The target schema is a reviewed design baseline; 22 of
36 tables (Waves 1-2) are now physically built, the remaining 14
(Waves 3-6) are not yet built.

Full detail is maintained in the dedicated database documentation
rather than duplicated here: [database/](database/), the
[reviewed ERD artifacts](database/erd/), the
[migration plan](database/migration_plan.md) (Wave 0 planning plus
Wave 1 physical implementation status), and
[ADR-004](decisions/ADR-004-phase1-canonical-data-model.md).

**Schema migration mechanism:** Alembic + SQLAlchemy (see
[ADR-005](decisions/ADR-005-database-schema-migration-strategy.md)).
Status: architecture decision accepted, the migration framework is
installed and initialized (`alembic.ini`, `migrations/`), wired to this
project's existing SQLAlchemy metadata and secure database
configuration, and in active use. The first-revision/brownfield
prototype transition strategy is resolved (see
[ADR-006](decisions/ADR-006-first-revision-and-brownfield-strategy.md))
and has been fully executed: the first revision (`c841e86a8516`)
implemented Wave 1 only, additively, leaving the existing
`workflow_runs`/`audit_events` tables untouched; the second revision
(`b9aba5b07ac8`) implemented Wave 2 and performed the approved
controlled rebuild of those two tables into their canonical shape.

**Wave 1 physical database foundation:** IMPLEMENTED.
**Wave 2 physical database foundation:** IMPLEMENTED.
**Real SQL Server validation:** COMPLETED for both.
**Installed Alembic revision:** `b9aba5b07ac8`.

Validated on the real local `healthcare_ai_fde_lab` database: all 14
Wave 1 tables and all 8 Wave 2 tables exist (23 `dbo` tables total,
including `alembic_version`); 8/8 Wave 2 primary keys, 40/40 Wave 2
foreign keys, and 2/2 Wave 2 business-key `UNIQUE` constraints
confirmed present; `document_types` was pulled forward from Wave 3
into Wave 2 because `case_documents.document_type_code` requires it
(schema only — see
[migration_plan.md §17.D](database/migration_plan.md#17d-wave-2-physical-implementation--complete)
for the full resolved-dependency explanation); the canonical
`workflow_runs`/`audit_events` tables replaced the prototype shape,
with the prototype's disposable synthetic rows intentionally removed;
all 14 Wave 1 tables confirmed untouched; every Wave 2 table contains
no rows (no seed/reference data has been loaded).

**Wave 6 relational hardening remains deferred** — CHECK constraints,
ISJSON validation, secondary indexes, composite FKs, the `event_types`
composite-FK-support `UNIQUE` constraint, and the `workflow_runs`
composite `UNIQUE(trace_id, case_id)` are intentionally not yet
applied; their absence was explicitly confirmed during both Wave 1 and
Wave 2 validation, not overlooked.

**Wave 2 runtime identity/traceability decisions:** the two
architecture decisions that were blocking Wave 2 schema design —
`trace_id` generation and the LangGraph-node-to-`workflow_definition_steps`
mapping — are resolved (see
[ADR-007](decisions/ADR-007-trace-id-and-workflow-step-mapping.md)).
In summary: `trace_id` is an application-generated UUID4, created once
per workflow run at the future orchestration boundary immediately
before the graph runs (this boundary does not exist in `src/` yet);
and every current LangGraph node is explicitly mapped to a stable
`step_code`, rather than persisting Python function names. **Neither
decision has runtime code behind it yet** — the Wave 2 schema itself
now physically supports them (e.g. `workflow_runs.trace_id` accepts an
application-generated UUID4; `audit_events.workflow_step_id` FKs to
`workflow_definition_steps`), but no orchestration boundary, no
LangGraph/API persistence wiring, and no node→step mapping module
exist in `src/` — this remains explicitly future work, not something
ADR-007 itself implemented.

## 7. Related Documents

- [requirements.md](requirements.md)
- [security.md](security.md)
- [production_roadmap.md](production_roadmap.md)
- [database/](database/) — Phase 1 canonical database design documentation
- [decisions/ADR-001-deterministic-first.md](decisions/ADR-001-deterministic-first.md)
- [decisions/ADR-002-langgraph.md](decisions/ADR-002-langgraph.md)
- [decisions/ADR-003-sql-server.md](decisions/ADR-003-sql-server.md)
- [decisions/ADR-004-phase1-canonical-data-model.md](decisions/ADR-004-phase1-canonical-data-model.md)
- [decisions/ADR-005-database-schema-migration-strategy.md](decisions/ADR-005-database-schema-migration-strategy.md)
- [decisions/ADR-006-first-revision-and-brownfield-strategy.md](decisions/ADR-006-first-revision-and-brownfield-strategy.md)
- [decisions/ADR-007-trace-id-and-workflow-step-mapping.md](decisions/ADR-007-trace-id-and-workflow-step-mapping.md)
