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

## 7. Universal Least-Privilege Escalation Boundary

This is a standing rule for all automation in this project — and, per
[ADR-008](decisions/ADR-008-least-privilege-escalation-and-missing-information.md),
a universal principle intended to apply to any project, not only Phase
1. It is also recorded in [CLAUDE.md](../CLAUDE.md) so future
Claude Code work follows it automatically. This is a separate,
additional boundary — it does not replace, narrow, or restate §5's AI
Decision-Making Boundary; both apply together.

Automation (deterministic rules, AI-assisted steps, integrations) may
use **only**:

1. Authenticated APIs it is already configured to call.
2. Explicitly approved FHIR-style/integration endpoints.
3. Explicitly approved data sources.
4. Permissions already granted to the current service account/user.

Automation must **never**, including in order to obtain missing
information:

- Exceed the current service-account/user's permissions.
- Bypass or circumvent access controls.
- Fall back to a prohibited or unapproved data source.
- Request, trigger, or imply a permission change for itself.
- Retrieve more PHI/PII or sensitive data than the task actually needs.
- Persist unnecessary PHI/PII.
- Log secrets, credentials, tokens, passwords, connection strings, raw
  LLM prompts, or raw LLM/provider responses (extends §2's logging
  rule into a boundary automation itself must never cross).

**If required information cannot be obtained within the current
authorized boundary, automation stops retrying and escalates to a
human** — it never broadens its own permissions and never tries an
unapproved source instead. This is the concrete rule behind Task 23's
two-stage missing-information handling: a case missing information is
first handled through the approved, already-authorized information-
request process; only if that leaves the case genuinely unresolved
does it escalate to `HUMAN_REVIEW_REQUIRED`
(`reason_code = HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION`).

The audit trail must make it possible to determine, for any escalation
or automated stop: what information was needed, which approved
source/component was actually used, what result occurred, why
automation stopped or continued, and what next workflow action was
selected — using only this project's existing structured audit fields
(`event_type_code`, `source_component_code`, `result_code`,
`reason_code`, small structured `metadata_json` counts,
`workflow_runs.next_action_code`). Audit records must never become a
place secrets or unnecessary PHI/PII end up — the same data-
minimization rule as everywhere else in this document.

## 8. Missing Information Safety Contract

**Status: APPROVED DESIGN REQUIREMENT (non-negotiable).** This section
is the operational security contract for handling missing/unknown
information, grounded in
[ADR-008](decisions/ADR-008-least-privilege-escalation-and-missing-information.md)
and [architecture.md §7](architecture.md#7-human-in-the-loop-missing-information-handling-and-escalation-boundary).
It is a separate, additional contract — it does not replace, narrow, or
restate §5 (AI Decision-Making Boundary) or §7 (Universal
Least-Privilege Escalation Boundary); all three apply together. These
are executable system boundaries that implemented code must obey, not
general recommendations or aspirational guidance.

### 8.1 Missing means missing

1. Missing data remains **MISSING/UNKNOWN** until verified evidence
   arrives from an approved source. Time passing, a retry occurring, or
   a case being reviewed does not by itself change that.
2. The system must **never fabricate or infer** missing facts and
   record them as if they were verified facts.

Concretely, missing/unknown information must **not** be converted into:

- Guessed values.
- Inferred clinical facts.
- AI-generated facts presented as verified.
- Fabricated documentation.
- Assumed diagnosis/procedure information.
- Default values that falsely imply the information is known.

A deterministic result may truthfully say `MISSING`, `UNKNOWN`,
`NOT_FOUND`, or `UNAVAILABLE`. The system must never replace one of
those honest states with fabricated certainty in order to let
processing continue.

### 8.2 AI boundary for missing information

This is additional to, and does not merge with, §5's AI
Decision-Making Boundary above.

AI may assist only with language-oriented tasks related to missing
information, such as:

- Explaining, in plain language, what information is missing.
- Summarizing information that has already been verified.
- Drafting the text of a clarification request.

AI must **not**:

- Invent the missing fact.
- Infer the missing fact and have that inference persisted as verified.
- Search arbitrary or unapproved sources for the answer.
- Use information from another patient/case to fill the gap.
- Transform uncertainty into a confirmed clinical fact.

### 8.3 Authorized retrieval boundary

`REQUEST_MISSING_INFORMATION` (and any missing-information
request/retrieval operation generally) means **only**: perform the
explicitly approved request/retrieval operation, using
already-authorized channels, approved/authenticated APIs/endpoints/data
sources, and the permissions already granted to the current
service-account/user (§7). It does **not** mean "search anywhere
necessary to obtain the information."

No permission elevation is ever an allowed way to resolve missing
information. No access-control bypass is ever an allowed way to
resolve it. No unapproved source is ever an allowed fallback.

Any approved missing-information request or retrieval operation must
use only the **minimum necessary** PHI/PII or other sensitive
information required for that specific purpose. The system must not
request, retrieve, persist, expose, or transmit broader sensitive data
merely because the current credentials technically permit access to
it.

If the approved process cannot resolve the missing information:

1. **STOP** automated retrieval attempts to resolve the missing
   information. Continue only with safe deterministic state handling,
   audit recording, and routing/escalation to Human Review.
2. **Preserve** the value as `MISSING`/`UNKNOWN` — never overwrite it
   with a guess.
3. **Route/escalate safely to Human Review**
   (`HUMAN_REVIEW_REQUIRED`, `reason_code =
   HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION` — see ADR-008).

### 8.4 Deny-by-default

**Not explicitly allowed = DENY.** An integration, source, endpoint,
retrieval mechanism, or data use must be explicitly approved before
automation may use it. The absence of an explicit prohibition is
**not** permission.

### 8.5 Audit contract

The audit trail must make it possible to reconstruct, for any
missing-information handling episode:

- What information was missing.
- What information was requested.
- Which approved source/component was used.
- The result/outcome.
- Whether the authorized boundary resolved it.
- Why automation stopped or continued.
- Why Human Review was requested, when it was.
- The next workflow action.
- The `trace_id` the episode occurred under.

This does not require storing raw sensitive content — safe, structured
facts are sufficient and preferred. Consistent with §2 and §7, the
audit trail must **never** contain: passwords, API keys, tokens,
connection strings, secrets of any kind, raw LLM provider responses,
unnecessary raw prompts, unnecessary PHI/PII, or unnecessary
clinical-note content.

### 8.6 Human Review does not expand access

Human Review is a **decision/safety escalation boundary**, not an
access-expansion mechanism. Routing a case to Human Review does
**not** automatically grant the automation:

- Additional permissions.
- Broader service-account access.
- New data sources.
- Bypass authority.
- Permission to retrieve otherwise-prohibited information.

The Universal Least-Privilege Escalation Boundary (§7) remains in force
before, during, and after Human Review — a human's involvement never
widens what the automation itself is allowed to access.

### 8.7 Implementation status

This contract is the **approved design requirement** as of this
writing. Individual elements' implementation status (Tasks 23/24
complete; last updated after Task 24B-4G):

