<!--
File Name: ADR-007-trace-id-and-workflow-step-mapping.md
Purpose: Records the approved trace_id generation point and the LangGraph node to workflow_definition_steps step_code mapping strategy
Creation Date: 2026-09-18
Author: K.Kashiwagi
-->

# ADR-007: trace_id Generation Point and Workflow-Step Mapping

## Status
Accepted

## Context
Wave 1 of the canonical database foundation is complete ([[ADR-006-first-revision-and-brownfield-strategy.md]]). [[../database/migration_plan.md]] §16 lists two decisions as OPEN and blocking Wave 2 (`prior_authorization_cases`, `workflow_definitions`/`workflow_definition_steps`, target `workflow_runs`/`audit_events`):

1. Where a `trace_id` is generated, once the workflow is wired to persistence.
2. How current LangGraph node names translate into the stable `workflow_definition_steps.step_code`/`workflow_step_id` values that `audit_events.workflow_step_id` will reference.

Direct inspection of the current implementation (not prior summaries) found:

- `src/workflow/state.py`'s `CaseWorkflowState` has no `trace_id` field at all.
- `src/workflow/graph.py` registers 9 LangGraph nodes: `retrieve_healthcare_evidence`, `evaluate_evidence_consistency`, `evaluate_completeness`, `evaluate_ai_requirement`, `complete`, `human_review_required`, `ai_analysis_required`, `run_ai_analysis`, `ai_analysis_complete`. `build_case_workflow_graph()` is a factory that is called only from `tests/test_workflow_graph.py` — no application code invokes the graph yet.
- `src/api/app.py` exposes only `POST /cases/validate`, which calls `evaluate_completeness()` directly and never touches the graph, the AI service, or the database. No orchestration boundary that calls `graph.invoke()` exists anywhere in `src/`.
- `src/workflow/nodes.py` appends free-text strings (e.g. `"healthcare_evidence_retrieved"`, `"ai_provider_failed"`) to `state["processing_steps"]`. These are implementation-derived trace strings, not a controlled vocabulary, and are never persisted today (no persistence is wired to the workflow at all).
- [[../database/data_model.md]] §12 already establishes that internal LangGraph node names must never be persisted as business codes, for the separate `workflow_actions` table. §14 already directs that `trace_id` be an application-generated identifier, but does not say where it is generated.
- [[../database/reference_data.md]] §7 already proposes a concrete `workflow_definition_steps` seed set (`CASE_VALIDATION`, `FHIR_RETRIEVAL`, `EVIDENCE_CONSISTENCY`, `COMPLETENESS_CHECK`, `AI_ROUTING`, `AI_ANALYSIS`, `HUMAN_REVIEW`, `COMPLETE`) and §11 a separate `event_types` vocabulary for outcomes (e.g. `FHIR_RETRIEVAL_FAILED`, `AI_ANALYSIS_FAILED`).

This ADR resolves both decisions. It creates no code, no migration revision, and executes no database change — Wave 2 implementation, including any orchestration boundary that calls the graph, remains separate future work.

## Decision

### A. trace_id generation point
1. **`trace_id` is generated exactly once per workflow run, by application code, immediately before the first `graph.invoke()` call for that run.** It is a UUID4 string (`str(uuid.uuid4())`), the same pattern already used by `AuditEvent.event_id` in `src/models/audit.py`.
2. **The generation point is the future workflow-orchestration boundary — not a node, not `CaseWorkflowState`, not the API's Pydantic validation step, and not SQL Server.** No node in `src/workflow/nodes.py` may generate or regenerate a `trace_id`. No audit-logging code may generate its own `trace_id` independently of the run it is recording. SQL Server never generates `trace_id` as an identity/sequence value.
3. **This orchestration boundary does not exist in application code today** (see Context) and this ADR does not create it. When it is built (a future implementation task), it is the single call site responsible for: assigning `trace_id`, constructing the initial `CaseWorkflowState`, and calling `graph.invoke()`. No new service layer is invented by this ADR; the exact module that will house this boundary (e.g. an addition to `src/api/app.py`, or a new orchestration module) is an implementation-task decision, not decided here.
4. **One workflow run = one `trace_id`.** Processing the same case again as a new run gets a new `trace_id`. Pausing a run for human review and resuming it later keeps the same `trace_id` — see Human-Review Resume Semantics below.
5. **`trace_id` must be threaded through workflow state once persistence is wired**, so it is available to deterministic processing, AI processing, integration events, persistence, audit events, and human-review continuation. Adding a `trace_id` field to `CaseWorkflowState` is Wave 2 implementation work, not performed by this ADR.

