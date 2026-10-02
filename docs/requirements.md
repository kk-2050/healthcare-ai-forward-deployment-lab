<!--
File Name: requirements.md
Purpose: Defines business, functional, technical, acceptance, risk, assumption, and clarification requirements for Phase 1.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# Requirements — Phase 1

## 1. Purpose

Demonstrate the requirements-gathering, architecture, and delivery
skills of a healthcare Data Forward Deployment Engineer (FDE) through a
realistic — but synthetic-data-only — Prior Authorization workflow
support prototype.

This document translates an ambiguous client need into a concrete,
testable, traceable requirements baseline for Phase 1, following the
chain:

**Business Requirement → Functional Requirement → Technical Requirement
→ Planned Implementation → Planned Test → Planned Audit Event**

This is a **design/requirements document**. Nothing in this file
describes implemented behavior unless it already exists — see
[README.md](../README.md) for current implementation status.

## 2. Use Case

**Prior Authorization workflow support.**

A synthetic prior authorization request (patient/case data, requested
service, supporting clinical notes) enters the system. The system:

1. Validates the structure and completeness of the request.
2. Applies explicit business rules to the request.
3. Where the request contains ambiguity, unstructured text, or requires
   summarization, invokes an LLM to assist — never to decide.
4. Routes uncertain, incomplete, or high-impact cases to a human
   reviewer.
5. Persists the case, workflow state, and a full audit trail.

## 3. Source Client Request (Synthetic)

> "We want to reduce the amount of manual work required for prior
> authorization requests. Our reviewers spend too much time identifying
> incomplete cases and determining which requests need additional
> documentation."

This is a synthetic/illustrative client statement used to drive
requirements definition for this portfolio project. It is not sourced
from a real client engagement, a real payer, or a real clinical policy.

## 4. Phase 1 Business Goals

1. Reduce manual effort spent identifying incomplete prior
   authorization requests.
2. Identify missing required information and documentation
   consistently.
3. Use deterministic validation and business rules before AI.
4. Use AI only for appropriate language-based or ambiguous tasks.
5. Route important, uncertain, incomplete, or failed cases safely to
   human review.
6. Preserve workflow state when waiting for human review.
7. Maintain traceability and auditability.
8. Never allow AI to independently approve or deny clinical care.
9. Use synthetic healthcare data only.
10. Build a working prototype with a clear path to production.

## 5. Requirement ID Convention

| Prefix | Meaning |
|--------|---------|
| BR-### | Business Requirement |
| FR-#   | Functional Requirement (existing IDs kept as originally numbered) |
| TR-### | Technical Requirement |
| NFR-#  | Non-Functional Requirement (existing IDs kept as originally numbered) |
| AC-### | Acceptance Criterion |

Existing `FR-#` and `NFR-#` IDs from the original Phase 1 baseline are
preserved unchanged below; new requirements continue those series.
Newly introduced categories (`BR`, `TR`, `AC`) use the zero-padded
`###` convention from first introduction.

## 6. Business Requirements

| ID | Business Requirement |
|----|-----------------------|
| BR-001 | Reduce manual review effort spent identifying incomplete prior authorization requests, so reviewers spend less time on administrative triage. |
| BR-002 | Improve consistency in identifying missing information and required documentation across cases, reducing rework caused by inconsistent manual screening. |
| BR-003 | Maintain human control over healthcare workflow decisions — the system may validate, route, and recommend, but only an authorized human reviewer makes the final call on any clinical approval or denial outcome. |
| BR-004 | Maintain traceability for how each case was processed: what was validated, what (if anything) the AI suggested, and what a human decided. |
| BR-005 | Support safe AI-assisted workflow processing without allowing AI to autonomously approve or deny clinical care. |
| BR-006 | Deliver a working Phase 1 prototype with a clearly documented path toward a production-viable system, rather than a one-off demo. |

