<!--
File Name: ADR-006-first-revision-and-brownfield-strategy.md
Purpose: Records the approved first Alembic revision and brownfield prototype transition strategy
Creation Date: 2026-09-17
Author: K.Kashiwagi
-->

# ADR-006: First Revision and Brownfield Prototype Strategy

## Status
Accepted

## Context
Task 19E installed and initialized the Alembic migration framework ([[ADR-005-database-schema-migration-strategy.md]]): `alembic.ini` and `migrations/` (`env.py`, `script.py.mako`, `versions/`) exist, `env.py`'s `target_metadata` points at this project's existing `Base.metadata` (`src/db/base.py`, `src/db/models.py`), and Alembic is wired to the project's existing secure database configuration. No migration revision exists yet, and no `alembic_version` table exists on the real database.

The local Microsoft SQL Server database (`healthcare_ai_fde_lab`) already contains two tables created before Alembic existed, via `Base.metadata.create_all()` in Task 18A/18B: `dbo.workflow_runs` and `dbo.audit_events`. These currently hold only synthetic Task 18B validation rows — no real data, no PHI/PII.

The approved target is the canonical 36-table Phase 1 model ([[ADR-004-phase1-canonical-data-model.md]]), implemented incrementally through Waves ([[../database/migration_plan.md]]). Before the first Alembic revision can be written, the project needs an explicit answer to: what does that first revision contain, how are the existing two prototype tables treated, when do they get replaced, how does a completely fresh database reach the same schema, and how do the approved Wave 1/Wave 2 boundaries stay intact. This ADR resolves that decision. It creates no migration revision and executes no database change.

## Decision
1. **The first Alembic revision(s) implement Wave 1 only** — Organization, Lifecycle & Core Reference Foundation, per [[../database/migration_plan.md]] §10–§11 (Tier 0 reference masters plus `clients`/`departments`/`locations`/`countries`). They do not redesign, alter, or drop `workflow_runs` or `audit_events`, do not migrate Task 18B synthetic rows, and do not implement any Wave 2 case/workflow schema.
2. **The existing brownfield tables remain physically present, untouched, and ignored during Wave 1.** The Wave 1 migration adds only its own foundation objects; it contains no conditional logic checking for or reacting to the existing tables.
3. **A controlled prototype rebuild happens at the Wave 2 boundary, not before.** Immediately before Wave 2 physical implementation begins, the local prototype database is deliberately dropped and recreated empty, with explicit approval sought at that time — because its only contents are disposable synthetic Task 18B rows, not because database rebuilds are a general migration technique.
4. **After that rebuild, the fresh empty database receives the full Alembic revision chain from the base** — Wave 1 revision(s), then Wave 2 revision(s), then later Waves — the same path any brand-new clone or developer environment uses. Wave 2's revisions are what create the canonical target forms of `workflow_runs` and `audit_events`, together with their required case/workflow dependencies.
5. **No `alembic stamp` and no fake baseline revision.** The Alembic revision history will represent only schema changes Alembic actually applied. `alembic_version` is created and managed by Alembic itself, only once the future Wave 1 migration is actually executed — not in this task, and not by pretending the current prototype tables correspond to a revision that never created them.
6. **No environment-specific conditional migration branching** (e.g. "if `workflow_runs` exists, alter it; else, create it") is introduced unless a later implementation review proves it is genuinely necessary. The preferred architecture is one deterministic fresh-build revision chain, plus one explicitly controlled prototype reset at the Wave 2 boundary — simpler to write, test, explain, and reproduce than conditional branching.

This ADR is a strategy decision only. No migration revision is created, no Alembic command that touches a database is run, and no SQL Server object is created, altered, or dropped as a result of this document.

## Wave 1 Behavior
The first revision(s) add only Wave 1's dependency-foundation schema: the Tier 0 pure reference masters (`countries`, `case_statuses`, `reasons`, `workflow_statuses`, `workflow_actions`, `requirement_types`, `document_types`, `event_categories`, `actor_types`, `source_components`, `result_codes`, `failure_categories`, `human_review_statuses`, `human_review_outcomes`, `discovery_item_types`, `ai_task_types`) plus the organization masters (`clients`, `departments`, `locations`) — exactly the scope [[../database/migration_plan.md]] §11 already assigns to Wave 1. Nothing outside that scope is silently pulled forward into the first revision. `dbo.workflow_runs` and `dbo.audit_events` are not referenced, altered, or dropped by any Wave 1 revision.

## Brownfield Prototype Behavior
The current local database is a temporary, pre-Alembic prototype predecessor to the canonical Alembic-managed schema, not a system the migration history needs to explain or absorb. During Wave 1 it simply sits alongside the new Wave 1 objects, unmodified. Its synthetic Task 18B rows are not inspected, preserved, or migrated by this ADR or by the Wave 1 revision. This is a deliberate continuation of the Task 19C position that preserving *application/repository behavior* matters, while preserving *these specific temporary rows* does not.

## Wave 2 Controlled Rebuild
Before Wave 2 physical implementation begins, the local prototype database may be deliberately dropped and recreated empty. This is acceptable only because: the existing rows are synthetic, no real PHI/PII exists, no production data exists, preserving the Task 18B rows has no portfolio value, and a clean migration chain is more valuable than a complicated in-place conversion of a schema that predates Alembic entirely. This rebuild is explicitly **not** an Alembic downgrade, not a production rollback, and not a routine migration technique — it is a one-time, controlled Phase 1 prototype reset, requiring explicit approval when the future Wave 2 implementation task actually occurs. No rebuild occurs as part of this ADR.

