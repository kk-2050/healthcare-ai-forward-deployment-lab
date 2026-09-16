<!--
File Name: constraints_and_indexes.md
Purpose: Phase 1 relational constraint, referential-integrity, uniqueness, check-constraint, and index catalog
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# Healthcare AI Forward Deployment Lab — Constraints & Indexes v2.2

**Status:** Design baseline; physical SQL implementation occurs by Wave.
**Database:** Microsoft SQL Server.

## 1. Global rules

- No cascade delete for business/history tables.
- Mutable tables use logical delete.
- `audit_events` is append-only.
- FK delete behavior defaults to `NO ACTION`.
- All JSON columns should use `ISJSON(...)` CHECK constraints where practical.
- Business-code uniqueness should normally apply to active/logically retained records according to the specific table rule.
- Indexes must serve demonstrated query patterns; do not add speculative indexes without tests/query needs.

## 2. Global control-field CHECK pattern

For every non-audit persistent table, enforce the logical-delete lifecycle:

```text
is_deleted = 0
OR
(
  is_deleted = 1
  AND deleted_at_utc IS NOT NULL
  AND deleted_by IS NOT NULL
  AND delete_reason_code IS NOT NULL
)
```

Application validation should additionally prevent stale delete metadata when `is_deleted=0`.

## 3. Case-close CHECK pattern

For `prior_authorization_cases`:

```text
case_status_code <> 'CLOSED'
OR
(
  closed_at_utc IS NOT NULL
  AND closed_by IS NOT NULL
  AND close_reason_code IS NOT NULL
)
```

## 4. Lookup-driven lifecycle enforcement

Some conditional rules depend on attributes held in reference masters, for example:

- `workflow_runs.completed_at_utc` is required when `workflow_statuses.is_terminal = 1`.
- `human_reviews.completed_at_utc` and `review_outcome_code` are required when `human_review_statuses.is_terminal = 1`.

SQL Server `CHECK` constraints cannot directly query another table. Phase 1 therefore does **not** hard-code terminal status codes into a CHECK constraint merely to emulate a cross-table rule.

Enforcement strategy:

1. application/service validation against the referenced status master,
2. transactional persistence,
3. focused repository/integration tests,
4. optional production hardening later if a trigger or other database-level enforcement is justified.

A local same-row consistency CHECK is appropriate where it does not depend on another table.

### Human-review completion pair

Recommended same-row constraint:

```text
(
  completed_at_utc IS NULL
  AND review_outcome_code IS NULL
)
OR
(
  completed_at_utc IS NOT NULL
  AND review_outcome_code IS NOT NULL
)
```

Application validation still verifies that the referenced review status is terminal.

### Workflow completion timestamp

`workflow_runs.completed_at_utc` remains physically nullable. Application validation must require it when the referenced `workflow_statuses.is_terminal = 1`.

## 5. Key/unique/index catalog