### B. LangGraph node → workflow step_code mapping
1. **Python node names are an implementation detail. `workflow_definition_steps.step_code` is the stable, persisted contract.** No code may derive a persisted step from `function.__name__` or any other Python implementation detail.
2. **The mapping from LangGraph node to `step_code` must be explicit, testable, and centralized in one application location** — not duplicated inside each node. This mapping module is Wave 2 implementation work; it is not created by this ADR.
3. **The approved mapping** (derived from the current graph in `src/workflow/graph.py`, reconciled against the `workflow_definition_steps` seed set already proposed in [[../database/reference_data.md]] §7):

   | LangGraph node (`src/workflow/graph.py`) | → step_code | Plain-English purpose |
   |---|---|---|
   | *(none — occurs before graph invocation, via Pydantic)* | `CASE_VALIDATION` | Structural validation of the submitted case (`PriorAuthorizationCase`), already enforced by Pydantic before the graph runs. No graph node exists for this step; it is recorded, if at all, by the future orchestration boundary, not by a node. |
   | `retrieve_healthcare_evidence` | `FHIR_RETRIEVAL` | Retrieve synthetic FHIR-style evidence for the case. |
   | `evaluate_evidence_consistency` | `EVIDENCE_CONSISTENCY` | Compare submitted case facts against retrieved evidence. |
   | `evaluate_completeness` | `COMPLETENESS_CHECK` | Deterministic required-information check. |
   | `evaluate_ai_requirement` | `AI_ROUTING` | Deterministic decision on whether an AI task is needed. |
   | `ai_analysis_required` | `AI_ANALYSIS` | Transient marker immediately before AI execution — same logical step as `run_ai_analysis` below; both represent the one `AI_ANALYSIS` step in `workflow_definition_steps`. |
   | `run_ai_analysis` | `AI_ANALYSIS` | Executes the AI-assisted analysis task and records the outcome. |
   | `human_review_required` | `HUMAN_REVIEW` | Routes the case to a human reviewer. |
   | `complete` | `COMPLETE` | Terminal completion — deterministic-only path (no AI task was needed). |
   | `ai_analysis_complete` | `COMPLETE` | Terminal completion — AI-assisted path. Reached via a different route than `complete`, but both are the same terminal `COMPLETE` step; the deterministic-vs-AI-assisted distinction is already preserved separately by `workflow_status_code` (`COMPLETE` vs `AI_ANALYSIS_COMPLETE`) and by the AI outcome's own audit event, so `workflow_definition_steps` does not need a second terminal step code to carry that same distinction again. |

4. **Sub-outcome strings are not steps — they are event types.** The current `processing_steps` list conflates two different concerns: *which step ran* (e.g. `"healthcare_evidence_retrieved"`) and *what specifically happened within that step* (e.g. `"evidence_mismatch_detected"`, `"ai_provider_failed"`, `"ai_output_validation_failed"`, `"healthcare_integration_failed"`). Wave 2 separates these: `workflow_step_id` (via the mapping above) records which step; `event_type_code` (from the `event_types` vocabulary already proposed in [[../database/reference_data.md]] §11, e.g. `FHIR_RETRIEVAL_FAILED`, `AI_ANALYSIS_FAILED`) records the specific outcome, as its own `audit_events` row. No new event_type codes are invented by this ADR.
5. **This mapping table is the current, reviewed answer, not a guess extrapolated from the task's illustrative examples.** It was derived by reading `src/workflow/graph.py` and `src/workflow/nodes.py` directly and reconciling every current node against the step_code set already proposed in `reference_data.md` §7. If a future graph change adds, removes, or renames a node, this table must be updated in the same reviewed change — not silently reinterpreted.

