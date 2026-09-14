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

This document translates the stated project goals into concrete
functional and non-functional requirements for Phase 1.

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

## 3. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | The system shall accept a structured prior authorization case (synthetic data only) via an API. |
| FR-2 | The system shall validate all inbound data against explicit schemas before further processing. |
| FR-3 | The system shall apply deterministic business rules prior to invoking any LLM. |
| FR-4 | The system shall use an LLM only for language-oriented tasks (e.g., summarizing clinical notes, classifying free-text intent) and shall constrain LLM output to a validated structured format. |
| FR-5 | The system shall never allow an LLM to independently produce a final approval or denial outcome. |
| FR-6 | The system shall route cases to human review when information is missing, when business rules require it, or when AI output is low-confidence or fails validation. |
| FR-7 | The system shall preserve workflow state while a case is pending human review, and resume correctly once a decision is recorded. |
| FR-8 | The system shall persist every case, its workflow transitions, and the final outcome in SQL Server. |
| FR-9 | The system shall record an auditable log entry for every workflow state transition and decision point. |
| FR-10 | The system shall expose workflow status and outcomes through a Streamlit interface for demonstration purposes. |
| FR-11 | The system shall model at least one healthcare/FHIR-style data shape for the case/request payload. |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | The system shall use only synthetic healthcare data — no real PHI/PII. |
| NFR-2 | The system shall fail safely (route to human review or a clear error state) if the LLM or an external healthcare API is unavailable or returns an invalid response. |
| NFR-3 | No secrets, credentials, or connection strings shall be hard-coded; all shall be supplied via environment variables or git-ignored local configuration. |
| NFR-4 | Business-sensitive configurable values (thresholds, retry limits, workflow limits) shall be externalized to configuration rather than hard-coded. |
| NFR-5 | The workflow's states and routing logic shall be explicit and inspectable (see ADR-002). |
| NFR-6 | Core business rules and workflow routing shall be covered by automated tests (pytest) once implemented. |
| NFR-7 | The design shall favor simplicity and explainability over technical novelty (see architecture principles). |

## 5. Out of Scope (Phase 1)

- Real clinical decision-making or medical advice.
- Integration with real payer systems or real EHR/FHIR servers.
- Production-grade authentication, authorization, and multi-tenant
  security (see [production_roadmap.md](production_roadmap.md)).
- Use of any real patient or member data.

## 6. Related Documents

- [architecture.md](architecture.md)
- [security.md](security.md)
- [production_roadmap.md](production_roadmap.md)
- [decisions/](decisions/)
