<!--
File Name: security.md
Purpose: Documents Phase 1 security, privacy, secret management, synthetic-data, logging, and configuration rules.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# Security & Privacy — Phase 1

## 1. Data Policy

- This project uses **only synthetic healthcare data**.
- No real PHI (Protected Health Information), PII, patient records, or
  healthcare identifiers belonging to real people will be used at any
  point, in any environment, for any reason.
- Synthetic data should still be treated with the same handling
  discipline as real data (no leaking sample "case" data into
  unrelated public contexts) as a matter of good practice, even though
  it carries no real-world privacy risk.

## 2. Secrets Management

**Never hard-code:**

- API keys
- Passwords
- Access tokens
- Secrets of any kind
- Database credentials
- Connection strings
- Private/internal identifiers
- Sensitive configuration values

**Instead, use:**

- Environment variables, loaded from a local `.env` file that is
  excluded from Git via `.gitignore`.
- `.env.example` for documenting *which* variables are needed, with
  placeholder (empty) values only — never real-looking secrets.
- Application configuration files (e.g., `config/settings.yaml`, itself
  git-ignored once created) for non-secret, business-sensitive
  configuration values.

**Never commit real secrets.** If a secret is ever accidentally
committed, it must be treated as compromised: rotate/revoke it and
scrub it from history, not just delete it in a new commit.

## 3. Configuration vs. Hard-Coding

Ordinary technical constants (e.g., HTTP status codes, retry backoff
shape, array sizes) may reasonably live in code.

Configurable or business-sensitive values must be externalized to
configuration rather than hard-coded, including:

- Risk thresholds
- Confidence thresholds (e.g., minimum LLM confidence before
  auto-continuing vs. routing to human review)
- Business thresholds
- Workflow limits (e.g., retry limits, timeouts)

See [config/settings.example.yaml](../config/settings.example.yaml) for
the placeholder structure.

## 4. Application-Level Security Considerations (for implementation phases)

These are principles to apply once code is written — not yet
implemented in Phase 1's skeleton:

- **SQL Server access**: use parameterized queries / an ORM's
  parameter binding — never string-concatenated SQL — to prevent SQL
  injection.
- **API input validation**: all inbound API payloads are validated via
  Pydantic schemas before use (also a correctness requirement, see
  [architecture.md](architecture.md)).
- **LLM output validation**: structured LLM output is validated before
  it can influence workflow state; invalid or unsafe output routes to
  human review rather than being trusted.
- **Least privilege**: any credentials used (DB, Azure OpenAI) should
  be scoped to only what the prototype needs.
- **Dependency hygiene**: keep dependencies current and avoid adding
  packages that aren't clearly justified by a requirement.
- **Data minimization in persistence**: raw FHIR-style payloads and raw
  LLM prompts/provider responses are not persisted; only validated,
  structured data is stored. See the FHIR and AI persistence boundary
  sections of [database/data_model.md](database/data_model.md) for the
  full Phase 1 database design baseline.

## 5. AI Decision-Making Boundary

The AI must **not** independently make clinical approval or denial
decisions. This is a hard boundary, not a tunable setting:

- The LLM may summarize, classify, or extract information from
  unstructured text.
- The LLM's output is always validated and treated as a
  recommendation/input, never as the workflow's final decision.
- Final outcomes are determined by deterministic business rules and/or
  human review, per [ADR-001](decisions/ADR-001-deterministic-first.md).

## 6. Prototype Security Scope

This is a portfolio prototype, not a production healthcare system. Full
production-grade security controls (see
[production_roadmap.md](production_roadmap.md)) — such as
authentication/authorization, encryption key management, network
isolation, formal access controls, and compliance controls (e.g.,
HIPAA safeguards for real PHI) — are intentionally out of scope for
Phase 1 and are documented as planned future work rather than
implemented now.