Business requirements about medical necessity criteria or payer
coverage policy are intentionally excluded from Phase 1 — see
[§12 Out of Scope](#12-out-of-scope-phase-1).

## 7. Functional Requirements

Original Phase 1 functional requirements (unchanged except FR-6, which
was corrected by [ADR-008](decisions/ADR-008-least-privilege-escalation-and-missing-information.md):
its original wording — "route cases to human review when information
is missing" — literally conflicted with the already-approved
`migration_plan.md` §7.A target design and the
`workflow_actions.REQUEST_MISSING_INFORMATION.requires_human = 0`
reference-data catalog entry, which both treat a first-pass missing-
information case as an automated outcome, not a human-review case.
This was a genuine pre-existing conflict between two approved
documents, not a reinterpretation — see ADR-008 for the full
investigation):

| ID | Requirement |
|----|-------------|
| FR-1 | The system shall accept a structured prior authorization case (synthetic data only) via an API. |
| FR-2 | The system shall validate all inbound data against explicit schemas before further processing. |
| FR-3 | The system shall apply deterministic business rules prior to invoking any LLM. |
| FR-4 | The system shall use an LLM only for language-oriented tasks (e.g., summarizing clinical notes, classifying free-text intent) and shall constrain LLM output to a validated structured format. |
| FR-5 | The system shall never autonomously produce a final clinical approval or denial outcome — whether via deterministic rules, LLM output, or any combination thereof — without a recorded decision from an authorized human reviewer. |
| FR-6 | Missing required information or documentation shall first be handled deterministically through an approved information-request workflow (no `human_reviews` record is created at this stage). If the required information remains unresolved after that approved process, cannot be obtained through authorized sources and existing permissions, or otherwise requires human judgment (e.g., a business-rule-flagged case, or low-confidence/invalid AI output), the case shall be routed to human review. Automation must never expand its own permissions or use an unapproved source to resolve missing information. |
| FR-7 | The system shall preserve workflow state while a case is pending human review, and resume correctly once a decision is recorded. |
| FR-8 | The system shall persist every case, its workflow transitions, and the final outcome in SQL Server. |
| FR-9 | The system shall record an auditable log entry for every workflow state transition and decision point. |
| FR-10 | The system shall expose workflow status and outcomes through a Streamlit interface for demonstration purposes. |
| FR-11 | The system shall model at least one healthcare/FHIR-style data shape for the case/request payload. |

New functional requirements (traceability baseline expansion):

| ID | Requirement |
|----|-------------|
| FR-12 | The system shall detect and explicitly report missing required information fields in an incoming case, based on the deterministic case schema and business rules. |
| FR-13 | The system shall detect and explicitly report missing required supporting documentation when a deterministic business rule requires it for a given case type. |
| FR-14 | The system shall determine, via deterministic business rules, whether AI-assisted language processing is needed for a given case before invoking the LLM. |
| FR-15 | The system shall skip the LLM step entirely when deterministic processing already produces a complete and unambiguous result. |
| FR-16 | The system shall restrict LLM invocation to an approved set of language-oriented tasks (e.g., summarizing narrative text, detecting ambiguity/inconsistency, suggesting clarification questions). |
| FR-17 | The system shall require LLM responses to conform to a predefined structured output schema. |
| FR-18 | The system shall validate LLM output against the structured schema and applicable safety checks before the output is used downstream. |
| FR-19 | The system shall treat malformed or schema-invalid LLM output as a validation failure and shall not use it as workflow data. |
| FR-20 | The system shall detect LLM/API call failures (e.g., timeout, service error, exception) and route the affected case to a safe fallback rather than fabricate a result. |
| FR-21 | The system shall detect healthcare/FHIR-style API call failures and route the affected case to a safe fallback rather than fabricate a result. |
| FR-22 | The system shall persist workflow state for a case before pausing it for human review. |
| FR-23 | The system shall resume a paused workflow from its persisted state once a human decision has been recorded. |
| FR-24 | The system shall record the human reviewer's decision as a distinct, attributable entry, kept separate from deterministic facts and AI inference. |
| FR-25 | The system shall provide workflow status and key trace events for a case through the UI for demonstration purposes. |
| FR-26 | Missing/unknown information shall remain represented as MISSING/UNKNOWN until verified evidence is received from an approved source, and shall never be guessed, inferred, or defaulted and then treated as verified. Any missing-information request/retrieval operation shall use only integrations, sources, endpoints, retrieval mechanisms, and data uses that have been explicitly approved (deny-by-default: an integration, source, endpoint, retrieval mechanism, or data use is prohibited unless explicitly approved) and shall remain strictly within the permissions already granted to the current service-account/user — permission elevation is never an acceptable way to resolve missing information, regardless of approval status. Only the minimum necessary PHI/PII or other sensitive information for that purpose may be requested, retrieved, persisted, exposed, or transmitted, and access controls shall never be bypassed. If the authorized process cannot resolve the missing information, the system shall stop further automated retrieval attempts, preserve the value as MISSING/UNKNOWN, and route the case to human review; human review shall not expand the automation's own permissions, sources, or access. See [security.md §8](security.md#8-missing-information-safety-contract) for the full contract. |
| FR-27 | Technical/integration failures (e.g., from the LLM provider or a healthcare/FHIR-style API) shall be classified as either retryable (illustrative, not exhaustive: temporary network failure, timeout, HTTP 429, temporary provider/service unavailability, an appropriate HTTP 5xx response) or non-retryable (illustrative, not exhaustive: an authentication/authorization failure against an already-approved source, invalid request/schema, an invalid provider response, or another failure the approved policy classifies as non-retryable). A non-retryable technical failure is distinct from a security-policy violation (FR-28): a non-retryable technical failure does not, by itself, indicate an attempt to exceed permissions or use an unapproved source, and is handled by this requirement, not by FR-28. A retryable failure may be retried only according to an explicitly approved, bounded, configurable retry policy — the system shall never retry a non-retryable failure, and no non-retryable failure, whether technical or a security-policy violation, shall ever be resolved through permission elevation, credential substitution, access-control bypass, a broader service account, or an unapproved fallback source, whether directly or as a side effect of retrying. When an approved retry policy is exhausted, the outcome shall be recorded truthfully as an unresolved technical/provider failure — never converted into false success, never used to fabricate missing information, and never resolved by broadening permissions or switching to an unapproved source — and the case shall be routed through the approved safe failure/escalation path appropriate to its classification (business/Human Review or a technical failure state, as applicable), consistent with FR-20/FR-21. |
| FR-28 | A security-policy violation (illustrative, not exhaustive: an attempt to use an unapproved data source or endpoint, an attempt to access beyond the current service-account/user's existing permissions, an attempted access-control bypass, an attempted permission expansion, or another prohibited data-use/retrieval path) is a distinct condition from missing information, evidence ambiguity, AI uncertainty, or an ordinary non-retryable technical failure (FR-27), and shall never be resolved as any of those. On detecting a security-policy violation, the system shall deny the prohibited action, shall not perform the prohibited retrieval/action, shall not broaden permissions or attempt an unapproved fallback, shall preserve a safe workflow state, shall record structured security/audit evidence, and shall route the case to the appropriate security/technical escalation path. Where technically possible, the prohibited operation shall be blocked before any unauthorized retrieval or access occurs. Human Review shall not authorize, trigger, or be interpreted as permission to expand automation permissions, broaden access, use an otherwise prohibited source, or bypass access controls. |

**Note:** FR-27/FR-28 do not redefine `workflow_statuses.FAILED`, which
remains reserved for a technical/workflow failure where a safe
workflow/Human Review state cannot be established (see
[architecture.md §6](architecture.md#6-database-design) /
[reference_data.md §4](database/reference_data.md#4-workflow_statuses)).
A non-retryable technical failure (FR-27) and a security-policy
violation (FR-28) are distinct conditions, routed through different
failure/escalation paths appropriate to their own classification —
neither is automatically forced into a single Human Review reason.

**Note:** No functional requirement in this document specifies or
implies automatic clinical approval or denial by the system. This
Phase 1 prototype does not autonomously make clinical approval or
denial decisions. Any final clinical approval or denial decision
remains the responsibility of an authorized human reviewer (see FR-5,
§10 AI Responsibility Boundary).

## 8. Technical Requirements

Technical requirements map the functional requirements above to the
approved Phase 1 architecture (see [architecture.md](architecture.md)
and [decisions/](decisions/)). These describe intended technical
behavior, not implemented code.

| ID | Technical Requirement | Supports |
|----|------------------------|----------|
| TR-001 | Pydantic models must validate all API inputs before workflow execution begins. | FR-2 |
| TR-002 | FastAPI must expose the Phase 1 backend contract consumed by the Streamlit UI. | FR-1, FR-10, FR-25 |
| TR-003 | Deterministic Python business-rule functions must execute — and complete — before any LLM invocation, including missing-information/documentation checks. | FR-3, FR-12, FR-13, FR-14, FR-15 |
| TR-004 | LangGraph must represent explicit workflow nodes and conditional edges for validation, business rules, the AI step, human review, and persistence. | FR-6, FR-22, FR-23 |
| TR-005 | LLM responses must conform to a predefined structured schema (e.g., a Pydantic model) and be validated before downstream use. | FR-4, FR-16, FR-17, FR-18, FR-19 |
| TR-006 | LLM invocation must be restricted, in code, to an approved set of language-oriented task types. | FR-16 |
| TR-007 | LLM/API call failures (timeout, exception, service error) must be caught and routed to a safe fallback path rather than produce a fabricated result. | FR-20 |
| TR-008 | Healthcare/FHIR-style API call failures must be caught and routed to a safe fallback path rather than produce a fabricated result. | FR-21 |
| TR-009 | SQL Server must persist case data, workflow state, human-review decisions, and audit events required by Phase 1. | FR-8, FR-22, FR-24 |
| TR-010 | Human-review pending state must be persisted to SQL Server — not only held in process memory — so it survives an application restart. | FR-22, FR-23 |
| TR-011 | When a recorded human decision requires return to automated workflow processing, resumption must read the persisted `workflow_runs`/`human_reviews` state and continue post-review processing within the same `workflow_runs` row and the same `trace_id`, without unnecessarily replaying already-completed external/API/AI steps, until the workflow reaches the appropriate next action or terminal disposition. A separate workflow run with a new `trace_id` is not a resume of the paused run. | FR-23, FR-7 |
| TR-012 | Every significant workflow transition must emit a structured audit event that distinguishes deterministic results, AI-derived inference, and human decisions. | FR-9, FR-24 |
| TR-013 | Streamlit must consume the FastAPI backend/workflow rather than duplicate core business logic. | FR-10, FR-25 |
| TR-014 | pytest must cover deterministic business rules, workflow routing, and LLM/API/healthcare-API failure paths. | NFR-6 |
| TR-015 | All secrets and connection configuration (Azure OpenAI, SQL Server) must be supplied via environment variables, never hard-coded. | NFR-3 |
| TR-016 | Business-sensitive, configurable thresholds (e.g., confidence thresholds, retry limits) must be externalized to configuration. | NFR-4 |
| TR-017 | Any missing-information request/retrieval component must enforce the Missing Information Safety Contract (see [security.md §8](security.md#8-missing-information-safety-contract)): use only explicitly approved integrations/sources/endpoints/retrieval mechanisms/data uses, remain strictly within permissions already granted to the current service-account/user (never elevated), apply deny-by-default, request/retrieve/persist/expose/transmit only minimum-necessary PHI/PII or other sensitive information, and stop further retrieval attempts — continuing only safe deterministic state handling, audit recording, and Human Review routing — when the authorized process cannot resolve the missing information. | FR-26 |
| TR-018 | Any retry of a classified-retryable technical/integration failure must be governed by an explicitly approved, bounded, and configurable retry policy (retry count, timeout, and backoff values are configuration, not hard-coded — no specific values are prescribed by this requirement); retry decisions and outcomes must be deterministic and auditable, and a non-retryable failure (including any access/authorization failure) must never be retried. | FR-27 |
| TR-019 | A security-policy enforcement gate must classify an attempted unapproved-source/endpoint use, an attempted access beyond existing service-account/user permissions, or another prohibited data-use/retrieval path as a security-policy violation distinct from ordinary technical failure or missing information; the gate must deny the action, block it before unauthorized access where technically possible, and route the case to the appropriate security/technical escalation path without broadening permissions or falling back to an unapproved source. | FR-28 |

**Implementation-status note (non-normative — does not redefine or
weaken TR-011 above):** TR-011 is **SATISFIED, IMPLEMENTED AND
VALIDATED (Task 24)** — `src/workflow/resume_service.py`'s
`resume_workflow()` reads the persisted `workflow_runs`/`human_reviews`
state, atomically claims the run, and continues processing within the
SAME `workflow_runs` row and the SAME `trace_id` (never a new run/new
`trace_id`), validated both offline and against the real local SQL
Server database
(`tests/test_workflow_resume_sql_server_integration.py`). TR-018/
TR-019 are **NOT YET IMPLEMENTED** — no retry policy or
security-policy enforcement gate exists in code yet.

## 9. Non-Functional Requirements

Original Phase 1 non-functional requirements (unchanged):

| ID | Requirement |
|----|-------------|
| NFR-1 | The system shall use only synthetic healthcare data — no real PHI/PII. |
| NFR-2 | The system shall fail safely (route to human review or a clear error state) if the LLM or an external healthcare API is unavailable or returns an invalid response. |
| NFR-3 | No secrets, credentials, or connection strings shall be hard-coded; all shall be supplied via environment variables or git-ignored local configuration. |
| NFR-4 | Business-sensitive configurable values (thresholds, retry limits, workflow limits) shall be externalized to configuration rather than hard-coded. |
| NFR-5 | The workflow's states and routing logic shall be explicit and inspectable (see ADR-002). |
| NFR-6 | Core business rules and workflow routing shall be covered by automated tests (pytest) once implemented. |
| NFR-7 | The design shall favor simplicity and explainability over technical novelty (see architecture principles). |

New non-functional requirements (traceability baseline expansion):

| ID | Requirement |
|----|-------------|
| NFR-8 | Audit records shall distinguish deterministic results, AI-derived inference, and human decisions as separate, clearly labeled categories (auditability). |
| NFR-9 | The system shall not claim or imply HIPAA compliance or production-grade regulatory certification during Phase 1 (honesty of scope). |

## 10. AI Responsibility Boundary

### Deterministic Responsibilities

- Schema validation.
- Required-field validation.
- Missing-information detection when based on explicit requirements.
- Explicit business rules.
- Workflow routing rules.
- Determining whether AI assistance is needed.
- Routing a case to human review.
- Recommending workflow next steps.
- Audit-event creation.

Deterministic rules validate, detect, route, and recommend only — they
do not autonomously approve or deny clinical care, and a case may not
receive a final clinical approval or denial outcome without a recorded
decision from an authorized human reviewer (see FR-5, BR-003).

### AI-Appropriate Responsibilities

- Summarizing supplied narrative text.
- Identifying ambiguity.
- Identifying text inconsistencies.
- Suggesting clarification questions.
- Producing structured language-analysis output.

### Human Responsibilities

- Reviewing uncertain or important cases.
- Evaluating context beyond what deterministic rules or the AI can
  assess.
- Accepting, sending back, or escalating workflow actions.
- Making final human decisions.

### Explicitly Forbidden AI Actions

- Autonomous clinical approval.
- Autonomous clinical denial.
- Overriding a human decision.
- Inventing missing clinical facts.
- Inventing payer policy.

## 11. Acceptance Criteria

| ID | Acceptance Criterion |
|----|------------------------|
| AC-001 | Valid synthetic input passes schema validation. |
| AC-002 | Missing required fields are explicitly identified. |
| AC-003 | Missing documentation is explicitly identified when the deterministic rule requires it. |
| AC-004 | A case that does not need language interpretation does not call the LLM. |
| AC-005 | A case requiring language interpretation can invoke the LLM. |
| AC-006 | Malformed LLM structured output is not accepted as valid workflow data. |
| AC-007 | LLM failure routes safely. |
| AC-008 | Healthcare API failure routes safely. |
| AC-009 | Human-review-required cases are persisted before pause. |
| AC-010 | A persisted case can resume after a recorded human decision. |
| AC-011 | Important workflow transitions create traceable audit events. |
| AC-012 | No workflow path autonomously produces a clinical approval or denial. |
| AC-013 | No real PHI/PII or hard-coded secrets are present. |
| AC-014 | When missing information cannot be resolved within the approved authorized boundary, the system preserves the value as MISSING/UNKNOWN, performs no unapproved or access-bypassing retrieval, stops further retrieval attempts, records the required structured audit evidence without secrets or unnecessary PHI/PII, and routes safely to Human Review without expanding automation permissions. |
| AC-015 | A classified-retryable technical/integration failure is retried only within the approved bounded retry policy and either succeeds or is truthfully recorded as exhausted; a classified-non-retryable technical failure is never retried. Neither case produces false success, fabricates missing information, expands permissions, or falls back to an unapproved source. |
| AC-016 | A detected security-policy violation is denied: the prohibited action is not performed (blocked before unauthorized access where technically possible), no permission expansion or access-control bypass occurs, no unapproved fallback source is used, structured security audit evidence is recorded, and the case is routed to the appropriate security/technical escalation path. |

## 12. Phase 1 Requirement Traceability Matrix

Status values used below follow the README's existing convention:
**PLANNED** means the requirement is fully defined with an identified
conceptual implementation target, test ID, and audit event, but no
code has been written yet (see
[README.md — Current Project Status](../README.md#4-current-project-status)).
This matrix has not been re-walked row-by-row since Task 22, so most
rows below still show PLANNED even though real code now exists behind
parts of them — see
[README.md — Current Project Status](../README.md#4-current-project-status)
for the authoritative, currently accurate implementation status. Two
rows have been updated to reflect Tasks 23/24, now complete: the
BR-003 row (`HUMAN_REVIEW_REQUIRED` persistence, including the real
`human_reviews` row created atomically with it) and the BR-003/BR-004
resume row (FR-23/FR-24/FR-7, TR-010/TR-011 — same-run/same-trace
resume, `resume_workflow()`, `WORKFLOW_RESUMED`), both now
**IMPLEMENTED AND VALIDATED**, offline and against the real local SQL
Server database. Real code also exists behind part of the BR-004/
FR-8/FR-9 row (`src/workflow/orchestrator.py` persists workflow
transitions and audit events to SQL Server), not yet updated here.
"Planned Implementation" entries name conceptual components, not
actual files, unless such a file already exists in the repository.

| Business Req | Functional Req | Technical Req | Planned Implementation | Planned Test | Planned Audit Event | Status |
|---|---|---|---|---|---|---|
| BR-001 | FR-1, FR-2 | TR-001, TR-002 | Pydantic case model; FastAPI request handler | TEST-001 | case_received, validation_completed | PLANNED |
| BR-001, BR-002 | FR-12, FR-13 | TR-003 | Deterministic validation service | TEST-002 | missing_information_detected | PLANNED |
| BR-005 | FR-3, FR-14, FR-15 | TR-003, TR-004 | Deterministic validation service; LangGraph routing node | TEST-003 | business_rules_completed | PLANNED |
| BR-005 | FR-4, FR-16, FR-17 | TR-005, TR-006 | Azure LLM adapter | TEST-004 | llm_requested | PLANNED |
| BR-005 | FR-18, FR-19 | TR-005 | Azure LLM adapter | TEST-005 | llm_output_validation_failed | PLANNED |
| BR-005 | FR-20 | TR-007 | Azure LLM adapter | TEST-006 | llm_call_failed | PLANNED |
| BR-002 | FR-21 | TR-008 | Healthcare/FHIR-style API adapter | TEST-007 | healthcare_api_failed | PLANNED |
| BR-003 | FR-6, FR-22 | TR-004, TR-009, TR-010 | LangGraph routing node; human-review state handler; SQL persistence layer | TEST-008 | human_review_required, workflow_paused | IMPLEMENTED AND VALIDATED |
| BR-003, BR-004 | FR-23, FR-24, FR-7 | TR-010, TR-011 | Human-review state handler (`src/workflow/human_review_service.py`, `src/workflow/resume_service.py`) | TEST-009 | human_decision_recorded, workflow_resumed (`WORKFLOW_RESUMED`) | IMPLEMENTED AND VALIDATED |
| BR-002, BR-003, BR-004 | FR-6, FR-26 | TR-017 | Missing-information request/retrieval component; deterministic completeness/routing logic; human-review state handler (see [security.md §8](security.md#8-missing-information-safety-contract)) | TEST-013 | Stage 1: `workflow_runs.next_action_code = REQUEST_MISSING_INFORMATION` (no `human_reviews` row); Stage 2: unresolved Human Review routing — exact canonical event/reason mapping pending state/catalog design | PLANNED |
| BR-002, BR-005 | FR-27 | TR-018 | Retry-policy component (LLM adapter / FHIR-style integration client) | TEST-014 | failure classification (retryable/non-retryable), retry outcome/exhaustion — exact canonical audit/reference-data mapping pending state/catalog design | PLANNED |
| BR-003, BR-004 | FR-28 | TR-019 | Security-policy enforcement gate | TEST-015 | security-policy DENY/block evidence — exact canonical audit/reference-data mapping pending state/catalog design | PLANNED |
| BR-004 | FR-8, FR-9 | TR-009, TR-012 | SQL persistence layer; audit service | TEST-010 | (all events in §12.1 Audit Event Vocabulary) | PLANNED |
| BR-006 | FR-10, FR-25 | TR-002, TR-013 | Streamlit UI | TEST-011 | n/a (status display only) | PLANNED |
| BR-005 | FR-5 | TR-003, TR-004 | Deterministic validation service; LangGraph routing node (constraint enforcement, not a separate build item) | TEST-012 | n/a (verified via AC-012) | PLANNED |

### 12.1 Audit Event Vocabulary

Planned audit event names (small, consistent, snake_case):

- `case_received`
- `validation_completed`
- `missing_information_detected`
- `business_rules_completed`
- `llm_requested`
- `llm_output_validation_failed`
- `llm_call_failed`
- `healthcare_api_failed`
- `human_review_required`
- `workflow_paused`
- `human_decision_recorded`
- `workflow_resumed`

## 13. Assumptions, Clarifications Needed (TBD), and Out of Scope

### 13.1 TBD / Needs Clarification

- Exact payer-specific documentation requirements.
- Exact source healthcare system(s) to integrate with.
- Exact FHIR resources/endpoints to be modeled.
- Expected request volume.
- SLA / response-time requirements.
- Production authentication/authorization model.
- Production deployment topology.

None of the above are guessed or assumed in this document; they remain
open until explicitly clarified.

### 13.2 Out of Scope (Phase 1)

- Real clinical decision-making or medical advice.
- Real payer policy automation or medical necessity criteria.
- Integration with real payer systems or real EHR/FHIR servers.
- Production PHI processing.
- Production-grade authentication, authorization, and multi-tenant
  security (see [production_roadmap.md](production_roadmap.md)).
- Production HIPAA compliance certification.
- Use of any real patient or member data.
- Docker.
- Full Azure application deployment.
- Kafka, Kubernetes, Redis, or other distributed infrastructure.

## 14. Related Documents

- [architecture.md](architecture.md)
- [security.md](security.md)
- [production_roadmap.md](production_roadmap.md)
- [decisions/](decisions/)
