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

Original Phase 1 functional requirements (unchanged):

| ID | Requirement |
|----|-------------|
| FR-1 | The system shall accept a structured prior authorization case (synthetic data only) via an API. |
| FR-2 | The system shall validate all inbound data against explicit schemas before further processing. |
| FR-3 | The system shall apply deterministic business rules prior to invoking any LLM. |
| FR-4 | The system shall use an LLM only for language-oriented tasks (e.g., summarizing clinical notes, classifying free-text intent) and shall constrain LLM output to a validated structured format. |
| FR-5 | The system shall never autonomously produce a final clinical approval or denial outcome — whether via deterministic rules, LLM output, or any combination thereof — without a recorded decision from an authorized human reviewer. |
| FR-6 | The system shall route cases to human review when information is missing, when business rules require it, or when AI output is low-confidence or fails validation. |
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
| TR-011 | Workflow resumption must read persisted state and continue from the correct LangGraph node once a human decision is recorded. | FR-23, FR-7 |
| TR-012 | Every significant workflow transition must emit a structured audit event that distinguishes deterministic results, AI-derived inference, and human decisions. | FR-9, FR-24 |
| TR-013 | Streamlit must consume the FastAPI backend/workflow rather than duplicate core business logic. | FR-10, FR-25 |
| TR-014 | pytest must cover deterministic business rules, workflow routing, and LLM/API/healthcare-API failure paths. | NFR-6 |
| TR-015 | All secrets and connection configuration (Azure OpenAI, SQL Server) must be supplied via environment variables, never hard-coded. | NFR-3 |
| TR-016 | Business-sensitive, configurable thresholds (e.g., confidence thresholds, retry limits) must be externalized to configuration. | NFR-4 |

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

## 12. Phase 1 Requirement Traceability Matrix

Status values used below follow the README's existing convention:
**PLANNED** means the requirement is fully defined with an identified
conceptual implementation target, test ID, and audit event, but no
code has been written yet (see
[README.md — Current Project Status](../README.md#4-current-project-status)).
No row's Status column below has been updated to IMPLEMENTED — this
matrix has not been re-walked row-by-row since Task 22. Note, however,
that real code now exists behind parts of the BR-004/FR-8/FR-9 row
(`src/workflow/orchestrator.py` persists workflow transitions and
audit events to SQL Server) and part of the BR-003 row
(`HUMAN_REVIEW_REQUIRED` is persisted correctly, though pause/resume
is not yet built) — see
[README.md — Current Project Status](../README.md#4-current-project-status)
for the authoritative, currently accurate implementation status.
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
| BR-003 | FR-6, FR-22 | TR-004, TR-009, TR-010 | LangGraph routing node; human-review state handler; SQL persistence layer | TEST-008 | human_review_required, workflow_paused | PLANNED |
| BR-003, BR-004 | FR-23, FR-24, FR-7 | TR-010, TR-011 | Human-review state handler | TEST-009 | human_decision_recorded, workflow_resumed | PLANNED |
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
