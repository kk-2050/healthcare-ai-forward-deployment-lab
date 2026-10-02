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
5. **Important or uncertain cases go to human review.** Missing
   information is first handled deterministically through the
   approved, already-authorized information-request process (see
   §7); only if it remains unresolved within that authorized boundary
   does the case route to human review. Low-confidence AI output or
   failed validation still route directly to a human reviewer rather
   than a guessed outcome.
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
   guess (see §8 for the retryable/non-retryable technical-failure and
   security-policy-violation model that governs how that routing
   decision is reached).
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
**The LangGraph workflow is now wired to this persistence layer**
(Task 22): `src/workflow/orchestrator.py` is a pure Python
orchestration function — generates one `trace_id` per run, invokes the
existing LangGraph graph, and persists `workflow_runs`/`audit_events`
via `AuditRepository` — validated end to end against real SQL Server
(see below). `src/api/app.py` now wires it to three HTTP endpoints —
`POST /workflows` (Task 25B, a brand-new run), `POST
/human-review/decisions` (Task 23C-7A), and `POST
/workflows/{trace_id}/resume` (Task 24B-4C) — alongside the
validation-only, non-persistent `POST /cases/validate`.

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

**Wave 2 runtime identity/traceability decisions — now implemented
(Task 22):** the two architecture decisions that were blocking Wave 2
schema design — `trace_id` generation and the
LangGraph-node-to-`workflow_definition_steps` mapping — are resolved
(see [ADR-007](decisions/ADR-007-trace-id-and-workflow-step-mapping.md))
and now have running code behind them: `trace_id` is an
application-generated UUID4, created once per workflow run in
`src/workflow/orchestrator.py`, immediately before `graph.invoke()`;
and every current LangGraph node is explicitly mapped to a stable
`step_code` in `src/workflow/step_mapping.py`, never a raw Python
function name. Both were validated end to end against real SQL Server:
one `trace_id` persisted consistently across one `workflow_runs` row
and six `audit_events` rows, with `workflow_step_id` resolved from the
real `workflow_definition_steps` rows loaded by
`src/db/reference_data.py`. `POST /human-review/decisions` and
`POST /workflows/{trace_id}/resume` (`src/api/app.py`) call into this
orchestration boundary for an existing run's Human Review decision and
same-run/same-trace resume, respectively (Tasks 23C-7A/24B-4C).
**`POST /workflows` (Task 25B, `src/workflow/case_intake_service.py`)
starts a brand-new orchestration run for a fresh/safely-retried case**
— implemented and validated offline (not yet proven against real SQL
Server). That fresh-intake path, and the resume path above, do not
currently supply `step_code_to_workflow_step_id` to the orchestrator,
so some of their audit events have `workflow_step_id = NULL` — the
`workflow_definition_steps` catalog itself remains fully loaded; this
is a current Phase 1 audit-enrichment limitation, not missing
reference data.

## 7. Human-in-the-Loop: Missing-Information Handling and Escalation Boundary

