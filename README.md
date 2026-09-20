<!--
File Name: README.md
Purpose: Main project overview, Phase 1 scope, architecture summary, current status, setup guidance, limitations, and production roadmap.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# Healthcare AI Forward Deployment Lab

## 1. Purpose

This project demonstrates the end-to-end skill set of a healthcare Data
Forward Deployment Engineer (FDE): translating a business problem into
requirements, designing a solution architecture, implementing it, and
planning its path from prototype to production — applied to a
healthcare workflow support use case.

## 2. FDE Portfolio Objective

This project is intentionally built to demonstrate:

- Requirements gathering and translation
- Solution architecture
- Python development
- REST/API integration
- Healthcare/FHIR-style integration
- LLM workflows
- SQL
- Testing
- Human-in-the-loop review
- Auditability
- Documentation
- Client delivery thinking
- Prototype-to-production planning

## 3. Phase 1 Use Case

**Prior Authorization workflow support.** A synthetic prior
authorization case is validated, run through explicit business rules,
optionally assisted by an LLM for language-oriented sub-tasks, and
routed to human review when information is missing, uncertain, or
high-impact. See [docs/requirements.md](docs/requirements.md) for full
detail.

**This is not intended to be a production healthcare system.** Only
synthetic healthcare data is used. The AI does not independently make
clinical approval or denial decisions — see
[docs/security.md](docs/security.md).

## 4. Current Project Status

**IMPLEMENTED:**
- Pydantic prior-authorization case validation
- Deterministic completeness rules
- FastAPI case-validation endpoint (`POST /cases/validate`)
- LangGraph workflow foundation (explicit graph, nodes, and routing)
- Deterministic AI-routing rules
- Structured AI contract and provider flow (validated structured
  output, never a raw/untrusted LLM response)
- Azure OpenAI adapter and configuration
- Synthetic FHIR-style integration client
- Deterministic evidence-consistency rules
- SQL persistence and audit foundation (`workflow_runs`, `audit_events`
  tables via a repository pattern)
- Local Microsoft SQL Server persistence validation (connectivity,
  schema creation, and repository read/write round-trips against a
  real local instance)
- Alembic migration framework, operational and applied: Wave 1
  (14 organization/reference tables) and Wave 2 (8 case/workflow
  tables, including a canonical replacement of the `workflow_runs`/
  `audit_events` prototype) of the canonical database foundation have
  both been migrated onto the real local SQL Server database and
  validated (installed revision `b9aba5b07ac8`); the disposable
  synthetic prototype rows were intentionally removed as part of the
  Wave 2 controlled rebuild, and all 14 Wave 1 tables were preserved
  unchanged
- LangGraph ↔ SQL persistence orchestration boundary (pure Python,
  `src/workflow/orchestrator.py`): generates one application-side
  UUID4 `trace_id` per workflow run, invokes the existing LangGraph
  graph, and persists the run to canonical `workflow_runs` (create at
  start, update on completion, immutable run-identity fields enforced)
  and canonical `audit_events` (meaningful transitions only, using the
  explicit stable LangGraph-node → `step_code` mapping in
  `src/workflow/step_mapping.py` — never a raw Python function name).
  `HUMAN_REVIEW_REQUIRED` is persisted as a pause, not a completion;
  persistence failures are surfaced, never hidden. Not yet wired to any
  HTTP endpoint — see Current Limitations.
- Stable Phase 1 reference/configuration data loader
  (`src/db/reference_data.py`), separate from Alembic schema
  migrations: idempotent insert-missing-only loading with conflict
  detection (a semantic mismatch fails and rolls back the whole load
  rather than silently overwriting). Loaded onto the real local SQL
  Server database and validated, including a second-run idempotency
  check (0 inserted, all 78 already present): 78 stable rows across 12
  tables, including the complete approved 8-step `PRIOR_AUTHORIZATION`
  workflow definition/configuration.
- Real local SQL Server integration validation of the orchestration
  boundary end to end: a synthetic case, mocked FHIR success, the
  AI-not-needed path, reaching `COMPLETED`/`COMPLETE_WORKFLOW`, with
  exactly one `workflow_runs` row and six `audit_events` rows
  persisted, all sharing one `trace_id`, and the synthetic test
  fixture cleaned up afterward. No Azure OpenAI call and no real
  external FHIR call were made.
- pytest test suite (312 tests passing, 1 opt-in real-SQL-Server test
  intentionally skipped by default, as of this update)
- Architecture design artifacts (ADRs, architecture/security/
  requirements docs)

**DESIGNED / PLANNED (not yet implemented):**
- Remaining canonical Phase 1 relational data model (Wave 3 and later,
  14 of 36 tables remaining) — see [docs/database/](docs/database/)
- Wave 6 relational hardening (CHECK constraints, JSON validation,
  secondary indexes, composite FKs, `event_types` composite uniqueness,
  `workflow_runs` composite uniqueness)
