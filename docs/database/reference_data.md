<!--
File Name: reference_data.md
Purpose: Controlled master/reference-data and proposed Phase 1 seed-value catalog
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# Healthcare AI Forward Deployment Lab — Reference Data Catalog v2.2

**Status:** Approved Phase 1 seed baseline. **Implementation status (Task 22):** a loader (`src/db/reference_data.py`) implementing this catalog is built and has been run against the real local SQL Server database (`healthcare_ai_fde_lab`) — 78 rows currently loaded across 12 tables: `reasons` (7 — `EVIDENCE_MISMATCH`/`HUMAN_REVIEW` domains only; `CASE_CLOSE`/`DELETE` domains below remain proposed-but-not-loaded, since no currently implemented workflow path references them), `case_statuses` (5), `workflow_statuses` (4), `workflow_actions` (4), `event_categories` (6), `event_types` (15), `actor_types` (4), `source_components` (8), `result_codes` (8), `failure_categories` (8), `workflow_definitions` (1), `workflow_definition_steps` (8 — the complete set below, not only a subset). `document_types`, `requirement_types`, `human_review_statuses`, `human_review_outcomes`, `discovery_item_types`, and `ai_task_types` remain proposed only — not yet loaded, since no currently implemented workflow path requires them. Loader idempotency (insert-missing-only; a semantic conflict on an existing row fails and rolls back the whole load, never silently overwriting) was validated directly against the real database. See [migration_plan.md §17.E](migration_plan.md#17e-task-22--langgraph--sql-persistence-wiring-and-reference-data-loading--complete) for the full validation record. This document's catalog values themselves are unchanged by Task 22 — only their load status is recorded here.

## 1. Seed-data principles

- Codes are stable and machine-readable.
- Display names/descriptions may change without changing the code.
- Do not reuse a retired code for a different meaning.
- Prefer deactivation (`is_active=0`) over deleting historical reference values.
- All reference/master tables still carry the standard nine control fields.
- No real client, patient, provider, reviewer, or facility identifiers are used.
- Evidence mismatch reasons are business `reasons`, not `failure_categories`.

## 2. Synthetic organization baseline

**Not part of the Task 22 stable reference-data loader.** `src/db/reference_data.py` never creates a `clients`, `department`, `location`, or `prior_authorization_cases` row — the example `cli_demo_001` row below remains a proposed design example only. The one real SQL Server integration test that needs a client/case (`tests/test_workflow_orchestrator_integration.py`, opt-in only) creates its own separate, differently-identified synthetic fixture (`cli_integration_test_001`) and deletes it after the test — it is never treated as reference/config data.

### `clients`

| client_id | client_code | client_name | is_active |
|---|---|---|---:|
| `cli_demo_001` | `DEMO_HEALTH` | Demo Health Plan | 1 |

### `departments`

| department_id | client_id | department_code | department_name | parent_department_id | is_active |
|---|---|---|---|---|---:|
| `dep_demo_pa_ops` | `cli_demo_001` | `PA_OPERATIONS` | Prior Authorization Operations | NULL | 1 |
| `dep_demo_clin_review` | `cli_demo_001` | `CLINICAL_REVIEW` | Clinical Review | NULL | 1 |

### `countries`

| country_code | country_name | iso3_code | is_active |
|---|---|---|---:|
| `US` | United States | `USA` | 1 |

### `locations`

| location_id | client_id | location_code | location_name | country_code | time_zone | is_active |
|---|---|---|---|---|---|---:|
| `loc_demo_chi_ops` | `cli_demo_001` | `CHI_OPS` | Chicago Operations | `US` | `America/Chicago` | 1 |
| `loc_demo_central_review` | `cli_demo_001` | `CENTRAL_REVIEW` | Central Review Center | `US` | `America/Chicago` | 1 |

## 3. `case_statuses`

| code | name | terminal | purpose |
|---|---|---:|---|
| `OPEN` | Open | 0 | Case exists and may be processed |
| `IN_PROGRESS` | In Progress | 0 | Active workflow processing |
| `PENDING_INFORMATION` | Pending Information | 0 | Missing required information/documents |
| `HUMAN_REVIEW_REQUIRED` | Human Review Required | 0 | Automated processing paused for reviewer |
| `CLOSED` | Closed | 1 | Business case lifecycle ended |

## 4. `workflow_statuses`

Canonical Phase 1 workflow-run statuses:

| code | name | terminal | human_review | purpose |
|---|---|---:|---:|---|
| `PROCESSING` | Processing | 0 | 0 | Automated workflow is actively executing |
| `HUMAN_REVIEW_REQUIRED` | Human Review Required | 0 | 1 | Automated processing is paused pending human review |
| `COMPLETED` | Completed | 1 | 0 | This workflow run completed successfully; use `next_action_code` for the business next step |
| `FAILED` | Failed | 1 | 1 | Terminal technical/workflow failure where safe automated continuation **or** successful creation/routing of a Human-in-the-Loop review task cannot be established |

**`FAILED` semantics (authoritative):** `FAILED` is reserved for a terminal technical/workflow failure where safe automated continuation cannot be established *and* a Human-in-the-Loop review task also cannot be reliably created or routed. It is not a catch-all for every technical failure.

A FHIR/AI/integration failure that is successfully and safely routed to human review is **not** `FAILED` — it remains `HUMAN_REVIEW_REQUIRED`, with `failure_category_code` (on the related `workflow_runs`/`audit_events` rows) carrying the specific technical classification. For example: a FHIR provider call fails, the failure is classified, and the workflow successfully creates/routes a human-review task → `HUMAN_REVIEW_REQUIRED`. An AI structured-output validation failure that is successfully routed to human review → likewise `HUMAN_REVIEW_REQUIRED`. Only a failure that additionally prevents safe human-review routing itself — for example, a persistence/orchestration failure — reaches `FAILED`.

Note on the `human_review` column above: it flags that a `FAILED` outcome still ultimately warrants human attention (e.g. manual operational investigation), which is a different thing from the *in-workflow, automated* HITL task creation/routing that `FAILED` specifically means could not be safely established.

### Current-code migration mapping

The current Python `WorkflowStatus` enum predates the relational status model.

| current Python value | target relational representation | rationale |
|---|---|---|
| `PROCESSING` | `PROCESSING` | Direct match |
| `HUMAN_REVIEW_REQUIRED` | `HUMAN_REVIEW_REQUIRED` | Direct match |
| `COMPLETE` | `COMPLETED` | Canonical naming is standardized to `COMPLETED` |
| `AI_ANALYSIS_REQUIRED` | Not a workflow-run status | Represent through workflow step/event/action; it is an internal processing state |
| `AI_ANALYSIS_COMPLETE` | Not a workflow-run status | Represent through workflow step/event; the run may still continue |

`INCOMPLETE` is intentionally **not** a workflow-run status. Missing-information state is represented by deterministic `rule_evaluations`, the Case lifecycle (`PENDING_INFORMATION` when applicable), and `next_action_code = REQUEST_MISSING_INFORMATION`.


## 5. `workflow_actions`

| code | name | requires_human | terminal |
|---|---|---:|---:|
| `CONTINUE_PROCESSING` | Continue Processing | 0 | 0 |
| `REQUEST_MISSING_INFORMATION` | Request Missing Information | 0 | 1 |
| `ROUTE_HUMAN_REVIEW` | Route to Human Review | 1 | 1 |
| `COMPLETE_WORKFLOW` | Complete Workflow | 0 | 1 |

## 6. `workflow_definitions`

| workflow_code | version_no | name | active |
|---|---|---|---:|
| `PRIOR_AUTHORIZATION` | `1.0` | Prior Authorization Phase 1 | 1 |

**Loaded (Task 22):** `workflow_definition_id = wfdef_prior_authorization_1_0` — a deterministic, human-readable prototype identifier derived from `workflow_code`/`version_no` (no literal ID is prescribed by the canonical design; see `src/db/reference_data.py`), not a random UUID, so repeated loads resolve to the same row.

## 7. `workflow_definition_steps`

Proposed semantic steps; exact IDs are generated during seeding. **Loaded (Task 22):** all 8 steps below are loaded, each with a deterministic `workflow_step_id` of the form `wfstep_prior_authorization_1_0_<step_code, lowercased>` (e.g. `wfstep_prior_authorization_1_0_fhir_retrieval`) — the same deterministic-ID convention as `workflow_definition_id` above, not a random UUID.

| step_code | step_order | optional | purpose |
|---|---:|---:|---|
| `CASE_VALIDATION` | 10 | 0 | Pydantic/schema validation |
| `FHIR_RETRIEVAL` | 20 | 0 | Retrieve synthetic FHIR-style evidence |
| `EVIDENCE_CONSISTENCY` | 30 | 0 | Compare case vs. retrieved evidence |
| `COMPLETENESS_CHECK` | 40 | 0 | Deterministic required-information check |
| `AI_ROUTING` | 50 | 0 | Decide whether AI is needed |
| `AI_ANALYSIS` | 60 | 1 | Structured AI analysis when required |
| `HUMAN_REVIEW` | 70 | 1 | Human-in-the-loop path |
| `COMPLETE` | 80 | 0 | Terminal workflow completion |

## 8. `requirement_types`

| code | name |
|---|---|
| `REQUIRED_FIELD` | Required Field |
| `REQUIRED_DOCUMENT` | Required Document |
| `NOTES_REQUIRED` | Clinical Notes Required |
| `EVIDENCE_MATCH` | Evidence Consistency Requirement |

## 9. `document_types`

| code | name |
|---|---|
| `CLINICAL_NOTE` | Clinical Note |
| `PT_DOCUMENTATION` | Physical Therapy Documentation |
| `IMAGING_REPORT` | Imaging Report |
| `LAB_RESULT` | Laboratory Result |

Only types actually needed by the synthetic scenarios should be seeded.

## 10. `event_categories`

**No generic `ERROR` event category is seeded in Phase 1 (authoritative).** This intentionally separates two distinct questions: *where/what domain* the event belongs to (this table, `event_category_code`) versus *why/how* it failed (`failure_category_code`). Failure events remain categorized by their functional domain — a FHIR failure is `event_category_code = FHIR`, an AI failure is `AI`, a persistence failure is `PERSISTENCE`, a workflow/orchestration failure is `WORKFLOW` — never a generic `ERROR`; `failure_category_code` separately carries the specific failure classification (e.g. `FHIR_HTTP_ERROR`, `AI_OUTPUT_INVALID`).

| code | name |
|---|---|
| `WORKFLOW` | Workflow |
| `FHIR` | FHIR / Integration |
| `RULE` | Deterministic Rule |
| `AI` | AI |
| `HUMAN` | Human Review |
| `PERSISTENCE` | Persistence |

## 11. `event_types`

| event_type_code | category | meaning |
|---|---|---|
| `WORKFLOW_STARTED` | `WORKFLOW` | Workflow run started |
| `FHIR_RETRIEVAL_STARTED` | `FHIR` | FHIR-style retrieval started |
| `FHIR_RETRIEVAL_SUCCEEDED` | `FHIR` | FHIR-style retrieval succeeded |
| `FHIR_RETRIEVAL_FAILED` | `FHIR` | FHIR-style retrieval failed |
| `EVIDENCE_CONSISTENCY_CHECKED` | `RULE` | Evidence consistency evaluated |
| `COMPLETENESS_CHECKED` | `RULE` | Completeness evaluated |
| `AI_REQUIRED` | `AI` | Deterministic routing selected AI |
| `AI_NOT_REQUIRED` | `AI` | Deterministic routing skipped AI |
| `AI_ANALYSIS_SUCCEEDED` | `AI` | Structured AI analysis succeeded |
| `AI_ANALYSIS_FAILED` | `AI` | AI analysis failed safely |
| `HUMAN_REVIEW_REQUIRED` | `HUMAN` | Human review was required |
| `HUMAN_REVIEW_COMPLETED` | `HUMAN` | Human review completed |
| `WORKFLOW_COMPLETED` | `WORKFLOW` | Workflow reached terminal completion |
| `WORKFLOW_FAILED` | `WORKFLOW` | Workflow reached a terminal failure state |
| `AUDIT_CORRECTION_RECORDED` | `PERSISTENCE` | New event corrects prior immutable event |

## 12. `actor_types`

| code | name | human |
|---|---|---:|
| `SYSTEM` | System | 0 |
| `API_CLIENT` | API Client | 0 |
| `AI_SERVICE` | AI Service | 0 |
| `HUMAN_REVIEWER` | Human Reviewer | 1 |

## 13. `source_components`

| code | name |
|---|---|
| `FASTAPI` | FastAPI |
| `LANGGRAPH` | LangGraph |
| `RULE_ENGINE` | Deterministic Rule Engine |
| `FHIR_STYLE_CLIENT` | FHIR-style Integration Client |
| `AI_SERVICE` | AI Analysis Service |
| `AZURE_OPENAI_ADAPTER` | Azure OpenAI Adapter |
| `STREAMLIT` | Streamlit UI |
| `PERSISTENCE` | Persistence Layer |

## 14. `result_codes`

| code | name | success |
|---|---|---:|
| `SUCCESS` | Success | 1 |
| `FAILED` | Failed | 0 |
| `COMPLETE` | Complete | 1 |
| `INCOMPLETE` | Incomplete | 0 |
| `MATCH` | Match | 1 |
| `MISMATCH` | Mismatch | 0 |
| `ROUTED` | Routed | 1 |
| `SKIPPED` | Skipped | 1 |

## 15. `failure_categories`

Technical/workflow failures only.

| code | name | retryable | human_review_default |
|---|---|---:|---:|
| `FHIR_HTTP_ERROR` | FHIR HTTP Error | 1 | 1 |
| `FHIR_MALFORMED_JSON` | FHIR Malformed JSON | 0 | 1 |
| `FHIR_INVALID_SCHEMA` | FHIR Invalid Schema | 0 | 1 |
| `FHIR_MISSING_SERVICE_REQUEST` | FHIR Missing Service Request | 0 | 1 |
| `FHIR_BROKEN_CONDITION_REFERENCE` | FHIR Broken Condition Reference | 0 | 1 |
| `FHIR_UNSUPPORTED_RESOURCE_TYPE` | FHIR Unsupported Resource Type | 0 | 1 |
| `AI_PROVIDER_FAILED` | AI Provider Failed | 1 | 1 |
| `AI_OUTPUT_INVALID` | AI Output Invalid | 0 | 1 |
| `PERSISTENCE_ERROR` | Persistence Error | 1 | 1 |

## 16. `reasons`

`reason_code` values are globally unique and domain-prefixed.

### Evidence mismatch reasons

| reason_code | reason_type_code | meaning |
|---|---|---|
| `EVIDENCE_MISMATCH_SERVICE_CODE` | `EVIDENCE_MISMATCH` | Requested service code differs |
| `EVIDENCE_MISMATCH_DIAGNOSIS_CODE` | `EVIDENCE_MISMATCH` | Diagnosis code differs |
| `EVIDENCE_DOCUMENT_NOT_FOUND` | `EVIDENCE_MISMATCH` | Required/supporting document not found |

### Case close reasons

| reason_code | reason_type_code | meaning |
|---|---|---|
| `CASE_CLOSE_COMPLETED` | `CASE_CLOSE` | Normal case processing completed |
| `CASE_CLOSE_REQUEST_WITHDRAWN` | `CASE_CLOSE` | Request withdrawn |
| `CASE_CLOSE_DUPLICATE` | `CASE_CLOSE` | Duplicate case closed |
| `CASE_CLOSE_SUPERSEDED` | `CASE_CLOSE` | Superseded by another case |
| `CASE_CLOSE_ADMINISTRATIVE` | `CASE_CLOSE` | Administrative close |
| `CASE_CLOSE_OTHER` | `CASE_CLOSE` | Other; explanatory text required |

### Logical-delete reasons

| reason_code | reason_type_code | meaning |
|---|---|---|
| `DELETE_DUPLICATE_RECORD` | `DELETE` | Duplicate persistent record |
| `DELETE_ERRONEOUS_RECORD` | `DELETE` | Record created in error |
| `DELETE_ADMINISTRATIVE` | `DELETE` | Controlled administrative deletion |

### Human-review reasons

| reason_code | reason_type_code | meaning |
|---|---|---|
| `HUMAN_REVIEW_EVIDENCE_MISMATCH` | `HUMAN_REVIEW` | Deterministic evidence mismatch |
| `HUMAN_REVIEW_FHIR_FAILURE` | `HUMAN_REVIEW` | FHIR/integration failure |
| `HUMAN_REVIEW_AI_FAILURE` | `HUMAN_REVIEW` | AI failure or invalid structured output |
| `HUMAN_REVIEW_AMBIGUITY` | `HUMAN_REVIEW` | Material ambiguity requires a human |

## 17. `human_review_statuses`

| code | name | terminal |
|---|---|---:|
| `REQUESTED` | Requested | 0 |
| `IN_PROGRESS` | In Progress | 0 |
| `COMPLETED` | Completed | 1 |
| `CANCELLED` | Cancelled | 1 |

## 18. `human_review_outcomes`

No autonomous clinical approval/denial outcome is defined.

| code | name | returns_to_workflow | closes_case |
|---|---|---:|---:|
| `CONTINUE_WORKFLOW` | Continue Workflow | 1 | 0 |
| `REQUEST_MORE_INFORMATION` | Request More Information | 0 | 0 |
| `ESCALATE` | Escalate | 0 | 0 |
| `CLOSE_CASE` | Close Case | 0 | 1 |

## 19. `discovery_item_types`

| code | name |
|---|---|
| `STAKEHOLDER` | Stakeholder |
| `FUNCTIONAL_REQUIREMENT` | Functional Requirement |
| `TECHNICAL_REQUIREMENT` | Technical Requirement |
| `MISSING_INFORMATION` | Missing Information |
| `RISK` | Risk |
| `ACCEPTANCE_CRITERION` | Acceptance Criterion |

## 20. `ai_task_types`

These align with the current structured AI contract.

| code | name |
|---|---|
| `SUMMARIZE_NARRATIVE` | Summarize Narrative |
| `IDENTIFY_AMBIGUITY` | Identify Ambiguity |
| `IDENTIFY_TEXT_INCONSISTENCIES` | Identify Text Inconsistencies |
| `SUGGEST_CLARIFYING_QUESTIONS` | Suggest Clarifying Questions |

## 21. Actor identifier convention

Phase 1 examples:

- `SYSTEM:FASTAPI`
- `SYSTEM:LANGGRAPH`
- `SYSTEM:RULE_ENGINE`
- `SYSTEM:PERSISTENCE`
- `AI:AZURE_OPENAI`
- `HUMAN:SYNTH_REVIEWER_001`

Production authentication/IAM may replace these with authenticated user/service principal IDs.

## 22. Related documentation

- [data_model.md](data_model.md) — canonical data model and normalization rationale
- [data_dictionary.md](data_dictionary.md) — authoritative field-level dictionary
- [constraints_and_indexes.md](constraints_and_indexes.md) — relational integrity, uniqueness, CHECK constraint, and index catalog
- [../decisions/ADR-004-phase1-canonical-data-model.md](../decisions/ADR-004-phase1-canonical-data-model.md) — the architecture decision record for this model