This section documents the two-stage missing-information model and the
universal least-privilege escalation boundary established by
[ADR-008](decisions/ADR-008-least-privilege-escalation-and-missing-information.md)
and [security.md §7](security.md#7-universal-least-privilege-escalation-boundary).
It does not replace or narrow Architecture Principle 5 (§3) or the
Human-in-the-Loop pause/resume preservation described in §6 — it makes
both concrete for the missing-information case specifically.

### 7.1 Stage 1 — deterministic information request (no human review)

When required information/documentation is detected as missing by the
deterministic completeness check, the intended design is:

Completeness check → missing information detected →
`next_action_code = REQUEST_MISSING_INFORMATION` → the request/
retrieval step uses only already-authorized, approved channels →
**no `human_reviews` row is created at this stage** → no permission
elevation, access-control bypass, or unapproved source is used.

Throughout this stage the value remains represented as
`MISSING`/`UNKNOWN` — it is never guessed, inferred, or defaulted and
then treated as verified — and only the minimum necessary PHI/PII or
other sensitive information for the request/retrieval purpose may be
requested, retrieved, persisted, exposed, or transmitted (see
[security.md §8](security.md#8-missing-information-safety-contract)).

**Status: IMPLEMENTED (Step 23C-5C).** `src/workflow/nodes.py`'s
`request_missing_information_node()` and `src/workflow/graph.py`'s
`route_after_completeness()` route a deterministically incomplete case
to this disposition (`workflow_status_code = COMPLETED`,
`next_action_code = REQUEST_MISSING_INFORMATION`), never to Human
Review — no `human_reviews` row is created at this stage. **The actual
external request/notification/response transport (e.g., contacting a
case submitter for the missing document) remains PLANNED — it is not
implemented, and this document does not claim otherwise.**

### 7.2 Stage 2 — unresolved-information escalation to human review

If required information remains unresolved after the approved Stage 1
process, or cannot be obtained using existing approved permissions and
sources, automation stops automated retrieval/processing and
escalates:

→ `HUMAN_REVIEW_REQUIRED` → `reason_code =
HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION` → a `human_reviews` row is
durably persisted → the **same `trace_id`** as the original workflow
run is preserved, consistent with the same-trace-id principle
established in [ADR-007](decisions/ADR-007-trace-id-and-workflow-step-mapping.md)
and already implemented for Task 22's audit trail.

Human review here is a **safety escalation, never a way to obtain
broader access** — a human reviewer records an explicit decision
through the human-review application/service boundary when that
workflow is available; the human review step itself does not grant
the automation any new permission or data source.

**Status: mixed — see the explicit breakdown below. Do not read this
section as claiming Stage 2 routing exists in the graph; it does not.
Human-review persistence, orchestrator wiring, and same-run/same-trace
resume (Tasks 23/24) are complete and validated, as described below.**

**NOT IMPLEMENTED (Stage 2 routing itself):** the escalation signal
(`CaseWorkflowState.missing_information_escalated`), the new
`HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION` reason code being
produced by a real run, and the routing change in the LangGraph graph
that would produce this path remain not implemented in
`src/workflow/graph.py`/`src/workflow/nodes.py` as of this writing.

**IMPLEMENTED AND VALIDATED (persistence/decision-handling layer, and
its orchestrator wiring):** `src/db/human_review_repository.py`,
`src/db/repository.py`, `src/db/case_repository.py`, and
`src/workflow/human_review_service.py` implement durable human-review
persistence, all four approved outcomes (`CONTINUE_WORKFLOW`,
`REQUEST_MORE_INFORMATION`, `ESCALATE`, `CLOSE_CASE`), the shared
caller-owned transaction spanning `human_reviews`/`workflow_runs`/
`prior_authorization_cases`/`audit_events`, and duplicate/cancelled/
idempotent-replay conflict handling. `request_human_review()` **is**
called from `src/workflow/orchestrator.py` (Task 23C-6A): a genuine
`HUMAN_REVIEW_REQUIRED` disposition (FHIR failure, evidence mismatch,
or AI failure) creates a real `human_reviews` row atomically with that
run's `workflow_runs`/`audit_events` writes — no real workflow run is
ever left claiming `HUMAN_REVIEW_REQUIRED` with no durable review
request behind it. This layer, and the resume path described below, is
validated both offline and directly against the real local SQL Server
database: the `CLOSE_CASE` success path, an atomic-rollback failure
path, and the full `HUMAN_REVIEW_REQUIRED` → `CONTINUE_WORKFLOW` →
resume → `COMPLETED` sequence (Task 24B-4E) all pass against real SQL
Server.

**Schema/migration status:** the `human_reviews` / `human_review_statuses`
/ `human_review_outcomes` schema (Alembic revision `f2fb22e3a41e`) **has
been applied to the real local SQL Server database** (Step 23B-6), and
the associated reference data — including the six `CASE_CLOSE_*`
reason rows and, as of Task 24B-4D, `event_types.WORKFLOW_RESUMED` —
is loaded (97 rows across 14 tables; see
[database/reference_data.md](database/reference_data.md)).

**Same-run/same-trace automated post-review continuation (Task 24):
IMPLEMENTED AND VALIDATED**, both offline and against the real local
SQL Server database. A `CONTINUE_WORKFLOW` decision moves the existing
`workflow_runs` row to `PENDING_RESUME`/`CONTINUE_PROCESSING` (an
application-level state transition only); `resume_workflow()`
(`src/workflow/resume_service.py`, exposed as
`POST /workflows/{trace_id}/resume`) then validates eligibility and
persisted case identity, atomically claims the SAME run (a race-safe
conditional `UPDATE`, never read-then-write), and re-invokes the SAME
compiled LangGraph graph on the SAME `trace_id` with fresh
caller-supplied input — this is application-level re-invocation, never
LangGraph checkpoint restoration (no checkpointer exists anywhere in
this project). `WORKFLOW_RESUMED` is recorded, with a deterministic
`event_id` derived from the authorizing `review_id`, only when this
automated continuation actually begins; `WORKFLOW_STARTED` is never
re-emitted; a duplicate resume attempt is rejected safely and changes
nothing.

### 7.3 Universal least-privilege escalation boundary

This principle applies to all automation in this project, not only the
missing-information path above — see
[ADR-008](decisions/ADR-008-least-privilege-escalation-and-missing-information.md)
and [security.md §7](security.md#7-universal-least-privilege-escalation-boundary)
for the full statement. In summary: automation may use only
authenticated APIs it is already configured to call, explicitly
approved FHIR-style/integration endpoints, explicitly approved data
sources, and permissions already granted to the current service
account/user — and must never expand its own permissions, bypass
access controls, fall back to an unapproved source, or retrieve,
persist, expose, or transmit more PHI/PII or other sensitive
information than the task needs.

**Not explicitly allowed = DENY**: an integration, source, endpoint,
retrieval mechanism, or data use is prohibited unless explicitly
approved — the absence of an explicit prohibition is not permission.
Automation remains limited to the permissions already granted to the
current service-account/user at all times.

If the authorized process cannot resolve the missing information,
automation stops further automated retrieval attempts to resolve that
missing information. It continues only with safe deterministic state
handling, audit recording, and routing/escalation to Human Review as
defined in §7.2.

### 7.4 Audit reconstruction

Consistent with Architecture Principle 8 (§3) and the existing audit
design ([database/data_model.md](database/data_model.md)), the audit
trail is expected to make it possible to reconstruct, for any
missing-information or escalation case: what information was needed,
which approved source/component was actually used, the result, why
automation stopped or continued, the reason for human review, the next
workflow action, and the same `trace_id` across the pause/resume
boundary — using only this project's existing structured audit fields.
This review was completed for Tasks 23/24: the audit-event catalog
already covered missing-information and human-review semantics, and
one approved addition, `event_types.WORKFLOW_RESUMED`, was made for
resume semantics (Task 24B-4A design, Task 24B-4D real-SQL load) —
documented and reviewed before loading, per this same rule. Any future
catalog addition must continue to follow the same explicitly-approved,
documented-before-loading discipline. As with
all audit records in this project, secrets, credentials, tokens, raw
LLM prompts/responses, and unnecessary PHI/PII must never be written to
an audit record.

## 8. Failure Handling: Technical Retry, Security-Policy Enforcement, and Safe-Continuation Classification

This section documents the retryable/non-retryable technical-failure
model, the security-policy-violation boundary, and the general
"cannot safely continue automatically" classification established by
[docs/requirements.md](requirements.md) FR-27/FR-28/TR-018/TR-019 and
[security.md §7](security.md#7-universal-least-privilege-escalation-boundary).
It does not replace or narrow Architecture Principle 9 (§3) or §7 —
it makes both concrete for these two failure categories specifically.

### 8.1 Retryable vs. non-retryable technical failure

A technical/integration failure (from the LLM provider or a
healthcare/FHIR-style API) is classified as either retryable
(illustrative, not exhaustive: transient network failure, timeout,
HTTP 429, temporary service unavailability, an appropriate HTTP 5xx
response) or non-retryable (illustrative, not exhaustive: an
authentication/authorization failure against an already-approved
source, invalid request/schema, an invalid provider response, or
another policy-classified non-retryable failure).

An authentication/authorization failure for an otherwise approved
operation may be classified as a non-retryable technical/configuration
failure. An attempted operation that exceeds the permissions already
granted to the current service-account/user is a security-policy
violation under §8.2. A 401/403-style response must therefore be
classified by cause rather than by status code alone.

A retryable failure may be retried only according to an explicitly
approved, bounded, configurable retry policy — retry count, timeout,
and backoff values are configuration, never hard-coded in this
architecture or any implementing code. Retry decisions and outcomes
must be deterministic and auditable. A non-retryable failure is never
retried, and no non-retryable failure — technical or a security-policy
violation — is ever resolved through permission elevation, credential
substitution to obtain broader access, a broader service account,
access-control bypass, or an unapproved fallback source.

When an approved retry policy is exhausted, the outcome is recorded
truthfully as an unresolved technical/provider failure — never
converted into false success, never used to fabricate a result, and
never resolved by broadening permissions or switching to an unapproved
source.

Retry exhaustion does not automatically become `FAILED` and does not
automatically route to Human Review. The resulting route depends on
the approved failure classification and the safe state that can be
established. Business/workflow cases may route to Human Review;
technical cases may use an appropriate technical/error path. `FAILED`
remains reserved for the narrower condition where a safe workflow or
Human Review state cannot be established (see
[reference_data.md §4](database/reference_data.md#4-workflow_statuses)).
Exact canonical status/reason/event mapping remains pending
state/catalog design.

**Status: PLANNED / NOT YET IMPLEMENTED.** No retry policy, retry
configuration, or non-retryable-failure classification exists in code
yet.

### 8.2 Security-policy violation boundary

A security-policy violation (illustrative, not exhaustive: an attempt
to use an unapproved data source or endpoint, an attempt to access
beyond the current service-account/user's existing permissions, an
attempted access-control bypass, an attempted permission expansion, or
another prohibited data-use/retrieval path) is a distinct condition
from missing information (§7), evidence mismatch, ambiguity, AI
uncertainty, or an ordinary non-retryable technical failure (§8.1) —
it is never resolved as any of those.

On detecting a security-policy violation, the system denies the
prohibited action, does not perform the prohibited retrieval/action,
does not broaden permissions or attempt an unapproved fallback,
preserves a safe workflow state, records structured security/audit
evidence, and routes the case to the appropriate security/technical
escalation path. Where technically possible, the prohibited operation
is blocked before any unauthorized retrieval or access occurs.

**Human Review is not a security override.** Human Review must not
authorize, trigger, or be interpreted as permission to expand
automation permissions, broaden access, use an otherwise-prohibited
source, or bypass access controls — the Universal Least-Privilege
Escalation Boundary (§7.3) remains in force before, during, and after
Human Review.

**Status: PLANNED / NOT YET IMPLEMENTED.** No security-policy
enforcement gate exists in code yet. This document does not invent a
dedicated Security Review UI or claim any Security/Compliance
operations workflow is implemented; the exact canonical
reason/event/status/source codes for this path are deferred to future
reference-data/state-model design, the same way Task 23's own
missing-information codes were reviewed before being proposed.

### 8.3 "Cannot safely continue automatically" classification

"Cannot safely continue automatically" is broader than "cannot
resolve missing information," and is never resolved by fabricating an
answer, expanding permissions, bypassing access control, or using an
arbitrary fallback source. Conceptually, at least seven distinct
categories can prevent safe automatic continuation:

1. Unresolved missing information (§7).
2. Evidence conflict/mismatch.
3. Ambiguity or judgment required.
4. AI/provider technical failure (§8.1).
5. Healthcare/FHIR integration failure (§8.1).
6. Security-policy violation (§8.2).
7. Severe system/persistence failure.

These are not forced into a single generic Human Review reason. Their
exact canonical status/reason/event/source-component mapping is not
decided by this document — it remains pending future
reference-data/state-model design.

### 8.4 Audit reconstruction (retry and security)

Extending §7.4's audit-reconstruction principle to this section's
scope, the audit trail is expected to make it possible to reconstruct:

- For a retry/technical-failure episode: the failure's classification,
  whether retry was permitted, the retry outcome/exhaustion, the
  source/component involved, the final route, and the `trace_id`.
- For a security-policy-violation episode: which policy boundary was
  encountered, the source/endpoint/component involved, the DENY/block
  result, why automated processing stopped or changed route, the next
  safe action, and the `trace_id`.

As elsewhere in this document, this never requires secrets, API keys,
tokens, credentials, connection strings, raw provider responses,
unnecessary raw prompts, unnecessary PHI/PII, or unnecessary clinical
content — safe, structured facts are sufficient.

## 9. Related Documents

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
- [decisions/ADR-008-least-privilege-escalation-and-missing-information.md](decisions/ADR-008-least-privilege-escalation-and-missing-information.md)
