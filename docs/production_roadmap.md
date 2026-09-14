<!--
File Name: production_roadmap.md
Purpose: Documents Phase 1 limitations and the planned path toward productionization.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# Phase 2 — Production Roadmap (Summary)

This document summarizes what would need to change or be added to move
this prototype toward a production-viable system. None of this is
implemented in Phase 1; it exists to demonstrate prototype-to-production
planning as part of the FDE portfolio objective.

## 1. Data & Compliance

- Replace all synthetic data with a formal process for handling real
  PHI/PII under HIPAA (and any other applicable regulatory frameworks).
- Business Associate Agreements (BAAs) with any third-party services
  that would touch real PHI (including the LLM provider).
- Data retention, minimization, and deletion policies.
- Formal audit logging retention policy, not just the presence of an
  audit trail.

## 2. Security

- Authentication and authorization (e.g., OAuth2/OIDC, role-based
  access control) for API and Streamlit access — Phase 1 has none.
- Secrets management via a managed vault (e.g., Azure Key Vault) rather
  than local `.env` files.
- Network isolation (private endpoints, VNETs) for database and LLM
  traffic.
- Encryption at rest and in transit verified end-to-end, not assumed.
- Formal security review / threat modeling, not just the informal
  practices in [security.md](security.md).

## 3. Reliability & Operations

- Real observability: structured logging, metrics, tracing, and
  alerting (Phase 1 has basic audit logging only).
- Defined SLAs/SLOs for the workflow, with monitoring against them.
- Retry/backoff and circuit-breaker behavior around external
  dependencies (LLM, healthcare APIs), beyond the basic fail-safe
  behavior in Phase 1.
- Horizontal scalability plan for the API and workflow layer.
- Disaster recovery / backup strategy for SQL Server data.

## 4. Integration

- Real FHIR server integration (Phase 1 only models FHIR-style shapes),
  including proper conformance to FHIR profiles relevant to prior
  authorization (e.g., Da Vinci PAS).
- Real payer/EHR system integration contracts, authentication, and
  error handling.

## 5. AI/ML Governance

- Formal model evaluation, bias/fairness review, and ongoing monitoring
  of LLM output quality in production.
- Documented human-in-the-loop review SLAs and escalation paths.
- Versioning and change management for prompts/model configuration,
  with rollback capability.
- Clear regulatory/compliance review of the AI's role, ensuring it
  remains a decision-support tool and not a decision-maker.

## 6. Engineering Process

- CI/CD pipeline with automated testing gates.
- Infrastructure as code for Azure resources (not present in Phase 1).
- Formal environment separation (dev/test/staging/prod).
- Containerization/orchestration strategy, if warranted by deployment
  requirements.

## 7. Explicitly Not Addressed Here

This roadmap is a summary, not a committed plan or timeline. It exists
to show awareness of the gap between a working prototype and a
production healthcare system — a core part of the FDE role this project
is designed to demonstrate.