## Prototype `processing_step` Transition
The current prototype `audit_events.processing_step` (free text, e.g. `evidence_consistency_evaluated`) has no fixed vocabulary and is not migrated. Per [[ADR-006-first-revision-and-brownfield-strategy.md]], the existing Task 18B synthetic rows are disposable and are not carried forward by any data migration; the Wave 2 controlled prototype rebuild replaces the prototype schema (including `processing_step`) with the canonical `workflow_step_id` design directly, rather than deriving one from the other. No complex text-to-code data migration is designed here or needed.

## Human-Review Resume Semantics
- While a workflow run is paused pending human review, `trace_id` and workflow-run identity remain unchanged.
- Resuming that run continues under the same `trace_id`, preserving chronological continuity of its `audit_events`.
- A separate, new workflow run for the same case (not a resume) always receives a new `trace_id`.
- No pause/resume mechanism is implemented by this ADR; these are constraints on the future Wave 2/4 implementation (human-review persistence remains a `docs/production_roadmap.md`/Wave 4 concern).

## Consequences
- Wave 2 implementation work (adding `trace_id` to `CaseWorkflowState`, building the orchestration boundary, building the node→step_code mapping module, wiring `workflow_definition_steps` seed data) can now proceed against a settled identifier and mapping contract, without re-litigating either decision mid-implementation.
- The audit trail's persisted meaning (`step_code`, `event_type_code`) is decoupled from Python function names, so nodes can be renamed/refactored later without rewriting historical audit records' meaning.
- `workflow_definition_steps` gains one entry (`CASE_VALIDATION`) with no corresponding current graph node — this is expected, not an error; it represents a validation step that happens before graph invocation.
- No code changes result from this ADR. `CaseWorkflowState`, `src/workflow/graph.py`, and `src/workflow/nodes.py` are unchanged; the mapping above is a documented design contract for the future Wave 2 implementation task to follow, not code that exists yet.

## Alternatives Considered

**Alternative A — Generate `trace_id` inside the first LangGraph node instead of before `graph.invoke()`.** Not selected: a node can only affect state after the graph has already started running, so if invocation itself needs to be logged, retried, or checkpointed under a `trace_id`, the ID must already exist before invocation. Generating it inside a node also means the ID would not exist yet if invocation fails immediately (e.g. malformed initial state).

**Alternative B — Let each node record its own `function.__name__` as the persisted step.** Not selected: this is the exact pattern [[../database/data_model.md]] §12 already rejects for `workflow_actions`, for the same reason — a routine internal rename/refactor would silently corrupt the historical meaning of every past audit record referencing that step.

**Alternative C — Derive `workflow_step_id` dynamically from `processing_steps` free text at persistence time (a translation-by-guessing layer).** Not selected: free text has no fixed vocabulary (confirmed directly in `src/workflow/nodes.py`), so any dynamic translation would be guessing, not a reviewed mapping. An explicit, reviewed table (this ADR) is simpler, testable, and matches this project's existing autogenerate/human-review discipline ([[ADR-005-database-schema-migration-strategy.md]]).

## Related
- [[ADR-004-phase1-canonical-data-model.md]]
- [[ADR-005-database-schema-migration-strategy.md]]
- [[ADR-006-first-revision-and-brownfield-strategy.md]]
- [[../architecture.md]]
- [[../database/migration_plan.md]]
- [[../database/data_model.md]]
- [[../database/data_dictionary.md]]
- [[../database/reference_data.md]]