- An API endpoint that invokes the orchestration boundary (`POST
  /cases/validate` remains validation-only; no endpoint triggers full
  LangGraph execution/persistence yet)
- Human-in-the-Loop pause/resume orchestration, reviewer assignment,
  reviewer UI, reviewer-decision persistence, and final human
  approval/denial workflow (today the orchestrator persists
  `HUMAN_REVIEW_REQUIRED` correctly and preserves the run's `trace_id`
  for a future resume, but does not itself pause/resume anything)
- Streamlit application
- Remaining end-to-end and productionization work — see
  [docs/production_roadmap.md](docs/production_roadmap.md)

## 5. Planned Phase 1 Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit |
| Backend | Python, FastAPI, Pydantic |
| Workflow | LangGraph |
| Database | Microsoft SQL Server (local), SQL |
| AI | Azure OpenAI / Azure AI Foundry, structured LLM output |
| Integration | REST/JSON, healthcare/FHIR-style API |
| Testing | pytest |
| Development | Git, GitHub, Claude Code |

These choices (LangGraph, SQL Server, Azure OpenAI/Foundry) have been
reviewed and are fixed for Phase 1 — see
[docs/decisions/](docs/decisions/).

## 6. High-Level Architecture

The system separates three kinds of information at every stage of a
case: **deterministic facts/rules**, **AI inference**, and **human
decisions** — never blended together. Explicit validation and business
rules run before any LLM call; the LLM is used only for
language-oriented sub-tasks, never for the final outcome; and anything
missing, uncertain, or high-impact routes to human review. Full detail:
[docs/architecture.md](docs/architecture.md).

## 7. High-Level Workflow

```mermaid
flowchart TD
    A[Client / Synthetic Case Input] --> B[FastAPI]
    B --> C[LangGraph Workflow]

    C --> D[Pydantic Validation]
    D --> E{Missing Information?}

    E -->|Yes| HR[Human Review Required]
    E -->|No| F[Deterministic Business Rules]

    F --> Q{Healthcare / FHIR API Needed?}
    Q -->|No| G{AI Needed?}
    Q -->|Yes| R[Call Healthcare / FHIR-style API]

    R --> S{API Call Successful?}
    S -->|Yes| G
    S -->|No| HR

    G -->|No| I[Continue Workflow]
    G -->|Yes| J[Call Azure OpenAI / LLM]

    J --> T{LLM Call Successful?}
    T -->|No| U[LLM Call Failed - Timeout / Service Error / Exception]
    U --> HR
    T -->|Yes| K[Validate Structured Output]

    K --> L{Structured Output Valid and Safe?}
    L -->|No| V[Structured Output Invalid or Unsafe]
    V --> HR
    L -->|Yes| I

    I --> M{Human Review Required?}
    M -->|Yes| HR
    M -->|No| N[Persist Result]

    HR --> PS[Persist Workflow State]
    PS --> PAUSE[Pause Workflow]
    PAUSE --> HREV[Human Review]
    HREV --> RD[Record Human Decision]
    RD --> RESUME[Resume Workflow]
    RESUME --> N

    N --> O[SQL Server Audit Log]
    O --> P[Workflow Outcome]
```

## 8. Security & Privacy Statement

- Only **synthetic** healthcare data is used — no real PHI/PII, ever.
- No secrets, credentials, or connection strings are hard-coded;
  configuration is supplied via environment variables and git-ignored
  local files (see [.env.example](.env.example)).
- The AI does not independently make clinical approval or denial
  decisions — see [docs/security.md](docs/security.md) for full policy.

## 9. Prototype vs. Production

This is a **portfolio prototype**, not a production healthcare system.
It does not include production-grade authentication/authorization,
managed secrets, real FHIR server integration, formal compliance
controls, or operational hardening. See
[docs/production_roadmap.md](docs/production_roadmap.md) for what
Phase 2 (production) would require.

## 10. Current Limitations

- No real external FHIR/payer system integration exists — the
  FHIR-style client uses synthetic data only, not a live production
  data source.
- Only 22 of the canonical 36-table Phase 1 database design (see
  [docs/database/](docs/database/)) are physically built (Waves 1-2).
  The LangGraph workflow is now wired to persistence (see Current
  Status), but only as a pure Python orchestration function — no HTTP
  endpoint invokes it yet, so the running API surface
  (`POST /cases/validate`) still does not itself persist anything.
