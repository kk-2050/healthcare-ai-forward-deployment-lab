<!--
File Name: ADR-005-database-schema-migration-strategy.md
Purpose: Records the approved Phase 1 database schema migration and versioning strategy
Creation Date: 2026-09-17
Author: K.Kashiwagi
-->

# ADR-005: Database Schema Migration Strategy

## Status
Accepted

## Context
The project has an approved canonical 36-table Phase 1 relational model ([[ADR-004-phase1-canonical-data-model.md]]). The current implementation persists only two prototype tables, `dbo.workflow_runs` and `dbo.audit_events`, created with `Base.metadata.create_all()` (`src/db/base.py`). That function's own code comments already describe it as prototype-only, not a production migration mechanism.

The approved Wave 0 migration plan ([[../database/migration_plan.md]]) identified the schema-application mechanism — *how* future physical changes to the real SQL Server database will be created, tracked, reviewed, and reversed — as the single remaining blocker to Wave 1 **physical** schema implementation. Wave 1 **planning** was already unblocked by that plan; this ADR resolves the remaining blocker.

A repository-aware architecture review (Task 19D) inspected the actual codebase and documentation, evaluated Alembic, versioned SQL scripts, and `metadata.create_all()` against the target 36-table design's SQL Server-specific requirements, and recommended Alembic + SQLAlchemy. This ADR records that decision formally.

**Project owner context:** the project owner has not previously used SQLAlchemy or Alembic independently and is still learning both. This ADR therefore includes a short plain-English explanation below, and explicitly separates *deciding* on Alembic from *implementing* it — implementation is deferred to a later, separately approved task with step-by-step guidance.

## Plain-English Explanation

**SQLAlchemy** defines how the Python code represents and interacts with database tables. It is already in use — `src/db/models.py` defines `WorkflowRunORM` and `AuditEventORM` as Python classes, and `AuditRepository` (`src/db/repository.py`) reads and writes rows through them. SQLAlchemy answers the question "what does the application expect the database to look like right now?"

**Alembic** is a separate, complementary tool that tracks *how the physical database structure changes over time*. Instead of one big "create everything" step, Alembic uses small, numbered, reviewable files called *revisions*, each describing one step of change, chained together in order. For example:

- Revision 001: create the organization/reference tables (Wave 1)
- Revision 002: add the case/workflow tables (Wave 2)
- Revision 003: add additional constraints/indexes (Wave 6)

The goal is that another developer — or the same developer six months later — can clone the repository and answer, with certainty rather than guesswork: which schema version is currently installed, what changed at each step, in what order, and how to reproduce the exact same database from scratch.

## Decision
The approved primary mechanism for all future physical schema creation and evolution against the real Microsoft SQL Server database (`healthcare_ai_fde_lab`) is **Alembic + SQLAlchemy**.

- SQLAlchemy remains the ORM / application-facing database layer, unchanged in role.
- Alembic becomes the single version-controlled mechanism for physical schema history once it is introduced.
- `Base.metadata.create_all()` remains, but only for narrowly-scoped bootstrap/test convenience: the SQLite offline test double in `tests/test_audit_repository.py`, and genuinely disposable local development/test environments. It must **not** be used to create or evolve the real `healthcare_ai_fde_lab` schema once Alembic is adopted.

**This decision is documentation only.** Alembic is not installed, configured, or run as a result of this ADR — see Implementation Boundary below.

## Rationale
Alembic was selected over the alternatives because it integrates directly with the SQLAlchemy models already in place (no model changes required), maintains its own version-history table so "what schema version is installed" has a definite answer, supports both forward evolution and — where a change is genuinely safe to reverse — downgrade, and is capable of expressing every SQL Server-specific construct the target design requires (see SQL Server Considerations below), with the explicit understanding that generated output for constraints and indexes must always be reviewed by a person rather than trusted automatically (see Autogenerate Policy). It is also the more explainable choice for an FDE portfolio: a single, widely-recognized tool with a clear job, rather than a custom-built alternative that would need its own justification in an interview.

## Schema Ownership Model
Schema knowledge in this project is intentionally split across three layers, not owned by any single one:

- **Layer 1 — Canonical database documentation** (`docs/database/`): owns *design intent* — business meaning, field definitions, nullability rules, normalization, controlled vocabulary, constraint/index intent, and privacy/data-minimization boundaries. This layer does not change as a result of this ADR.
- **Layer 2 — SQLAlchemy ORM** (`src/db/`): owns the *application-facing schema expectation* — the Python mapping the running application code actually reads and writes through (`AuditRepository` and, in later Waves, additional repository classes).
- **Layer 3 — Alembic revisions** (future, not yet created): own the *physical schema evolution history* — what changed, in what sequence, which revision is currently installed on a given database, how version N becomes version N+1, and downgrade only where genuinely safe.

**The SQLAlchemy ORM alone is not the complete schema source of truth.** A model class describes intended shape; it cannot answer "which version is actually installed on this SQL Server instance right now" or "how do I get from version 7 to version 9." Only the Alembic revision chain (Layer 3), once it exists, can answer that.

## Autogenerate Policy
Alembic can generate a draft migration automatically by comparing the SQLAlchemy models against the current database (`--autogenerate`). **This output is a migration-draft assistant. It is not authoritative, and it must never be applied without review.**

For this project, every autogenerated revision must be explicitly reviewed for:

- primary keys
- foreign keys
- composite foreign keys
- filtered unique indexes
- CHECK constraints (including every `ISJSON(...)` constraint)
- `datetime2(3)` precision
- self-referencing foreign keys
- `NO ACTION` FK behavior
- constraint/index naming
- destructive changes (drops, narrowing type changes)
- column rename semantics (autogenerate typically sees a rename as a drop-and-add, which is destructive if applied literally)

This project does not claim Alembic can safely infer every database decision on its own, and it does not claim Alembic is categorically incapable of expressing composite foreign keys or CHECK constraints — it can express them once a person writes or corrects the operation. The policy is simply: **automatic output may assist; human review remains mandatory** before any migration is applied to a real database.

## Wave Boundary Policy
The approved implementation Waves ([[../database/data_model.md]] §16) remain unchanged by this ADR and must be respected by future migration work:

- Wave 1 and Wave 2 must not be combined into one large initial migration. Only Wave 1's own dependency tables (organization/lifecycle/core reference masters) are physically implemented in Wave 1.
- `dbo.workflow_runs` and `dbo.audit_events` must **not** be dropped or rebuilt merely to initialize Alembic during Wave 1. Their controlled replacement/rebuild is a Wave 2 concern (Case & Workflow Schema Expansion), consistent with the controlled-rebuild recommendation already approved in [[../database/migration_plan.md]].
- Required progression: Wave 1 migration(s) → validate → tests → review → commit → next Wave; then Wave 2 migration(s) → controlled `workflow_runs`/`audit_events` evolution/rebuild → contract-preservation validation (per `migration_plan.md` §6) → tests → review.

## SQL Server Considerations
Migrations may use ordinary Alembic operations, ordinary SQLAlchemy constructs, SQL Server-specific SQLAlchemy constructs, and explicit raw SQL only when genuinely required — explainable SQLAlchemy/Alembic operations are preferred, and raw SQL is not introduced without a specific reason. The target design's SQL Server-specific requirements that future migrations must be able to express include: `datetime2(3)` columns, filtered unique indexes, `ISJSON` CHECK constraints, composite foreign keys, self-referencing foreign keys, explicit constraint names, and `NO ACTION` FK delete behavior. All of these are expressible through Alembic operations; none of them are reliably produced by autogenerate without review (see Autogenerate Policy).

## Reference Data Policy
Schema migration and reference-data loading are separate concerns and must stay separate:

- Alembic owns **physical schema evolution** only — table, column, constraint, and index shape.
- [[../database/reference_data.md]] owns **reference/controlled vocabulary design** — what the valid seed values are and what they mean.
- Reference/business seed data is **not** automatically placed inside Alembic revision files. Migrations change shape; they do not, by default, also own populating business vocabulary content.
- The future idempotent reference-data loading mechanism (how `reference_data.md`'s controlled values actually get inserted and kept current) remains a separate, later implementation decision — not decided by this ADR.

## Rollback / Recovery Principles
Three distinct concepts, which must never be treated as interchangeable:

**A. Git / code rollback.** Source and documentation changes (including migration revision files themselves, once they exist) are reverted through Git, independent of database state.

**B. Alembic schema downgrade.** Used only where a migration is genuinely and safely reversible (e.g. adding a nullable column, adding an index). Not every migration will have a safe downgrade — a destructive change (dropping a column, narrowing a type, the Wave 2 controlled rebuild) must say so explicitly rather than imply a false safety net. Downgrade must never be assumed to restore data that was actually lost.

**C. Controlled prototype database rebuild.** For the current, synthetic-data-only local `healthcare_ai_fde_lab` database, rebuilding it from a known migration baseline (drop and recreate via Alembic) may be an acceptable recovery option — but only with explicit approval at the time, and only because the data involved is confirmed synthetic and disposable, not because rebuilding is generally an acceptable substitute for a real rollback.

## Schema Drift Controls
**Schema drift**, in plain language: the real SQL Server database structure no longer matches the schema that the version-controlled project expects.

Phase 1 controls, proportionate to a prototype's scale (no new monitoring infrastructure is introduced):

- Alembic's own revision/version history identifies exactly which revision is installed on a given database.
- Before any physical schema work in a session, the installed revision is checked against the latest revision in the repository.
- Alembic's comparison/check capability (comparing the live database against the current models) may be used as a review aid to catch unexpected differences.
- Manual schema changes made directly in SSMS, outside a version-controlled migration, are prohibited — this is a discipline rule, not a tooling feature, and is the single most effective drift-prevention measure regardless of what tooling exists.

## Consequences
- Once actually installed (not yet — see Implementation Boundary), Alembic adds one new dependency and a new configuration file/directory structure (`alembic.ini`, `migrations/`).
- Every future physical schema change must be authored as a reviewed migration revision, not a hand-run, unrecorded SQL statement.
- Not every migration will have a safe downgrade; destructive changes must be documented as such rather than implying reversibility that doesn't exist.
- The existing offline SQLite tests (`tests/test_audit_repository.py`) and their use of `create_database_schema()` are unaffected and remain unchanged.
- Establishes a clear, three-layer separation between design intent, application-facing ORM shape, and physical schema history, which future Waves build on rather than re-deciding.
- Requires a separate, explicitly approved implementation task — with step-by-step explanation suited to someone new to SQLAlchemy/Alembic — before any of this becomes real.

## Alternatives Considered

**Alternative A — Explicit versioned SQL migration scripts.** Strength: direct SQL Server control and high transparency — every statement is exactly what is intended, with no translation layer. Reason not selected as the primary mechanism: this project has no existing script-runner, so adopting it would mean building a custom version-tracking, ordering, and "what has already been applied" mechanism from scratch — effectively reinventing a smaller, less-proven version of what Alembic already provides. It also carries a higher risk of the ORM models and the hand-written SQL silently drifting apart, since nothing would automatically flag a mismatch. Alembic does not give up this strength — a migration written under Alembic can still contain explicit raw SQL wherever that is genuinely the clearest way to express something.

**Alternative B — `Base.metadata.create_all()` as the ongoing migration mechanism.** Strength: simple, and already working today for first-time schema creation in both the offline SQLite tests and the original live SQL Server bootstrap. Reason not selected as the migration mechanism: it cannot alter a table that already exists, keeps no revision history, has no concept of a migration chain, and offers no controlled downgrade or version tracking. Its own existing code comments already describe it as prototype-only. It remains valuable and is retained — but only in that original, narrower bootstrap/test role (see Decision above), not as a replacement for real schema evolution.

## Implementation Boundary

**DECIDED:** Alembic + SQLAlchemy is the approved schema migration mechanism for the real Phase 1 SQL Server database.

**NOT YET IMPLEMENTED:**
- The Alembic package is not installed.
- `alembic.ini` does not exist.
- `migrations/` does not exist.
- `env.py` does not exist.
- No revision file exists.
- No SQL Server migration has been executed under this mechanism.

A separate, explicitly approved learning-and-implementation task — with step-by-step explanation appropriate for someone introducing SQLAlchemy and Alembic for the first time — is required before Alembic is actually installed, initialized, or run against SQL Server. That future task, and every task after it that touches migrations, must: review every migration revision before it is executed, never trust autogenerate output blindly, never modify the SQL Server schema manually outside an approved migration, report migration/test results honestly, and never claim a migration succeeded unless it was actually tested.

## Related
- [[ADR-003-sql-server.md]]
- [[ADR-004-phase1-canonical-data-model.md]]
- [[../architecture.md]]
- [[../database/migration_plan.md]]
- [[../database/data_model.md]]
- [[../database/data_dictionary.md]]
- [[../database/reference_data.md]]
- [[../database/constraints_and_indexes.md]]
