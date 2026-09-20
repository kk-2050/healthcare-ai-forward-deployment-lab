<!--
File Name: migration_plan.md
Purpose: Wave 0 migration plan and persistence-contract preservation strategy for the Phase 1 canonical database model
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# Phase 1 Database Migration Plan — Wave 0

## 1. Status

**PLANNING DOCUMENT (Wave 0) — no schema, code, or data changes have occurred as a result of this document itself.** Wave 1 physical implementation has since been completed and validated through separate, explicitly approved tasks (Task 20A: authoring; Task 20B: SQL Server execution and validation) — see §17.C for the current, authoritative Wave 1 status.

This is Wave 0 of the approved Wave plan in [data_model.md §16](data_model.md#16-implementation-waves). It documents how the currently implemented two-table SQL Server persistence foundation relates to the approved v2.2 canonical 36-table model, and what must be true before Wave 1 begins. It does not itself create, alter, or drop any table, and it does not change any application code.

## 2. Purpose

The project already has a working, tested persistence foundation (`workflow_runs`, `audit_events`) validated against a real local Microsoft SQL Server instance. The canonical 36-table model is an approved design baseline, not yet implemented. This document exists so that later Waves evolve the existing implementation deliberately — preserving what already works — rather than replacing it blindly. It establishes: current-to-target mapping, dependency analysis, contract preservation, vocabulary migration, identifier strategy, synthetic-data handling, a test-preservation plan, and a rollback strategy.

## 3. Current Physical Baseline

Confirmed directly from source code (not from documentation) as of commit `4f473fcb2e7b792113a55b72dd035ca27c73591f`.

**Database:** Microsoft SQL Server, database `healthcare_ai_fde_lab` (see [ADR-003](../decisions/ADR-003-sql-server.md)).

**`dbo.workflow_runs`** — [src/db/models.py](../../src/db/models.py), class `WorkflowRunORM`:

| column | SQLAlchemy type | nullable | key |
|---|---|---|---|
| `trace_id` | `String(64)` | NO | PK |
| `case_id` | `String(64)` | NO | |
| `workflow_status` | `String(64)` | NO | |
| `human_review_required` | `Boolean` | NO | |
| `failure_category` | `String(64)` | YES | |
| `created_at_utc` | `DateTime` | NO | |
| `updated_at_utc` | `DateTime` | NO | |

**`dbo.audit_events`** — [src/db/models.py](../../src/db/models.py), class `AuditEventORM`:

| column | SQLAlchemy type | nullable | key |
|---|---|---|---|
| `event_id` | `String(64)` | NO | PK |
| `trace_id` | `String(64)` | NO | indexed (`ix_audit_events_trace_id`) |
| `case_id` | `String(64)` | NO | |
| `event_type` | `String(128)` | NO | |
| `event_category` | `String(64)` | NO | |
| `workflow_status` | `String(64)` | YES | |
| `processing_step` | `String(128)` | YES | |
| `failure_category` | `String(64)` | YES | |
| `occurred_at_utc` | `DateTime` | NO | |

Neither table has a physical foreign key between `audit_events.trace_id` and `workflow_runs.trace_id` — this is a documented, deliberate Phase 1 simplification (see the class docstring in `src/db/models.py`), not an oversight.

**Application-facing models** ([src/models/audit.py](../../src/models/audit.py)): `WorkflowRunSnapshot` and `AuditEvent` (Pydantic, `extra="forbid"`) mirror the ORM fields one-for-one, plus `AuditEventCategory` (str Enum): `WORKFLOW`, `HEALTHCARE_INTEGRATION`, `DETERMINISTIC_RULE`, `AI`, `HUMAN_REVIEW`, `ERROR`.

**Repository** ([src/db/repository.py](../../src/db/repository.py)): `AuditRepository`, injected `session_factory`, `PersistenceError` on any `SQLAlchemyError`. See §6 for the full behavioral contract.

**Critical finding — persistence is not wired to the workflow.** `src/workflow/graph.py`, `nodes.py`, and `state.py` contain no import of `src/db/*`, `AuditRepository`, `WorkflowRunSnapshot`, or `AuditEvent`. `CaseWorkflowState` ([src/workflow/state.py](../../src/workflow/state.py)) has no `trace_id` field at all, and nothing in `src/` generates a `trace_id`. `AuditRepository` is exercised today only by `tests/test_audit_repository.py` and by the (non-repository, scratchpad-only) Task 18B live SQL Server validation scripts, using hand-supplied synthetic `trace_id`/`case_id`/`event_id` values. This means: (a) the "contract" to preserve is the repository's own tested public API, not any live production call pattern, and (b) Wave 0 correctly requires no LangGraph-to-schema wiring, per [data_model.md §16](data_model.md#16-implementation-waves) Wave 0's own description.

**Local database state:** the local `healthcare_ai_fde_lab` database also contains synthetic rows written during the earlier Task 18B-6 live integration check (`trace_id = trace-task18b6-synthetic-001`, two audit events). Per that task's explicit policy, no cleanup DELETE was performed. See §9.

## 4. Target Design Baseline

The approved v2.2 canonical model: 36 tables, 3NF-first, documented in [data_model.md](data_model.md), [data_dictionary.md](data_dictionary.md), [reference_data.md](reference_data.md), and [constraints_and_indexes.md](constraints_and_indexes.md), decided in [ADR-004](../decisions/ADR-004-phase1-canonical-data-model.md). Key principles restated here only where they affect this plan: Case → Workflow Run → Audit Event hierarchy; every non-audit table carries the nine standard control fields; `audit_events` is append-only/immutable; two documented intentional denormalizations (`audit_events.case_id`, `audit_events.event_category_code`); Case Close ≠ Logical Delete; no raw FHIR/LLM persistence; synthetic data only.

## 5. Current-to-Target Schema Mapping

### 5.A `workflow_runs`

**Field count reconciliation** (recalculated directly from `src/db/models.py` and [data_dictionary.md](data_dictionary.md) — every current field is counted exactly once, in exactly one bucket below; no renamed field is double-counted as both a KEEP and an ADD, and no vocabulary-only change is counted as a new physical field):

| metric | count | fields |
|---|---:|---|
| current physical column count | 7 | `trace_id`, `case_id`, `workflow_status`, `human_review_required`, `failure_category`, `created_at_utc`, `updated_at_utc` |
| target physical column count | 23 | see [data_dictionary.md `workflow_runs`](data_dictionary.md#workflow_runs) |
| (A) same/rename-compatible, no vocabulary/FK change | 4 | `trace_id`, `human_review_required`, `created_at_utc`, `updated_at_utc` |
| (B) changed semantics/FK/type (same field, requires vocabulary migration and/or a new FK relationship) | 3 | `case_id` (gains FK), `workflow_status`→`workflow_status_code` (renamed + vocabulary + FK), `failure_category`→`failure_category_code` (renamed + vocabulary + FK) |
| (D) derived/replaced (current field has no direct 1:1 target counterpart) | 0 | — none for this table |
| (C) truly new target fields (no current counterpart at all) | 16 | `workflow_definition_id`, `next_action_code`, `processing_department_id`, `processing_location_id`, `initiated_by_component_code`, `started_at_utc`, `completed_at_utc`, `schema_version`, `metadata_json`, `created_by`, `updated_by`, `is_deleted`, `deleted_at_utc`, `deleted_by`, `delete_reason_code`, `delete_reason_text` |

Reconciliation: current (A+B+D = 4+3+0 = **7**) matches the current physical column count exactly. Target (current carried forward + new = 7+16 = **23**) matches the target physical column count exactly. `created_at_utc`/`updated_at_utc` are counted once each, in bucket A only — they are not also counted among the "new" control fields below.

| current_field | current_type | target_field | target_type | action | compatibility | notes |
|---|---|---|---|---|---|---|
| `trace_id` | `String(64)` | `trace_id` | `nvarchar(64)` PK | KEEP | Direct | Same identifier role, same physical length. |
| `case_id` | `String(64)` | `case_id` | `nvarchar(64)` FK → `prior_authorization_cases.case_id` | CHANGE FK | Compatible, needs new parent | Currently a plain string with no referenced table (no `prior_authorization_cases` table exists yet); becomes a real FK once that table exists (Wave 2). |
| `workflow_status` | `String(64)`, free string | `workflow_status_code` | `nvarchar(64)` FK → `workflow_statuses.workflow_status_code` | RENAME + CHANGE FK | Requires vocabulary migration | See §7 — current 5-value enum does not map 1:1 to the target 4-value status vocabulary. |
| `human_review_required` | `Boolean` | `human_review_required` | `bit` | KEEP | Direct | No change. |
| `failure_category` | `String(64)`, nullable | `failure_category_code` | `nvarchar(64)` FK → `failure_categories.failure_category_code`, nullable | RENAME + CHANGE FK | Requires vocabulary migration | Current values are unprefixed (`PROVIDER_FAILED`, `HTTP_ERROR`, …); target values are domain-prefixed (`AI_PROVIDER_FAILED`, `FHIR_HTTP_ERROR`, …). See §7. |
| `created_at_utc` | `DateTime` | `created_at_utc` | `datetime2(3)` | KEEP | Direct (precision widens) | Target adds explicit millisecond precision; existing UTC-naive/aware values remain semantically compatible. |
| `updated_at_utc` | `DateTime` | `updated_at_utc` | `datetime2(3)` | KEEP | Direct | Same as above. |
| — (none) | — | `workflow_definition_id` | `nvarchar(64)` FK, NOT NULL | ADD | New required column | No workflow-versioning concept exists in current code at all; requires `workflow_definitions` (Wave 2) to exist first, plus an application decision on which definition ID a run was processed under. |
| — (none) | — | `next_action_code` | `nvarchar(64)` FK, nullable | ADD | New nullable column | Corresponds to the business-facing action (`CONTINUE_PROCESSING`, `REQUEST_MISSING_INFORMATION`, `ROUTE_HUMAN_REVIEW`, `COMPLETE_WORKFLOW`) that today only exists implicitly as a LangGraph routing decision (see `route_after_*` functions in `src/workflow/graph.py`); no current field captures it. |
| — (none) | — | `processing_department_id` | `nvarchar(64)` FK, nullable | ADD | New nullable column | Not present in current model or workflow state; requires `departments` (Wave 1). |
| — (none) | — | `processing_location_id` | `nvarchar(64)` FK, nullable | ADD | New nullable column | Same as above; requires `locations` (Wave 1). |
| — (none) | — | `initiated_by_component_code` | `nvarchar(64)` FK, NOT NULL | ADD | New required column | Requires `source_components` (Wave 1); current code has no concept of "which internal component started this run." |
| — (none) | — | `started_at_utc` | `datetime2(3)`, NOT NULL | ADD | New required column | `created_at_utc` currently plays this role informally; target separates row-creation time from workflow-start time. |
| — (none) | — | `completed_at_utc` | `datetime2(3)`, nullable, conditionally required | ADD | New column, application-enforced rule | Not present today; must be populated whenever `workflow_status_code` is terminal (`COMPLETED`/`FAILED`) — enforced at the application layer, not by a CHECK constraint (see [constraints_and_indexes.md §4](constraints_and_indexes.md)). |
| — (none) | — | `schema_version` | `nvarchar(32)`, NOT NULL | ADD | New required column | No current schema-versioning field. |
| — (none) | — | `metadata_json` | `nvarchar(max)`, nullable | ADD | New nullable column | No current extension field; must never carry raw FHIR/LLM content per [data_model.md §11](data_model.md#11-ai-persistence-boundary). |
| — (none) | — | seven new control fields (`created_by`, `updated_by`, `is_deleted`, `deleted_at_utc`, `deleted_by`, `delete_reason_code`, `delete_reason_text`) — the remaining two of the nine standard control fields, `created_at_utc`/`updated_at_utc`, already exist today and are counted above as KEEP, not here | see [data_dictionary.md](data_dictionary.md) | ADD | New required/conditional columns | Current table has none of the logical-delete control fields; today a row is never logically deleted at all. |

### 5.B `audit_events`

**Field count reconciliation** (recalculated directly from `src/db/models.py` and [data_dictionary.md](data_dictionary.md)):

| metric | count | fields |
|---|---:|---|
| current physical column count | 9 | `event_id`, `trace_id`, `case_id`, `event_type`, `event_category`, `workflow_status`, `processing_step`, `failure_category`, `occurred_at_utc` |
| target physical column count | 19 | see [data_dictionary.md `audit_events`](data_dictionary.md#audit_events) |
| (A) same/rename-compatible, no vocabulary/FK change | 2 | `event_id`, `occurred_at_utc` |
| (B) changed semantics/FK/type (same field, requires vocabulary migration and/or a new FK relationship, but still a direct 1:1 value mapping) | 6 | `trace_id` (gains composite FK), `case_id` (gains composite FK), `event_type`→`event_type_code` (renamed + vocabulary + composite FK), `event_category`→`event_category_code` (renamed + vocabulary + composite FK), `workflow_status`→`workflow_status_code` (renamed + vocabulary + FK), `failure_category`→`failure_category_code` (renamed + vocabulary + FK) |
| (D) derived/replaced (current field has no direct 1:1 target counterpart — requires new translation logic, not a value rename) | 1 | `processing_step`→`workflow_step_id` (see notes below — requires a LangGraph-step-to-`step_code` translation layer, an Open Decision; not a simple rename) |
| (C) truly new target fields (no current counterpart at all) | 10 | `source_component_code`, `actor_type_code`, `actor_identifier`, `result_code`, `reason_code`, `related_event_id`, `schema_version`, `metadata_json`, `created_at_utc`, `created_by` |

Reconciliation: current (A+B+D = 2+6+1 = **9**) matches the current physical column count exactly. Target (current carried forward + new = 9+10 = **19**) matches the target physical column count exactly.

| current_field | current_type | target_field | target_type | action | compatibility | notes |
|---|---|---|---|---|---|---|
| `event_id` | `String(64)` | `event_id` | `nvarchar(64)` PK | KEEP | Direct | No change. |
| `trace_id` | `String(64)`, indexed, no physical FK | `trace_id` | `nvarchar(64)`, part of composite FK → `workflow_runs(trace_id, case_id)` | CHANGE FK | Compatible, needs new constraint | Becomes part of the planned composite FK once `workflow_runs` carries a `UNIQUE(trace_id, case_id)` constraint (see [constraints_and_indexes.md §5](constraints_and_indexes.md)). |
| `case_id` | `String(64)`, no physical FK | `case_id` | `nvarchar(64)`, part of composite FK → `workflow_runs(trace_id, case_id)` | CHANGE FK | Compatible, needs new constraint | This is the documented intentional denormalization ([data_model.md §7](data_model.md#7-normalization-and-intentional-denormalization), Denormalization 1) — already present today in spirit (case_id is duplicated on the event row); the target formalizes it with a composite FK. |
| `event_type` | `String(128)`, free string | `event_type_code` | `nvarchar(64)`, part of composite FK → `event_types(event_type_code, event_category_code)` | RENAME + CHANGE TYPE + CHANGE FK | Requires vocabulary migration | Current free-text values (e.g. `synthetic_task18b6_workflow_run_created`) are test/scratchpad-only, not a fixed vocabulary; target requires values drawn from `event_types` (§7). Also narrows `String(128)` → `nvarchar(64)`; existing longer test values would need shortening. |
| `event_category` | `String(64)` enum-backed | `event_category_code` | `nvarchar(64)`, part of the same composite FK | RENAME + CHANGE FK | Requires vocabulary migration | Current `AuditEventCategory` values (`WORKFLOW`, `HEALTHCARE_INTEGRATION`, `DETERMINISTIC_RULE`, `AI`, `HUMAN_REVIEW`, `ERROR`) do not match target `event_categories` codes (`WORKFLOW`, `FHIR`, `RULE`, `AI`, `HUMAN`, `PERSISTENCE`) 1:1 — see §7. This is the documented intentional denormalization ([data_model.md §7](data_model.md#7-normalization-and-intentional-denormalization), Denormalization 2). |
| `workflow_status` | `String(64)`, nullable | `workflow_status_code` | `nvarchar(64)` FK, nullable | RENAME + CHANGE FK | Requires vocabulary migration | Same underlying migration as `workflow_runs.workflow_status` above. |
| `processing_step` | `String(128)`, nullable, free string | `workflow_step_id` | `nvarchar(64)` FK → `workflow_definition_steps.workflow_step_id`, nullable | DERIVE | Requires a translation layer, not a rename | Current values are internal LangGraph node/step names (e.g. `healthcare_evidence_retrieved`, `evidence_consistency_evaluated`). Per [data_model.md §12](data_model.md#12-workflow-action-vs-langgraph-node), internal node names must never be persisted directly as business codes. A future translation layer must map each LangGraph step to a `workflow_definition_steps.step_code` (e.g. `FHIR_RETRIEVAL`, `EVIDENCE_CONSISTENCY`, `COMPLETENESS_CHECK`) and resolve it to the surrogate `workflow_step_id` for the active `workflow_definition_id`. The exact mapping is now RESOLVED (Task 21A, [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md)); building the translation layer/module itself remains Wave 2 implementation work. |
| `failure_category` | `String(64)`, nullable | `failure_category_code` | `nvarchar(64)` FK, nullable | RENAME + CHANGE FK | Requires vocabulary migration | Same migration as `workflow_runs.failure_category`. |
| — (none) | — | `event_category_code` composite consistency | — | REPLACED BY RELATIONSHIP | — | Already listed above; called out again because it is a *relationship*, not a scalar field, that must be added (composite FK), not merely a renamed column. |
| — (none) | — | `source_component_code` | `nvarchar(64)` FK, NOT NULL | ADD | New required column | No current field records which component emitted the event; requires `source_components` (Wave 1). |
| — (none) | — | `actor_type_code` | `nvarchar(64)` FK, NOT NULL | ADD | New required column | No current concept of actor type; requires `actor_types` (Wave 1). |
| — (none) | — | `actor_identifier` | `nvarchar(128)`, nullable | ADD | New nullable column | No current field; per [reference_data.md §21](reference_data.md#21-actor-identifier-convention) uses synthetic identifiers only in Phase 1. |
| — (none) | — | `result_code` | `nvarchar(64)` FK, NOT NULL | ADD | New required column | No current field distinguishes success/failure/match/mismatch as a controlled code; requires `result_codes` (Wave 1). |
| — (none) | — | `reason_code` | `nvarchar(64)` FK, nullable | ADD | New nullable column | No current field; requires `reasons` (Wave 1). Distinct from `failure_category_code` — see [data_model.md §9](data_model.md#9-failure-vs-business-reason). |
| — (none) | — | `related_event_id` | `nvarchar(64)` FK → `audit_events.event_id` (self), nullable | ADD | New nullable self-referencing column | Supports immutable-correction chains ("corrections are new events, never updates/deletes"); no current equivalent, since the current table has never needed a correction mechanism. |
| `occurred_at_utc` | `DateTime` | `occurred_at_utc` | `datetime2(3)` | KEEP | Direct (precision widens) | No change in meaning. |
| — (none) | — | `schema_version` | `nvarchar(32)`, NOT NULL | ADD | New required column | No current schema-versioning field. |
| — (none) | — | `metadata_json` | `nvarchar(max)`, nullable | ADD | New nullable column | No current extension field; same data-minimization rule as `workflow_runs.metadata_json`. |
| — (none) | — | `created_at_utc`, `created_by` | `datetime2(3)` / `nvarchar(128)`, both NOT NULL | ADD | New required columns | Target `audit_events` intentionally has **only** these two control fields (append-only — no `updated_*`, no `is_deleted`, no delete fields at all, per the table note in [data_dictionary.md](data_dictionary.md)). Current table has neither `created_at_utc` nor `created_by`; `occurred_at_utc` today informally serves both "when it happened" and "when it was recorded" roles. |

**Composite FK requirements identified for `audit_events`:** (1) `(trace_id, case_id)` → `workflow_runs(trace_id, case_id)`, requiring `UNIQUE(trace_id, case_id)` on `workflow_runs`; (2) `(event_type_code, event_category_code)` → `event_types(event_type_code, event_category_code)`, requiring `UNIQUE(event_type_code, event_category_code)` on `event_types`. Both are already specified in [constraints_and_indexes.md §5](constraints_and_indexes.md); neither exists physically today because neither `event_types` nor a unique constraint on `workflow_runs` exists yet.

## 6. Repository Contract Preservation

**Contract preservation means preserving externally observable repository behavior, not the physical schema.** `AuditRepository`'s public methods may be reimplemented against the target schema in a later Wave as long as each behavior below still holds.

| behavior | current test(s) | target behavior | interface unchanged? | implementation will change? | migration regression test required? |
|---|---|---|---|---|---|
| Save a new workflow run | `test_workflow_run_can_be_saved` | Same: `save_workflow_run(snapshot)` succeeds for a new `trace_id` | Yes, if `WorkflowRunSnapshot` gains new required fields the call signature is unaffected (fields, not signature, change) | Yes — internally becomes an INSERT against the target `workflow_runs` shape, likely needing default values for new required columns | Yes |
| Read a workflow run by `trace_id` | `test_workflow_run_can_be_retrieved_by_trace_id` | Same: `get_workflow_run(trace_id)` returns a full snapshot | Yes | Yes — SELECT must join/resolve additional target columns | Yes |
| Update (upsert) an existing run | `test_saving_same_trace_id_updates_instead_of_duplicating` | Same: saving a second snapshot for the same `trace_id` updates in place, never duplicates | Yes | Yes — `session.get()` + field assignment pattern likely still applies but against more columns | Yes |
| Missing run returns `None` | `test_missing_workflow_run_returns_none` | Same: no fabricated result | Yes | No | Yes (cheap regression) |
| Append one audit event | `test_audit_event_can_be_appended` | Same | Yes | Yes — more required columns to populate | Yes |
| Multiple events retained (not overwritten) | `test_multiple_audit_events_are_retained` | Same | Yes | No (already correct by design — INSERT-only) | Yes |
| Chronological retrieval, stable tiebreak | `test_audit_events_are_returned_in_chronological_order` | Same ordering guarantee (`occurred_at_utc`, then `event_id`) | Yes | No | Yes |
| Events isolated by `trace_id` | `test_audit_events_are_isolated_by_trace_id` | Same | Yes | No | Yes |
| Duplicate `event_id` rejected deterministically | `test_duplicate_event_id_fails_deterministically` | Same: `PersistenceError`, never silent overwrite | Yes | No (PK-violation-based enforcement still applies) | Yes |
| Rollback on failure + repository still usable | `test_failed_write_rolls_back_and_repository_still_usable` | Same | Yes | No (per-call session/transaction pattern already matches this requirement) | Yes |
| Caller's input objects never mutated | `test_repository_does_not_mutate_workflow_run_snapshot_input`, `..._audit_event_input` | Same | Yes | No | Yes |
| No raw clinical/FHIR/AI/secret/approval fields on persistence models | `test_audit_models_contain_no_raw_clinical_or_fhir_fields`, `..._no_secret_or_connection_fields`, `..._no_approval_denial_fields` | Same prohibition extends to every new target field (`metadata_json` allowlist, no `workflow_step_id` free text, etc.) | N/A (a data-shape guarantee, not a call-signature guarantee) | No | Yes — the forbidden-field set should be re-checked against whatever new Pydantic model(s) back the expanded columns |
| Repository has no AI dependency | `test_repository_uses_no_ai_dependency` | Same | N/A | No | Yes |
| No live network access from offline repository tests | `test_repository_tests_require_no_live_sql_server` | Same | N/A | No | Yes |
| Composite FK consistency (`trace_id`+`case_id`, `event_type_code`+`event_category_code`) | none today (no such constraint exists) | New behavior: a mismatched pair must be rejected | New | New | New test required in the Wave that adds the constraint |

No behavior in this table requires an interface change to `AuditRepository`'s method signatures. Every "implementation will change" entry is driven by new required columns needing values, not by a change in what the caller observes for existing fields.

## 7. Status / Code Vocabulary Mapping

### 7.A Workflow status

| current value (`WorkflowStatus`, `src/workflow/state.py`) | current meaning | target domain | target value | migration rule |
|---|---|---|---|---|
| `PROCESSING` | Actively executing | `workflow_statuses.workflow_status_code` | `PROCESSING` | Direct match — no change needed. |
| `HUMAN_REVIEW_REQUIRED` | Paused pending a human reviewer | `workflow_statuses.workflow_status_code` | `HUMAN_REVIEW_REQUIRED` | Direct match — no change needed. |
| `COMPLETE` | Deterministic processing finished, no human review needed | `workflow_statuses.workflow_status_code` | `COMPLETED` | Rename only (`COMPLETE` → `COMPLETED`); already documented in [reference_data.md §4](reference_data.md#4-workflow_statuses). |
| `AI_ANALYSIS_REQUIRED` | Transient: about to invoke AI | **Not a workflow-run status** — `workflow_definition_steps.step_code` (`AI_ROUTING`/`AI_ANALYSIS`) or an `event_types` value | n/a as a status | Do not force into `workflow_statuses`. Represent as a workflow step and/or an audit event type instead. |
| `AI_ANALYSIS_COMPLETE` | AI-assisted step finished successfully; run continues | **Not a workflow-run status** — an `event_types` value (`AI_ANALYSIS_SUCCEEDED`) | n/a as a status | Same as above; the run's actual `workflow_status_code` at this point is still `PROCESSING` (or moves to `COMPLETED`/`HUMAN_REVIEW_REQUIRED` next). |
| *(none currently exists)* | A terminal technical/workflow failure where safe automated continuation cannot be established | `workflow_statuses.workflow_status_code` | `FAILED` | **APPROVED target semantics (RESOLVED — see [reference_data.md §4](reference_data.md#4-workflow_statuses), the authoritative source of truth).** `FAILED` is reserved for a terminal technical/workflow failure where safe automated continuation **or** successful creation/routing of a Human-in-the-Loop review task cannot be established. It is not a catch-all for every technical failure. |
| *(none currently exists)* | Missing required information | Not a `workflow_status_code` — represented via `rule_evaluations`, `prior_authorization_cases.case_status_code = PENDING_INFORMATION`, and `next_action_code = REQUEST_MISSING_INFORMATION` | n/a | `INCOMPLETE` is intentionally not a target workflow-run status; current code likewise has no `INCOMPLETE` `WorkflowStatus` value, so there is no current-to-target gap here — both already agree. |

**Current → target migration behavior for `FAILED` (RESOLVED):** today, every failure path in `src/workflow/nodes.py` (FHIR retrieval failure, evidence mismatch, AI provider failure, AI output-validation failure) routes to `human_review_required_node`, setting `WorkflowStatus.HUMAN_REVIEW_REQUIRED` — confirmed directly in source. **That mapping remains correct and does not change**: whenever a failure is classified (`failure_category_code` populated) and the workflow successfully creates/routes a human-review task, the target `workflow_status_code` is `HUMAN_REVIEW_REQUIRED`, exactly as today. `FAILED` is a genuinely new terminal semantic that applies only to the narrower case where that safe human-review fallback itself cannot be established — for example, a persistence/orchestration failure that prevents the workflow from reliably creating or routing the review task at all. No current code path exercises this narrower case today; introducing one (if ever needed) is separate workflow-graph behavior work, not a Wave 0 documentation action, and is not required for Wave 1 or Wave 2 schema work — `workflow_status_code = FAILED` simply remains an unused-but-valid target value until/unless such a path is added.

**Examples (non-normative, illustrating the distinction only):**
- FHIR provider call fails → failure is classified → workflow successfully creates/routes a human review task → `workflow_status_code = HUMAN_REVIEW_REQUIRED`.
- AI structured-output validation fails → failure is classified → workflow successfully routes to human review → `workflow_status_code = HUMAN_REVIEW_REQUIRED`.
- A persistence/orchestration failure prevents both safe automated continuation and reliable human-review routing → `workflow_status_code = FAILED`.

### 7.B Audit event category

| current value (`AuditEventCategory`, `src/models/audit.py`) | target `event_categories.event_category_code` | migration rule |
|---|---|---|
| `WORKFLOW` | `WORKFLOW` | Direct match. |
| `HEALTHCARE_INTEGRATION` | `FHIR` | Rename. |
| `DETERMINISTIC_RULE` | `RULE` | Rename. |
| `AI` | `AI` | Direct match. |
| `HUMAN_REVIEW` | `HUMAN` | Rename. |
| `ERROR` | **No target equivalent — RESOLVED, by design (see [reference_data.md §10](reference_data.md#10-event_categories), the authoritative source of truth)** | The target model does not seed or use a generic `ERROR` event category. Events remain categorized by functional domain (`WORKFLOW`, `FHIR`, `RULE`, `AI`, `HUMAN`, `PERSISTENCE`) — i.e. *where/what domain* the event belongs to — while `failure_category_code` separately carries *why/how* it failed. **Migration rule:** current `AuditEventCategory.ERROR` values must **not** become a target `ERROR` category (none exists); at whatever future Wave `event_category_code` becomes a real FK, each current `ERROR`-categorized event must instead be translated to the functional-domain category matching what actually failed (e.g. an AI failure recorded today as `ERROR` becomes `AI` at that time, with `failure_category_code` carrying the specific classification). Current code still defines `AuditEventCategory.ERROR` and at least one existing test fixture (`tests/test_audit_repository.py`) uses it — **that fixture is explicitly left unchanged by Task 19C**; no test code is modified by this planning document. |

### 7.C Failure categories

| current value | source enum | target `failure_categories.failure_category_code` | migration rule |
|---|---|---|---|
| `HTTP_ERROR` | `FHIRIntegrationFailureType` (`src/integrations/fhir_models.py`) | `FHIR_HTTP_ERROR` | Add `FHIR_` prefix. |
| `MALFORMED_JSON` | same | `FHIR_MALFORMED_JSON` | Add `FHIR_` prefix. |
| `INVALID_SCHEMA` | same | `FHIR_INVALID_SCHEMA` | Add `FHIR_` prefix. |
| `UNSUPPORTED_RESOURCE_TYPE` | same | `FHIR_UNSUPPORTED_RESOURCE_TYPE` | Add `FHIR_` prefix. |
| `MISSING_SERVICE_REQUEST` | same | `FHIR_MISSING_SERVICE_REQUEST` | Add `FHIR_` prefix. |
| `BROKEN_CONDITION_REFERENCE` | same | `FHIR_BROKEN_CONDITION_REFERENCE` | Add `FHIR_` prefix. |
| `PROVIDER_FAILED` | `AIAnalysisFailureType` (`src/ai/contracts.py`) | `AI_PROVIDER_FAILED` | Add `AI_` prefix. |
| `OUTPUT_VALIDATION_FAILED` | same | `AI_OUTPUT_INVALID` | Rename (not a simple prefix — wording also changes). |
| *(none currently exists)* | — | `PERSISTENCE_ERROR` | New; no current code raises a classified persistence failure category (the current `PersistenceError` exception has no associated failure-category code). |

### 7.D Evidence mismatch reasons

| current value (`EvidenceMismatchReason`, `src/models/evidence.py`) | target `reasons.reason_code` | migration rule |
|---|---|---|
| `SERVICE_CODE_MISMATCH` | `EVIDENCE_MISMATCH_SERVICE_CODE` | Rename (prefix reordered: domain-first in target). |
| `DIAGNOSIS_CODE_MISMATCH` | `EVIDENCE_MISMATCH_DIAGNOSIS_CODE` | Rename, same pattern. |
| `DOCUMENTATION_NOT_FOUND` | `EVIDENCE_DOCUMENT_NOT_FOUND` | Rename — wording also changes (`DOCUMENTATION` → `DOCUMENT`). |

### 7.E AI task types

| current value (`AITask`, `src/models/ai.py`) | target `ai_task_types.code` | migration rule |
|---|---|---|
| `summarize_narrative` | `SUMMARIZE_NARRATIVE` | Casing only (lowercase → uppercase); same identifier. |
| `identify_ambiguity` | `IDENTIFY_AMBIGUITY` | Casing only. |
| `identify_text_inconsistencies` | `IDENTIFY_TEXT_INCONSISTENCIES` | Casing only. |
| `suggest_clarifying_questions` | `SUGGEST_CLARIFYING_QUESTIONS` | Casing only. |

### 7.F Event types

No current code defines a fixed "event type" vocabulary at all — `event_type` today is whatever free-text string a caller supplies (e.g. test fixtures use `workflow_completed`, `synthetic_task18b6_workflow_run_created`). The target `event_types` vocabulary ([reference_data.md §11](reference_data.md#11-event_types)) is entirely new controlled data with no current equivalent to migrate *from*; this is an ADD, not a rename, for every value.

## 8. Identifier Strategy

Confirmed from code: `trace_id`, `case_id`, and `event_id` are all plain `str` fields with `min_length=1` validation (`src/models/audit.py`, `src/models/case.py`). Only `AuditEvent.event_id` has generation logic (`default_factory=lambda: str(uuid.uuid4())`); `trace_id` and `case_id` have **no** generation logic anywhere in `src/` — they are supplied by the caller (tests, or the Task 18B scratchpad scripts), never derived from a live workflow run, since `CaseWorkflowState` does not even carry a `trace_id` field.

**Target direction** ([data_model.md §14](data_model.md#14-identifier-strategy)): entity/run/event identifiers are application-generated UUID/string identifiers; reference/master values are stable, human-readable business codes.

**Compliance assessment:**
- `event_id`: already compliant (UUID4-generated by default).
- `trace_id`, `case_id`: format is already compliant (opaque application-generated strings), but **no generation point currently exists** — this is a gap in workflow wiring (out of Wave 0 scope, see §16), not a format problem.
- Reference/master codes (`workflow_status_code`, `event_type_code`, etc.): do not exist as physical columns yet; the *vocabulary* is defined in `reference_data.md` using stable readable codes, consistent with the target direction.

**No identifier changes are made in Wave 0.**

## 9. Current Synthetic Data Handling

The local `healthcare_ai_fde_lab` SQL Server database currently contains synthetic Task 18B-6 validation rows (`trace_id = trace-task18b6-synthetic-001`, one `workflow_runs` row, two `audit_events` rows). **This document does not delete, alter, or migrate those rows.** They remain in place, exactly as Task 18B-6 left them, per that task's explicit "no cleanup DELETE" policy.

Two future strategies were assessed for how a later Wave should treat the *physical schema* (not the application/repository behavior, which is separately preserved per §6):

**A. In-place migration** (`ALTER TABLE` the existing `workflow_runs`/`audit_events` to add target columns and constraints incrementally):
- *Benefits:* preserves the existing synthetic rows without any data-copy step; smallest possible diff per Wave; each `ALTER` can be reviewed and tested independently.
- *Risks:* SQL Server `ALTER TABLE ... ADD` for new NOT NULL columns requires a default or a two-step nullable-then-backfill-then-NOT-NULL process; composite FK additions require the existing two synthetic rows to already satisfy the new constraint (they currently would not, e.g. no `workflow_definition_id` exists for them).
- *Test impact:* the SQLite-based offline test suite (`tests/test_audit_repository.py`) uses `create_database_schema()` (`Base.metadata.create_all`) against a fresh engine every test run, so it is unaffected either way; only the live SQL Server integration check (Task 18B-style) would need to handle the existing rows.
- *Migration complexity:* moderate — each column/constraint addition is small, but ordering matters (parent reference tables must exist before FKs can be added).
- *Do the synthetic rows matter?* Only as a test case for "does the migration handle pre-existing rows correctly" — they carry no business value and are not depended on by any test today.

**B. Controlled prototype schema rebuild** (drop and recreate `workflow_runs`/`audit_events` in their target form once the target schema is ready for that Wave):
- *Benefits:* avoids incremental `ALTER TABLE` complexity entirely; the target schema can be created cleanly via `Base.metadata.create_all()` against new ORM models, exactly like the offline tests already do.
- *Risks:* destroys the existing synthetic Task 18B-6 rows; requires explicit approval before any DROP, per this project's destructive-action discipline.
- *Test impact:* none beyond re-running the existing live-validation pattern (Task 18B-style) against the new schema afterward.
- *Migration complexity:* lower — a clean create is simpler to reason about and test than a sequence of in-place alterations for a prototype with no real production data.
- *Do the synthetic rows matter?* No — they were always disposable validation evidence, not data the application depends on, and their sole documented purpose (proving the repository could round-trip against a real SQL Server instance) is fully satisfied and preserved as this document's §3/§6 finding, independent of whether the rows themselves survive.

**Recommendation for this Phase 1 prototype: Strategy B (controlled prototype schema rebuild), performed explicitly and only in the Wave that first implements target `workflow_runs`/`audit_events` (Wave 2), never automatically and never without explicit approval at that time.** This is a prototype, not a production system with real data to preserve; a clean rebuild is simpler and lower-risk than incremental `ALTER` sequences for a two-table schema that is about to gain a dozen new columns and two composite FKs. This recommendation concerns only the *disposable rows* — it does not change §6's requirement that `AuditRepository`'s observable behavior (its method contracts) must still pass its full regression suite afterward.

## 10. Dependency / Migration Order

Validated against the actual FK columns documented in [data_dictionary.md](data_dictionary.md) for `workflow_runs` and `audit_events` (not assumed from the task's example list).

**`workflow_runs` depends on:** `prior_authorization_cases`, `workflow_definitions`, `workflow_statuses`, `workflow_actions` (nullable), `failure_categories` (nullable), `departments` (nullable), `locations` (nullable), `source_components`.

**`audit_events` depends on:** `workflow_runs`, `prior_authorization_cases` (denormalized), `event_types`, `event_categories` (denormalized, via the `event_types` composite), `workflow_statuses` (nullable), `workflow_definition_steps` (nullable), `source_components`, `actor_types`, `result_codes`, `failure_categories` (nullable), `reasons` (nullable), `audit_events` itself (self, `related_event_id`, nullable).

Full dependency-safe creation order (all 36 tables, tier by tier):

- **Tier 0 — pure reference masters (no dependencies):** `countries`, `case_statuses`, `reasons`, `workflow_statuses`, `workflow_actions`, `requirement_types`, `document_types`, `event_categories`, `actor_types`, `source_components`, `result_codes`, `failure_categories`, `human_review_statuses`, `human_review_outcomes`, `discovery_item_types`, `ai_task_types`.
- **Tier 1:** `clients` (nullable FK to `countries`), `workflow_definitions`, `event_types` (depends on `event_categories`).
- **Tier 2:** `departments` (depends on `clients`, self, `locations` — nullable FKs avoid a hard circular dependency), `locations` (depends on `clients`, `countries`), `workflow_definition_steps` (depends on `workflow_definitions`, `source_components`), `requirement_sets` (depends on `clients`, `workflow_definitions`).
- **Tier 3:** `prior_authorization_cases` (depends on `clients`, `departments`, `locations`, `case_statuses`, `source_components`, `reasons`), `requirement_rules` (depends on `requirement_sets`, `requirement_types`, `document_types`), `client_requirement_intakes` (depends on `clients`).
- **Tier 4:** `workflow_runs` (see above), `case_diagnoses`, `case_documents` (both depend on `prior_authorization_cases`, `source_components`/`document_types`), `client_requirement_items` (depends on `client_requirement_intakes`, `discovery_item_types`).
- **Tier 5:** `rule_evaluations`, `integration_executions`, `ai_analysis_runs`, `human_reviews`, `audit_events` (all depend on `workflow_runs` and `prior_authorization_cases`, plus their respective vocabulary tables from Tiers 0–2).
- **Tier 6:** `ai_analysis_tasks` (depends on `ai_analysis_runs`, `ai_task_types`, `result_codes`).

This order is consistent with, and does not require changing, the approved Wave plan (§11).

## 11. Wave Boundary Review

The approved Wave plan ([data_model.md §16](data_model.md#16-implementation-waves)) already aligns with the dependency tiers above:

- **Wave 1** (Organization, Lifecycle & Core Reference Foundation) delivers essentially all of Tier 0, plus `clients`/`departments`/`locations`/`countries` — sufficient parent data for Wave 2.
- **Wave 2** (Case & Workflow Schema Expansion) delivers `prior_authorization_cases`, `workflow_definitions`/`workflow_definition_steps`, target `workflow_runs`, and target `audit_events` together — which is dependency-correct only if `workflow_definitions` and `workflow_definition_steps` are created **before** `workflow_runs` and `audit_events` *within* Wave 2 (both depend on them). This is an intra-Wave ordering note, not a Wave-boundary change.
- **Waves 3–6** match Tiers 3–6 respectively (requirements, integration/AI/human review, client intake, hardening) with no dependency conflicts found.

**One Wave-boundary refinement was required and applied (Task 21B):** `document_types` (originally Wave 3, per Tier 0's dependency-order listing) was pulled forward into Wave 2 because `case_documents.document_type_code` — a Wave 2 table's required, NOT NULL column — references it. A Wave must be internally dependency-consistent; `document_types` has no dependencies of its own, so it moved to the earliest Wave that needs it, exactly like `case_statuses` was already pulled into Wave 1 for `prior_authorization_cases`' sake. See [§17.D](#17d-wave-2-physical-implementation--complete) for the executed result. Aside from this one table, no other Wave-boundary redesign was required.

## 12. Test Preservation Matrix

| behavior | existing test | test to preserve | future test to add | Wave to add it | SQL Server-specific validation required |
|---|---|---|---|---|---|
| Valid insert (workflow run) | `test_workflow_run_can_be_saved` | Yes | Insert against target schema with all new required columns populated | Wave 2 | Yes — confirm SQL Server accepts the expanded column set. |
| Read | `test_workflow_run_can_be_retrieved_by_trace_id` | Yes | Read-back of every new target column | Wave 2 | Yes |
| Update/upsert | `test_saving_same_trace_id_updates_instead_of_duplicating` | Yes | Upsert leaves control fields (`created_at_utc`, `created_by`) untouched while updating `updated_at_utc`/`updated_by` | Wave 2 | Yes |
| Duplicate event rejection | `test_duplicate_event_id_fails_deterministically` | Yes | Same, against target `audit_events` | Wave 2 | Yes |
| Chronological event retrieval | `test_audit_events_are_returned_in_chronological_order` | Yes | Same, against target `audit_events` | Wave 2 | No (behavior is SQLAlchemy `ORDER BY`, not SQL Server-specific) |
| Rollback | `test_failed_write_rolls_back_and_repository_still_usable` | Yes | Same, against target schema | Wave 2 | Yes — confirm SQL Server transaction rollback behaves identically to SQLite in tests. |
| Reuse after rollback | `test_failed_write_rolls_back_and_repository_still_usable` | Yes | Same | Wave 2 | Yes |
| FK rejection | none today (no FKs exist) | N/A | New: inserting a `workflow_runs.case_id` with no matching `prior_authorization_cases` row must fail | Wave 2 | Yes — FK enforcement is a SQL Server engine behavior, not exercised by current SQLite offline tests unless FKs are explicitly enabled there too. |
| Composite FK consistency | none today | N/A | New: `audit_events(trace_id, case_id)` mismatched against `workflow_runs(trace_id, case_id)` must fail; same for `(event_type_code, event_category_code)` | Wave 2 (once composite FKs are added) | Yes |
| Control-field lifecycle validation | none today (no control fields exist on these two tables) | N/A | New: `is_deleted=1` requires `deleted_at_utc`/`deleted_by`/`delete_reason_code` populated (see [constraints_and_indexes.md §2](constraints_and_indexes.md)) | Wave 2 (or wherever logical delete is first exercised) | Partial — the CHECK constraint itself is SQL Server-enforced; application-side validation should also be tested offline. |
| Logical-delete behavior | none today | N/A | New: a logically deleted `workflow_runs` row is excluded from active queries but not physically removed | Wave 2+ | No (application-level query filtering) |
| Case-close behavior | none today (no `prior_authorization_cases` table exists) | N/A | New: `case_status_code = CLOSED` requires `closed_at_utc`/`closed_by`/`close_reason_code` (see [constraints_and_indexes.md §3](constraints_and_indexes.md)) | Wave 2 | Partial, same reasoning as above. |
| Workflow terminal timestamp requirement | none today | N/A | New: `workflow_status_code` terminal (`COMPLETED`/`FAILED`) requires `completed_at_utc` populated — application-enforced, not a CHECK (see [constraints_and_indexes.md §4](constraints_and_indexes.md)) | Wave 2 | No — this is explicitly an application/service-layer test, not a database-level one. |
| Human-review completion/outcome consistency | none today (`human_reviews` does not exist) | N/A | New: same-row CHECK — `completed_at_utc` and `review_outcome_code` are both NULL or both NOT NULL | Wave 4 | Yes — this one *is* a same-row CHECK constraint per [constraints_and_indexes.md §4](constraints_and_indexes.md). |

No tests are added by Task 19C itself — this table is a plan only, per the task's explicit instruction.

## 13. Rollback / Recovery Strategy

This is planning only; no rollback has been exercised or needs to be exercised as a result of this document.

- **Git rollback boundary:** every Wave's schema/code changes must land as its own reviewed commit(s), so a failed Wave can be reverted with `git revert`/`git reset` back to the last known-good commit (currently `4f473fcb2e7b792113a55b72dd035ca27c73591f`) without touching unrelated work.
- **Schema migration rollback boundary:** the schema-application mechanism is chosen and the framework is installed and initialized — Alembic + SQLAlchemy, per [ADR-005](../decisions/ADR-005-database-schema-migration-strategy.md). The first revision (`c841e86a8516`, Wave 1) has now been authored, reviewed, applied to the real local SQL Server database, and validated (see §17.C); it has a corresponding `downgrade()` reversal path, though downgrading has not been exercised. Every future schema change continues through the same reviewed `upgrade`/`downgrade` revision pattern, never a hand-run, unrecorded `ALTER`/`CREATE` statement.
- **Test gate before next Wave:** a Wave is not considered safe to build on until its own new tests pass *and* the full existing suite (currently 241 tests) still passes — no Wave may be layered on top of a regression.
- **Backup/recreate strategy for the synthetic local database:** because `healthcare_ai_fde_lab` contains only disposable synthetic validation data (§9), "backup" here means nothing more than: before any destructive schema change (e.g. the Strategy B rebuild recommended in §9), confirm current schema/data state via a read-only query, and only then proceed with explicit approval. No production-grade backup/restore tooling is required for a synthetic Phase 1 prototype.
- **No destructive reset without explicit approval:** consistent with this project's established working pattern (every live-SQL-Server-touching script in Task 18B was shown in full and approved before execution), no future Wave may `DROP`/`TRUNCATE`/bulk-delete against the real local SQL Server without the same explicit, per-action approval.
- **No dependence on manually remembered SQL:** every schema change must exist as committed, reviewable code (ORM model change, or a migration script) — never as an ad hoc SQL statement typed once and not preserved anywhere in the repository.

## 14. Risks

- The `processing_step` → `workflow_step_id` translation (§5.B) requires new mapping logic between LangGraph step names and `workflow_definition_steps.step_code`; underestimating this as a "rename" would produce an incorrect Wave 2 estimate. The mapping itself is now RESOLVED (§16, [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md)); implementing it in code remains Wave 2 work.
- Current `AuditEventCategory.ERROR` usage (§7.B) — including at least one existing test fixture — must eventually be translated to the correct functional-domain category once `event_category_code` becomes a real FK; underestimating this as automatic risks a silent behavior change or a test failure at that time. The category disposition itself is resolved (§7.B); only the mechanical translation work remains, and it is scoped to the Wave that adds the FK, not Wave 0 or Wave 1.
- Composite FK enforcement (§5.B, §12) is new SQL Server behavior with no current offline-test equivalent; the SQLite test double may not enforce composite FKs identically unless explicitly configured to do so, risking a false sense of coverage.
- The existing Task 18B-6 synthetic rows do not satisfy the target schema's new NOT NULL columns; an in-place migration (Strategy A) without a rebuild would need explicit backfill values invented for them, which risks polluting the target schema with meaningless placeholder data for rows that were never meant to be permanent.
- **Wave 1 is now physically implemented (§17.C).** The first Alembic revision (`c841e86a8516`) followed ADR-006's approved scope exactly (Wave 1 only, additive, existing `workflow_runs`/`audit_events` tables untouched) and was validated against the real database with no deviation. The remaining risk is forward-looking: Wave 2 must still resolve the `trace_id` generation point and the LangGraph-step-to-`workflow_definition_steps` mapping (§16) before it can implement the target `workflow_runs`/`audit_events` shape and the controlled prototype rebuild.

## 15. Assumptions

- The current two-table implementation and its 241-test suite represent the full scope of "existing behavior" to preserve; no undocumented persistence code exists outside `src/db/` and `src/models/audit.py`.
- `trace_id` will eventually be generated somewhere in the workflow/API layer before Wave 2 wiring occurs; Wave 0 does not decide where (see §16).
- Alembic + SQLAlchemy, the approved schema-application mechanism ([ADR-005](../decisions/ADR-005-database-schema-migration-strategy.md)), is installed and initialized (Task 19E), the first-revision/brownfield prototype strategy is resolved ([ADR-006](../decisions/ADR-006-first-revision-and-brownfield-strategy.md), Task 19F), and the first Wave 1 revision has been authored, applied, and validated (Tasks 20A/20B — see §17.C).
- The local `healthcare_ai_fde_lab` database remains the only environment affected by any future Wave's schema work; no shared/staging/production SQL Server instance exists yet.

## 16. Open Decisions

Three decisions originally listed here are now **RESOLVED** and are documented at their authoritative source, not here:

- **`FAILED` workflow-status semantics** — RESOLVED. Authoritative source: [reference_data.md §4](reference_data.md#4-workflow_statuses). Migration rule recorded in §7.A above.
- **Generic `ERROR` event-category disposition** — RESOLVED (no target `ERROR` category exists; events remain categorized by functional domain). Authoritative source: [reference_data.md §10](reference_data.md#10-event_categories). Migration rule recorded in §7.B above.
- **Schema-application mechanism (architecture decision)** — RESOLVED. Alembic + SQLAlchemy is the approved primary mechanism for future physical schema creation/evolution against the real SQL Server database; `Base.metadata.create_all()` is retained only for offline-test/bootstrap convenience. Authoritative source: [ADR-005](../decisions/ADR-005-database-schema-migration-strategy.md).
- **Alembic migration framework (installation/initialization)** — RESOLVED (Task 19E). Alembic 1.20.0 is installed and pinned in `requirements.txt`; `alembic.ini` and `migrations/` (`env.py`, `script.py.mako`, `versions/`) exist and are wired to this project's existing SQLAlchemy `Base.metadata` and its existing secure database configuration (`src/config/database.py` + `src/db/engine.py`). **The framework is now in active use: the first revision (`c841e86a8516`) has been applied to the real database and the `alembic_version` table exists — see §17.C.**
- **First-revision / brownfield prototype strategy** — RESOLVED (Task 19F) and executed (Tasks 20A/20B). The first Alembic revision (`c841e86a8516`) implements Wave 1 only (additive; the existing `workflow_runs`/`audit_events` tables remain untouched); a controlled local prototype database rebuild remains planned at the Wave 2 boundary, with explicit approval to be sought at that time; a fresh database thereafter uses the same Alembic revision chain from base. No `alembic stamp`/fake baseline was used. Authoritative source: [ADR-006](../decisions/ADR-006-first-revision-and-brownfield-strategy.md).
- **`trace_id` generation point** — RESOLVED (Task 21A). `trace_id` is application-generated (UUID4) exactly once per workflow run, at the future orchestration boundary immediately before the first `graph.invoke()` call — never inside a node, never by audit logging independently, never by SQL Server. One workflow run = one `trace_id`; a new run for the same case gets a new `trace_id`; a human-review pause/resume keeps the same `trace_id`. This orchestration boundary does not exist in application code yet; building it is Wave 2 implementation work, not decided by this resolution. Authoritative source: [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md).
- **LangGraph step → `workflow_definition_steps.step_code`/`workflow_step_id` mapping** — RESOLVED (Task 21A) and implemented (Task 22, `src/workflow/step_mapping.py`). Every current LangGraph node (`src/workflow/graph.py`) is explicitly mapped to one of the `step_code` values already proposed in [reference_data.md §7](reference_data.md#7-workflow_definition_steps); the mapping is a reviewed table, not a runtime derivation from `function.__name__`. Sub-outcome strings currently folded into `processing_steps` (e.g. `evidence_mismatch_detected`, `ai_provider_failed`) become `event_type_code` values, not steps. Authoritative source: [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md).
- **Reference-data loading implementation** — RESOLVED and implemented (Task 22, `src/db/reference_data.py`). Idempotent, insert-missing-only, semantic-conflict-fails-and-rolls-back, one transaction, separate from Alembic schema migrations, deterministic human-readable prototype IDs for `workflow_definition_id`/`workflow_step_id`. Run against the real local SQL Server database: 78 stable rows across 12 tables (`reasons`, `case_statuses`, `workflow_statuses`, `workflow_actions`, `event_categories`, `event_types`, `actor_types`, `source_components`, `result_codes`, `failure_categories`, `workflow_definitions`, `workflow_definition_steps`), including the complete approved 8-step `PRIOR_AUTHORIZATION` workflow definition. Idempotency re-validated on the real database (second run: 0 inserted, 78 already present). Synthetic business fixtures (a test client/case) are explicitly separate and never part of this loader. See §17.E.

No further decisions are required to complete Wave 0. The schema-application mechanism's *architecture decision*, the Alembic *framework installation*, the *first-revision/brownfield strategy*, the `trace_id` *generation point*, the LangGraph *step mapping*, and *reference-data loading* are all resolved and implemented — see §17 for what that does and does not unblock. No OPEN items remain in this table.

## 17. Wave 1 Readiness

This plan distinguishes two separate readiness states. They are not the same thing, and this plan does not claim Wave 1 is unconditionally "ready" without specifying which one it means.

### 17.A Wave 1 planning readiness — MET

Task 19C (Wave 0) is complete, and **Wave 1 planning is unblocked**, because all of the following are true:

- [x] Current-to-target mapping for `workflow_runs` and `audit_events` is complete and field counts are exactly reconciled (§5).
- [x] The current `AuditRepository` contract is documented, behavior by behavior (§6).
- [x] Status/code vocabulary mapping is resolved for every current enum against target reference data, including the two decisions approved in this pass (`FAILED`, generic `ERROR`) (§7).
- [x] Identifier strategy is confirmed compliant in format; the generation-point gap tracked here is now RESOLVED (Task 21A, [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md)) and implemented (Task 22, §17.E) (§8, §16).
- [x] Current synthetic data handling strategy is documented, without altering the actual rows (§9).
- [x] Dependency order for all 36 tables is confirmed against the real data dictionary, not assumed (§10).
- [x] Test preservation matrix is complete for every currently-tested behavior plus every newly-required behavior (§12).
- [x] Rollback approach is documented, including the three distinct rollback concepts defined in [ADR-005](../decisions/ADR-005-database-schema-migration-strategy.md) (§13).
- [x] No unresolved MUST-FIX blocker exists **for planning purposes** (§14 lists risks; the schema-application mechanism's *architecture decision* is resolved via ADR-005, the Alembic *framework* is installed and initialized (Task 19E), and the *first-revision/brownfield strategy* is resolved via ADR-006 (Task 19F) — see 17.B for what remains to actually implement).
- [x] Repository documentation (`data_model.md`, `data_dictionary.md`, `reference_data.md`, `constraints_and_indexes.md`, this plan) is internally consistent — no contradiction was found during this review.
- [x] The current test baseline (241 tests) still passes, confirmed after this document was written (see the validation run accompanying this task).
- [x] No code or schema change occurred as part of Wave 0 — confirmed by `git status` showing only documentation changes.

### 17.B Wave 1 physical implementation readiness — DESIGN GATE CLEARED (historical)

Three things became true before implementation began, and were not conflated: the schema-application mechanism **architecture decision** was resolved (ADR-005); the Alembic **framework was installed and initialized** (Task 19E) — `alembic.ini` and `migrations/` (`env.py`, `script.py.mako`, `versions/`) exist, `env.py` uses this project's existing `Base.metadata` and existing secure database configuration, and Alembic 1.20.0 is pinned in `requirements.txt`; and the **first-revision/brownfield prototype strategy was resolved** (ADR-006, Task 19F) — the first revision would implement Wave 1 only, additively, leaving `dbo.workflow_runs`/`dbo.audit_events` untouched, with a controlled prototype rebuild deferred to the Wave 2 boundary under explicit future approval.

This cleared the design/architecture gate for writing the first Wave 1 migration revision (Task 20A), which was then authored, reviewed, and executed (Task 20B) — see §17.C for the completed result.

### 17.C Wave 1 physical implementation — COMPLETE

**Status: PHYSICAL IMPLEMENTATION COMPLETE.**

**Installed Alembic revision:** `c841e86a8516` (`migrations/versions/c841e86a8516_create_wave_1_database_foundation.py`), applied to the real local SQL Server database `healthcare_ai_fde_lab` via `alembic upgrade head` (Task 20B).

**Validation performed and passed** (read-only, against the real database):
- All 14 Wave 1 tables created (`reasons`, `countries`, `clients`, `locations`, `departments`, `case_statuses`, `workflow_statuses`, `workflow_actions`, `event_categories`, `event_types`, `actor_types`, `source_components`, `result_codes`, `failure_categories`).
- Primary key validation: 14/14 matched.
- Foreign key validation: 20/20 expected FKs found (ordinary FKs, the self-referencing `departments.parent_department_id` FK, and the universal `delete_reason_code` → `reasons` FK on every applicable table).
- Business-key `UNIQUE` constraint validation: all 4 present and correctly named/ordered (`uq_countries_iso3_code`, `uq_clients_client_code`, `uq_locations_client_id_location_code`, `uq_departments_client_id_department_code`).
- Prototype preservation: `dbo.workflow_runs` (1 row) and `dbo.audit_events` (2 rows) both preserved unchanged in row count and column schema.
- No seed/reference rows inserted — all 14 new tables confirmed empty (0 rows each).
- Wave 6 hardening confirmed still absent: 0 CHECK constraints on the 14 Wave 1 tables, the three deferred secondary indexes (`ix_locations_client_id_country_code`, `ix_departments_client_id`, `ix_departments_parent_department_id`) absent, and the `event_types` composite-FK-support `UNIQUE` constraint absent.
- Full test suite: 241 passed.
- Repository working tree confirmed clean after execution (no incidental file changes).

**Wave 1: COMPLETE. Wave 2: COMPLETE — see §17.D.**

The `trace_id` generation point and the LangGraph-step-to-`workflow_definition_steps` mapping were RESOLVED (Task 21A, §16, [ADR-007](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md)) and are now implemented as runtime code (Task 22, §17.E). Reference-data loading is likewise resolved and implemented (Task 22, §17.E) — no OPEN items remain in §16.

### 17.D Wave 2 physical implementation — COMPLETE

**Status: PHYSICAL IMPLEMENTATION COMPLETE.**

**Installed Alembic revision:** `b9aba5b07ac8` (`migrations/versions/b9aba5b07ac8_create_wave_2_canonical_case_workflow_.py`, `down_revision = c841e86a8516`), applied to the real local SQL Server database `healthcare_ai_fde_lab` via `alembic upgrade head` (Task 21B).

**8 Wave 2 tables physically installed:** `document_types` (pulled forward from Wave 3 — see below), `workflow_definitions`, `workflow_definition_steps`, `prior_authorization_cases`, `case_diagnoses`, `case_documents`, `workflow_runs` (canonical replacement), `audit_events` (canonical replacement). The physical database now contains 22 application tables + `alembic_version` = 23 `dbo` tables.

**`document_types` Wave reassignment (resolved dependency conflict, not silently decided):** `document_types` was originally scoped to Wave 3 (see the Wave 1 revision's own docstring and §16's prior wording). During Wave 2 authoring, `case_documents.document_type_code` was found to be a required (NOT NULL) foreign key to `document_types`, which would not yet exist under the original Wave 3 assignment. Because a Wave must be internally dependency-consistent, `document_types` — a zero-dependency reference master — was pulled forward into Wave 2, schema only, following the same precedent already used for `case_statuses` being pulled into Wave 1 for `prior_authorization_cases`' sake. At the time of this Wave 2 migration, no `document_types` reference rows were inserted (schema-only reassignment); reference-data loading was implemented separately afterward (Task 22, §17.E) and does not include `document_types` rows, since no currently implemented workflow path requires them yet.

**Canonical `workflow_runs`/`audit_events`:** the Task 18A/18B prototype tables (7 and 9 columns) were replaced via the ADR-006-approved controlled rebuild (`DROP` + `CREATE` inside the same migration) with their canonical Wave 2 shapes (23 and 19 columns respectively, per [data_dictionary.md](data_dictionary.md)). The prototype's disposable synthetic Task 18B rows were intentionally removed as part of this rebuild — not preserved, per ADR-006.

**Validation performed and passed** (read-only, against the real database):
- All 8 Wave 2 tables created; all 14 Wave 1 tables confirmed still present, untouched.
- Primary key validation: 8/8 matched.
- Foreign key validation: 40/40 expected FKs found.
- Business-key `UNIQUE` constraint validation: 2/2 present (`workflow_definitions(workflow_code, version_no)`, `workflow_definition_steps(workflow_definition_id, step_code)`).
- Exactly one index present on `audit_events`: `ix_audit_events_trace_id` (preserved from the pre-Wave Task 18A prototype, not new Wave 2 or Wave 6 scope).
- 0 CHECK constraints introduced.
- All 8 new/replaced tables confirmed empty (0 rows each) — no seed/reference data inserted.
- Wave 6 hardening confirmed still absent: the composite FK pair (`audit_events(trace_id, case_id)` → `workflow_runs`; `audit_events(event_type_code, event_category_code)` → `event_types`), `workflow_runs` composite `UNIQUE(trace_id, case_id)`, lifecycle/ISJSON CHECK constraints, the filtered `case_diagnoses` primary-diagnosis constraint, and every deferred secondary index were all confirmed absent.
- Full test suite: 279 passed, 1 warning (241 baseline + 38 new Wave 2 schema tests).

**SQLite DDL execution: NOT APPLICABLE / DIALECT-INCOMPATIBLE.** These migrations deliberately use Microsoft SQL Server-specific types (`mssql.DATETIME2`, `mssql.NVARCHAR`) that SQLite's compiler cannot render — this is a dialect boundary, not a defect, and was confirmed directly (the already-executed, already-SQL-Server-validated Wave 1 migration fails identically under SQLite, before Wave 2 is even reached). The applicable validation layers for these revisions are: Python syntax validation, Alembic revision-chain validation, SQLAlchemy metadata/unit tests (valid for the ORM layer, which deliberately uses generic, dialect-neutral types), manual migration inspection, and controlled execution against real SQL Server. The migration is not altered to become SQLite-compatible.

**Wave 1: COMPLETE. Wave 2: COMPLETE. Wave 3: PLANNING / IMPLEMENTATION NEXT** (now minus `document_types`, which moved to Wave 2 — see above).

At the close of Task 21B, the following remained NOT implemented: reference-data loading, LangGraph → persistence wiring, runtime `trace_id` generation, runtime node → workflow-step mapping. **All four are now implemented — see §17.E.** Still NOT implemented: an API endpoint that invokes the orchestrator, Human-in-the-Loop pause/resume orchestration and reviewer-decision persistence, Streamlit UI, Wave 3+ tables (beyond `document_types`), Wave 6 relational hardening, and all productionization items.

### 17.E Task 22 — LangGraph ↔ SQL persistence wiring and reference-data loading — COMPLETE

**Status: RUNTIME PERSISTENCE WIRING AND REFERENCE-DATA LOADING IMPLEMENTED AND VALIDATED.**

**Orchestration boundary implemented:** `src/workflow/orchestrator.py`, a pure Python function (`run_prior_authorization_workflow`) — not an HTTP endpoint. Generates one application-side UUID4 `trace_id` per workflow run, immediately before `graph.invoke()` (per ADR-007); invokes the existing, unmodified LangGraph graph; persists the run to canonical `workflow_runs` (created as `PROCESSING` at orchestration start, updated once with the final outcome — run-identity fields, e.g. `case_id`/`workflow_definition_id`/`initiated_by_component_code`/`started_at_utc`/`created_at_utc`/`created_by`, are never overwritten on update, a mutability-policy fix also applied to `AuditRepository.save_workflow_run`) and canonical `audit_events` (meaningful transitions only, via the single authoritative node → `step_code` mapping in `src/workflow/step_mapping.py` — never a raw Python function name). `HUMAN_REVIEW_REQUIRED` is persisted correctly as a pause (`completed_at_utc` stays `NULL`, matching `workflow_statuses.is_terminal = 0`), preserving the same `trace_id` for a future Task 23 resume. An unhandled workflow exception is marked `FAILED` and re-raised, never hidden; a repository `PersistenceError` is never caught or swallowed.

**Reference-data loader implemented:** `src/db/reference_data.py` — separate from Alembic, idempotent (insert-missing-only; a semantic conflict on an existing row raises `ReferenceDataConflictError` and rolls back the entire load, never silently overwriting), one transaction. Ten of the twelve tables it loads have no SQLAlchemy ORM class (Wave 1, raw DDL only — see `src/db/models.py`'s Foreign Key Policy), so those are read/written via parameterized `sa.text()` through the same session; the two ORM-backed tables (`workflow_definitions`, `workflow_definition_steps`) use the existing ORM classes directly. `workflow_definition_id`/`workflow_step_id` (no literal value prescribed by the canonical design) use deterministic, human-readable prototype IDs derived from each row's business key (e.g. `wfdef_prior_authorization_1_0`), not random UUIDs.

**Loaded onto the real local SQL Server database (`healthcare_ai_fde_lab`, revision `b9aba5b07ac8`) and validated:** 78 rows across 12 tables — `reasons`=7 (`EVIDENCE_MISMATCH`/`HUMAN_REVIEW` domains only; `CASE_CLOSE`/`DELETE` domains excluded as unreferenced by any implemented code path), `case_statuses`=5, `workflow_statuses`=4, `workflow_actions`=4, `event_categories`=6, `event_types`=15, `actor_types`=4, `source_components`=8, `result_codes`=8, `failure_categories`=8, `workflow_definitions`=1 (`PRIOR_AUTHORIZATION`/`1.0`), `workflow_definition_steps`=8 (the complete approved step set: `CASE_VALIDATION`, `FHIR_RETRIEVAL`, `EVIDENCE_CONSISTENCY`, `COMPLETENESS_CHECK`, `AI_ROUTING`, `AI_ANALYSIS`, `HUMAN_REVIEW`, `COMPLETE` — not only the 5 exercised by the happy-path test). Idempotency re-validated by running the loader a second time against the same real database: 0 inserted, all 78 recognized as already present, 0 conflicts, row counts unchanged. `document_types` was deliberately not loaded — no currently implemented workflow path requires it.

**Synthetic business fixtures kept explicitly separate**, per ADR-006/Task 21B precedent: `src/db/reference_data.py` never creates a `clients`, `department`, `location`, or `prior_authorization_cases` row. The one real SQL Server integration test (`tests/test_workflow_orchestrator_integration.py`, opt-in only — skipped by ordinary `pytest` unless `RUN_SQL_SERVER_INTEGRATION_TESTS=1`) creates its own single synthetic client + case fixture separately, and deletes it (plus its `workflow_runs`/`audit_events` rows) in a `finally` block, leaving the 78 stable rows untouched.

**Real SQL Server integration path validated:** synthetic case → mocked FHIR success (`httpx.MockTransport`, no real network call) → evidence consistent → completeness passes → AI not required (no Azure OpenAI call) → `COMPLETED`. Confirmed: exactly 1 `workflow_runs` row, exactly 6 `audit_events` rows (`WORKFLOW_STARTED`, `FHIR_RETRIEVAL_SUCCEEDED`, `EVIDENCE_CONSISTENCY_CHECKED`, `COMPLETENESS_CHECKED`, `AI_NOT_REQUIRED`, `WORKFLOW_COMPLETED`), one `trace_id` shared across all of them, `workflow_status_code = COMPLETED`, `next_action_code = COMPLETE_WORKFLOW`, `human_review_required = false`, `completed_at_utc` populated, and `workflow_step_id` resolved from the real, just-loaded `workflow_definition_steps` rows (never a raw node name). Full offline test suite: 312 passed, 1 skipped (the opt-in integration test, by design), 1 warning.

**Still NOT implemented:** any HTTP endpoint invoking the orchestrator (`POST /cases/validate` remains validation-only), Human-in-the-Loop pause/resume orchestration, reviewer assignment/UI/decision persistence, Streamlit UI, Wave 3+ tables, Wave 6 relational hardening, and all productionization items. AI still cannot approve/deny clinical care — the validated path used deterministic AI-not-needed routing, and the existing classified-failure → `HUMAN_REVIEW_REQUIRED` safe fallback is unchanged.

## 18. Related Documentation

- [data_model.md](data_model.md) — canonical data model and normalization rationale
- [data_dictionary.md](data_dictionary.md) — authoritative field-level dictionary
- [reference_data.md](reference_data.md) — proposed controlled seed/reference-data catalog
- [constraints_and_indexes.md](constraints_and_indexes.md) — relational integrity, uniqueness, CHECK constraint, and index catalog
- [erd/](erd/) — reviewed ERD artifacts
- [../decisions/ADR-003-sql-server.md](../decisions/ADR-003-sql-server.md) — Microsoft SQL Server decision
- [../decisions/ADR-004-phase1-canonical-data-model.md](../decisions/ADR-004-phase1-canonical-data-model.md) — canonical data model decision
- [../decisions/ADR-005-database-schema-migration-strategy.md](../decisions/ADR-005-database-schema-migration-strategy.md) — schema migration/versioning mechanism decision (Alembic + SQLAlchemy)
- [../decisions/ADR-006-first-revision-and-brownfield-strategy.md](../decisions/ADR-006-first-revision-and-brownfield-strategy.md) — first Alembic revision scope and brownfield prototype transition strategy
- [../decisions/ADR-007-trace-id-and-workflow-step-mapping.md](../decisions/ADR-007-trace-id-and-workflow-step-mapping.md) — trace_id generation point and LangGraph node → workflow_definition_steps mapping
- [../architecture.md](../architecture.md) — overall Phase 1 system architecture