- Human-review *outcomes* (a reviewer's decision) are not yet
  persisted, and there is no pause/resume orchestration yet — only the
  `HUMAN_REVIEW_REQUIRED` routing state itself is persisted today.
- No Streamlit UI exists yet.
- Not evaluated for clinical, legal, or regulatory accuracy — it is a
  technical/architectural demonstration only.

## 11. Phase 2 — Productionization (Summary)

Moving toward production would require, among other things: real
PHI/HIPAA-compliant data handling, authentication/authorization, a
managed secrets vault, real FHIR/payer integrations, production
observability, and formal AI governance. See
[docs/production_roadmap.md](docs/production_roadmap.md) for the full
summary.

## 12. Database Design Documentation

**IMPLEMENTED:**
- The Alembic migration framework (see
  [ADR-005](docs/decisions/ADR-005-database-schema-migration-strategy.md))
  is installed, initialized, and in active use — `alembic.ini` and
  `migrations/` (`env.py`, `script.py.mako`, `versions/`) exist in the
  repository.
- Wave 1 of the canonical database foundation — 14 organization and
  core reference tables (`reasons`, `countries`, `clients`,
  `locations`, `departments`, `case_statuses`, `workflow_statuses`,
  `workflow_actions`, `event_categories`, `event_types`,
  `actor_types`, `source_components`, `result_codes`,
  `failure_categories`) — has been migrated onto the real local SQL
  Server database `healthcare_ai_fde_lab` and validated: all primary
  keys, foreign keys, and business-key uniqueness constraints
  confirmed present.
- Wave 2 of the canonical database foundation — 8 case/workflow tables
  (`document_types`, `workflow_definitions`, `workflow_definition_steps`,
  `prior_authorization_cases`, `case_diagnoses`, `case_documents`, and
  the canonical `workflow_runs`/`audit_events`) — has also been
  migrated onto the real local SQL Server database and validated:
  installed Alembic revision `b9aba5b07ac8`, 8/8 primary keys, 40/40
  foreign keys, and 2/2 business-key uniqueness constraints confirmed
  present. `document_types` was originally scoped to Wave 3 but was
  pulled forward into Wave 2 because `case_documents.document_type_code`
  requires it (schema only — no reference rows were inserted).
- The canonical `workflow_runs`/`audit_events` tables (23/19 columns,
  accessed through `AuditRepository`) replaced the Task 18A/18B
  prototype shape via a controlled rebuild — the disposable synthetic
  prototype rows were intentionally removed, per
  [ADR-006](docs/decisions/ADR-006-first-revision-and-brownfield-strategy.md).
  All 14 Wave 1 tables were preserved, untouched, throughout.
- The `trace_id` generation point and the LangGraph-node-to-workflow-step
  mapping architecture decisions (see
  [ADR-007](docs/decisions/ADR-007-trace-id-and-workflow-step-mapping.md))
  are now implemented as running code:
  `src/workflow/orchestrator.py` generates the `trace_id` and
  `src/workflow/step_mapping.py` is the single authoritative node →
  `step_code` mapping.
- Reference/master seed data loading (`src/db/reference_data.py`) —
  idempotent, conflict-detecting, separate from Alembic — is
  implemented and has been run against the real local SQL Server
  database: 78 stable rows across 12 tables, including the complete
  8-step `PRIOR_AUTHORIZATION` workflow definition. Synthetic business
  fixtures (a test client/case) are explicitly not part of this stable
  catalog and are not loaded by it.

**DESIGNED / PLANNED:**
- The remaining canonical Phase 1 relational data model (Wave 3 and
  later — 14 of 36 tables) covering deterministic rule evaluations,
  integration execution records, validated AI output, human review,
  and client requirement intake. This design has been reviewed and
  approved as the Phase 1 baseline but is implemented incrementally
  through Waves.
- An API endpoint that invokes the orchestration boundary end to end
  (the orchestrator itself is implemented; no HTTP route calls it yet).
- Human-in-the-Loop pause/resume orchestration and reviewer-decision
  persistence (Task 23 scope).
- Wave 6 relational hardening (CHECK constraints, ISJSON validation,
  secondary indexes, composite FKs, the `event_types` composite-FK-support
  uniqueness constraint, and `workflow_runs` composite uniqueness) —
  deliberately deferred, not yet applied.

See:
- [docs/database/data_model.md](docs/database/data_model.md)
- [docs/database/data_dictionary.md](docs/database/data_dictionary.md)
- [docs/database/reference_data.md](docs/database/reference_data.md)
- [docs/database/constraints_and_indexes.md](docs/database/constraints_and_indexes.md)
- [docs/database/erd/](docs/database/erd/) — reviewed ERD artifacts (overview, full, and Mermaid text formats)
- [docs/database/migration_plan.md](docs/database/migration_plan.md) — Wave 0 migration plan and Wave 1/Wave 2 physical implementation status
- [docs/decisions/ADR-004-phase1-canonical-data-model.md](docs/decisions/ADR-004-phase1-canonical-data-model.md)
- [docs/decisions/ADR-005-database-schema-migration-strategy.md](docs/decisions/ADR-005-database-schema-migration-strategy.md) — schema migration mechanism decision

## 13. Documentation Index

- [docs/requirements.md](docs/requirements.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/security.md](docs/security.md)
- [docs/production_roadmap.md](docs/production_roadmap.md)
- [docs/decisions/](docs/decisions/) — Architecture Decision Records
- [docs/database/](docs/database/) — Phase 1 canonical database design documentation
- [CLAUDE.md](CLAUDE.md) — guidance for Claude Code in this repo