## Fresh Database Path
A completely fresh database — a new local instance, a new developer's machine, or (conceptually) a future non-local environment — is constructible using only the version-controlled Alembic revision chain: empty database → Wave 1 revision(s) → Wave 2 revision(s) → Wave 3 → … → the canonical Phase 1 schema. No manual SSMS schema creation is required, and `Base.metadata.create_all()` is not used to build this real schema (its role remains limited to the offline SQLite test double and disposable bootstrap convenience, per [[ADR-005-database-schema-migration-strategy.md]]). This is the same path the rebuilt local prototype database follows after the Wave 2 controlled rebuild — there is exactly one fresh-build path, not two.

## Why No Stamp / Fake Baseline
`alembic stamp` marks a database as already being at a given revision without running that revision's `upgrade()`. Using it to mark the current prototype tables as though a Wave 1 (or earlier) revision created them would record a false history: Alembic never actually created `workflow_runs`/`audit_events` in their current prototype form, so stamping them as if it had would misrepresent what happened, weaken the reproducibility guarantee that is the entire point of adopting Alembic ([[ADR-005-database-schema-migration-strategy.md]]), and make the revision chain unreliable evidence for "what changed, when." The controlled rebuild (dropping the two prototype tables and replaying the real, honest revision chain from base) preserves an accurate history instead.

## Rationale
- The existing prototype data is synthetic and disposable; nothing about it requires preservation.
- No production or real user data exists anywhere in this project to lose.
- Avoids a complex, brittle in-place conversion of a two-table pre-Alembic schema into a differently-shaped 36-table target.
- Avoids a fake stamp/baseline that would misrepresent the project's actual migration history.
- Keeps every migration deterministic and environment-independent — no conditional logic branching on what happens to already exist.
- Preserves the approved Wave 1/Wave 2 boundaries exactly as already documented, rather than quietly renegotiating them to accommodate the brownfield tables.
- Gives a single, clean fresh-database path that is also the path every future developer or environment uses.
- Provides a more credible, explainable migration model to reason about for later Waves.
- Is materially easier for the developer to explain and defend in an FDE interview than either a fake baseline or bespoke conditional migration logic.

## Production Boundary
This strategy is a Phase 1 prototype decision, not a general database-operations practice, and must not be read as one. **Production databases should not routinely be dropped and rebuilt.** The controlled rebuild described here is acceptable *only* because this is a local Phase 1 prototype holding exclusively synthetic, disposable data. A real production migration strategy would need to preserve live data and would require materially stronger backup/recovery procedures, deployment controls, backward/forward compatibility planning, rollback procedures, monitoring, and change-approval processes — all of which remain explicit Phase 2 / productionization considerations, not something this ADR claims to have solved.

## Consequences
- The first Alembic revision(s), when actually written, are scoped narrowly to Wave 1 — smaller and easier to review than a combined Wave 1+2 migration would be.
- Wave 1 physical implementation can begin (an implementation task, not this ADR) without waiting on a Wave 2 design decision.
- A real, explicitly-approved rebuild step is now a documented, expected part of the Wave 2 transition, not a surprise or an implicit assumption.
- The Alembic revision history will always represent real applied changes; no revision will ever claim to have created something it didn't.
- The exact DDL/schema content of the first Wave 1 revision is still not decided by this ADR — only its *scope and boundaries* are. Writing the actual revision remains a separate future implementation task.

## Alternatives Considered

**Alternative A — In-place migration of the two prototype tables.** Converting `workflow_runs`/`audit_events` directly, column by column, into their Wave 2 target forms via a sequence of `ALTER TABLE` operations. Not selected as the approach here because the data involved is synthetic and disposable, and the target schema differs substantially (new required columns, new composite FKs, new control fields) — the complexity of a careful in-place conversion buys nothing when there is nothing worth preserving. This does not mean in-place migration is wrong in general; for data that must be preserved, it would be the right approach, and remains the expected approach once real Wave-by-Wave data exists.

**Alternative B — `alembic stamp` the current state as a baseline.** Marking the existing prototype tables as though some revision had created them, so Alembic would treat the database as already "caught up" to that point. Not selected because it would assert a migration history that never actually happened, weakening the reproducibility and trustworthiness that is the reason Alembic was adopted in the first place (see Why No Stamp / Fake Baseline above).

**Alternative C — Conditional migration branches for existing vs. fresh database.** Writing revision logic that checks whether `workflow_runs`/`audit_events` already exist and behaves differently depending on the answer. Not selected because it adds environment-specific complexity — and a corresponding testing burden — that this prototype does not need, when a single controlled rebuild step achieves the same outcome more simply and more explainably. This is not a claim that conditional migration logic is never appropriate; only that it is unjustified complexity for this project's current scale.

## Related
- [[ADR-004-phase1-canonical-data-model.md]]
- [[ADR-005-database-schema-migration-strategy.md]]
- [[../architecture.md]]
- [[../database/migration_plan.md]]
- [[../database/data_model.md]]
- [[../database/data_dictionary.md]]