| table | key / constraint / index | purpose |
|---|---|---|
| `clients` | UNIQUE(`client_code`) | Stable business code |
| `departments` | UNIQUE(`client_id`,`department_code`) | Client-scoped department uniqueness |
| `departments` | INDEX(`client_id`) | Client organization lookup |
| `departments` | INDEX(`parent_department_id`) | Hierarchy traversal |
| `locations` | UNIQUE(`client_id`,`location_code`) | Client-scoped location uniqueness |
| `locations` | INDEX(`client_id`,`country_code`) | Organization/geography lookup |
| `workflow_definitions` | UNIQUE(`workflow_code`,`version_no`) | Version-stable workflow definition |
| `workflow_definition_steps` | UNIQUE(`workflow_definition_id`,`step_code`) | Step uniqueness within version |
| `requirement_sets` | UNIQUE(`client_id`,`set_code`,`version_no`) | Versioned client requirement set |
| `requirement_rules` | INDEX(`requirement_set_id`) | Rule retrieval |
| `prior_authorization_cases` | INDEX(`client_id`,`case_status_code`,`is_deleted`) | Client work queue |
| `prior_authorization_cases` | INDEX(`department_id`) | Ownership routing |
| `prior_authorization_cases` | INDEX(`location_id`) | Location routing |
| `case_diagnoses` | INDEX(`case_id`) | Case detail retrieval |
| `case_diagnoses` | filtered UNIQUE on active primary diagnosis per `case_id` | At most one active primary diagnosis |
| `case_documents` | INDEX(`case_id`,`document_type_code`,`is_deleted`) | Completeness/document lookup |
| `workflow_runs` | INDEX(`case_id`,`started_at_utc`) | Run history per case |
| `workflow_runs` | INDEX(`workflow_status_code`,`human_review_required`) | Workflow queues |
| `workflow_runs` | UNIQUE(`trace_id`,`case_id`) | Composite audit consistency target |
| `rule_evaluations` | INDEX(`trace_id`,`evaluated_at_utc`) | Deterministic evaluation history |
| `integration_executions` | INDEX(`trace_id`,`started_at_utc`) | Integration history |
| `ai_analysis_runs` | INDEX(`trace_id`,`started_at_utc`) | AI execution history |
| `human_reviews` | INDEX(`trace_id`,`review_status_code`) | Review history |
| `human_reviews` | INDEX(`assigned_department_id`,`review_status_code`) | Human-review work queue |
| `human_reviews` | CHECK(completion timestamp/outcome pair) | Keep `completed_at_utc` and `review_outcome_code` nullability synchronized |
| `event_types` | UNIQUE(`event_type_code`,`event_category_code`) | Composite audit consistency target |
| `audit_events` | INDEX(`trace_id`,`occurred_at_utc`,`event_id`) | Chronological trace audit |
| `audit_events` | INDEX(`case_id`,`occurred_at_utc`) | Case audit timeline |
| `audit_events` | INDEX(`event_type_code`) | Event filtering |
| `audit_events` | COMPOSITE FK(`trace_id`,`case_id`) → `workflow_runs` | Prevent trace/case mismatch |
| `audit_events` | COMPOSITE FK(`event_type_code`,`event_category_code`) → `event_types` | Prevent type/category mismatch |

## 6. JSON constraints

Candidate columns:

- `clients.metadata_json`
- `departments.metadata_json`
- `locations.metadata_json`
- `requirement_sets.metadata_json`
- `client_requirement_intakes.metadata_json`
- `requirement_rules.parameter_json`
- `prior_authorization_cases.metadata_json`
- `case_documents.metadata_json`
- `workflow_runs.metadata_json`
- `rule_evaluations.metadata_json`
- `integration_executions.metadata_json`
- `ai_analysis_runs.validated_output_json`
- `ai_analysis_runs.metadata_json`
- `human_reviews.metadata_json`
- `audit_events.metadata_json`

For nullable JSON:

```text
column IS NULL OR ISJSON(column) = 1
```

Pydantic/application validation remains required; `ISJSON` checks syntax, not allowed keys.

## 7. Audit immutability

Database/runtime permission design should eventually deny normal application runtime:

- `UPDATE` on `audit_events`
- `DELETE` on `audit_events`

Only INSERT and SELECT are required for normal operation.

Phase 1 local prototype may enforce this first through repository contract/tests, with database-role hardening documented for productionization.

## 8. Application boundary length alignment

Before Wave 2 persistence wiring, bounded SQL string columns must be matched by Pydantic/API boundary validation where the value originates from an external request.

At minimum review:

- `case_id`
- `member_id`
- `provider_id`
- `requested_service_code`
- `diagnosis_code`
- document references and other externally supplied bounded strings

Goal: reject oversize input through structured validation rather than surfacing a raw SQL Server truncation/length error.

The SQL data dictionary remains the source of truth for the physical maximum length; Pydantic constraints should match it.

## 9. Related documentation

- [data_model.md](data_model.md) — canonical data model and normalization rationale
- [data_dictionary.md](data_dictionary.md) — authoritative field-level dictionary
- [reference_data.md](reference_data.md) — proposed controlled seed/reference-data catalog
- [../decisions/ADR-004-phase1-canonical-data-model.md](../decisions/ADR-004-phase1-canonical-data-model.md) — the architecture decision record for this model