- Stage 1 (deterministic missing-information detection,
  `next_action_code = REQUEST_MISSING_INFORMATION`, no `human_reviews`
  row): **IMPLEMENTED** (Step 23C-5C) — `src/workflow/nodes.py`'s
  `request_missing_information_node()` and `src/workflow/graph.py`'s
  `route_after_completeness()` route a deterministically incomplete
  case to this disposition, never to Human Review. The external
  request/response transport that would notify a requester remains
  **PLANNED**, not built.
- Stage 2 (unresolved-information escalation to
  `HUMAN_REVIEW_REQUIRED` with the dedicated reason code): **NOT
  IMPLEMENTED** — the reason code and routing change are confirmed not
  yet implemented in `src/workflow/graph.py`.
- Human-review request and decision persistence
  (`src/db/human_review_repository.py`, `src/db/repository.py`,
  `src/db/case_repository.py`, `src/workflow/human_review_service.py`):
  **IMPLEMENTED AND VALIDATED** — all four approved outcomes, the
  shared caller-owned transaction, and duplicate/cancelled/idempotent-
  replay conflict handling are validated both offline and directly
  against the real local SQL Server database. `request_human_review()`/
  `resume_after_human_review()` **are** called from
  `src/workflow/orchestrator.py` (Task 23C-6A): a genuine
  `HUMAN_REVIEW_REQUIRED` disposition (FHIR failure, evidence mismatch,
  or AI failure) creates a real `human_reviews` row atomically with the
  same run's `workflow_runs`/`audit_events` writes.
- **Same-run/same-trace post-review workflow continuation: IMPLEMENTED
  AND VALIDATED (Task 24)**, both offline and against the real local
  SQL Server database
  (`tests/test_workflow_resume_sql_server_integration.py`). A
  `CONTINUE_WORKFLOW` decision moves the existing `workflow_runs` row
  to `PENDING_RESUME`/`CONTINUE_PROCESSING`; `resume_workflow()`
  (`src/workflow/resume_service.py`, exposed as
  `POST /workflows/{trace_id}/resume`) then validates eligibility and
  persisted case identity, atomically claims the SAME run, and
  re-invokes the SAME compiled LangGraph graph on the SAME `trace_id`
  with fresh caller-supplied input — this is application-level
  re-invocation, never LangGraph checkpoint restoration (no
  checkpointer exists anywhere in this project). `WORKFLOW_RESUMED` is
  recorded, with a deterministic `event_id` derived from the
  authorizing `review_id`, only when this automated continuation
  actually begins; `WORKFLOW_STARTED` is never re-emitted; a duplicate
  resume attempt is rejected safely and changes nothing.
  `CONTINUE_WORKFLOW`/successful resume never means a clinical
  approval/denial decision — only that automation may continue
  processing.
- The underlying `human_reviews`/`human_review_statuses`/
  `human_review_outcomes` schema: migration `f2fb22e3a41e` **has been
  applied** to the real local SQL Server database (Step 23B-6), and the
  associated reference data — including the six `CASE_CLOSE_*` reason
  rows and, as of Task 24B-4D, `event_types.WORKFLOW_RESUMED` — is
  loaded: 97 rows across 14 tables (see
  [database/reference_data.md](database/reference_data.md)).

No element of this contract should be read as already fully
implemented merely because it is now an approved requirement.
