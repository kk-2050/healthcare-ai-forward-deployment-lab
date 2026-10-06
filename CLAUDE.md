<!--
File Name: CLAUDE.md
Purpose: Project-level instructions and engineering guardrails for Claude Code.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Healthcare AI Forward Deployment Lab — a portfolio project demonstrating
skills aligned with a healthcare Data Forward Deployment Engineer (FDE)
role, using a Prior Authorization workflow support use case. See
[README.md](README.md) for full context, current status, and the
high-level architecture diagram.

**This is not a production healthcare system.** Only synthetic
healthcare data is used, and the AI does not independently make
clinical approval/denial decisions.

## Fixed Technology Decisions — do not change without explicit user approval

These have already been reviewed and decided (see
[docs/decisions/](docs/decisions/)):

- **LangGraph** for workflow orchestration — do not substitute another
  state-machine library.
- **Microsoft SQL Server** (local) for persistence — do not substitute
  PostgreSQL or another database engine.
- **Azure OpenAI / Azure AI Foundry** for LLM calls — do not substitute
  the plain OpenAI API or another provider.
- Backend: **FastAPI + Pydantic**. Frontend: **Streamlit**. Testing:
  **pytest**.
- **Alembic + SQLAlchemy** for physical SQL Server schema migration and
  versioning (see [ADR-005](docs/decisions/ADR-005-database-schema-migration-strategy.md))
  — the migration framework is installed, initialized, and in active
  use: `alembic.ini` and `migrations/` (`env.py`, `script.py.mako`,
  `versions/`) exist and are wired to the project's existing
  SQLAlchemy metadata and secure database configuration. **Revision
  `c841e86a8516` (Wave 1 database foundation), revision
  `b9aba5b07ac8` (Wave 2 canonical case/workflow schema, including the
  controlled rebuild of `workflow_runs`/`audit_events` into their
  canonical shape), and revision `f2fb22e3a41e` (Human-in-the-Loop
  persistence tables — `human_review_statuses`, `human_review_outcomes`,
  `human_reviews`) have all been successfully applied to the real
  local SQL Server database (`healthcare_ai_fde_lab`) and validated
  (Tasks 20B, 21B, 23B).** Do not substitute a different migration
  mechanism without explicit approval, and do not create a migration
  revision (`alembic revision`), run `alembic upgrade`/`downgrade`/
  `stamp`, or modify the schema outside an explicitly approved,
  reviewed Alembic revision task.

## Architecture Principles (apply to all implementation work)

1. Deterministic-first: explicit code and rules before LLM reasoning.
2. Validate all inputs (Pydantic) before anything reaches the AI step.
3. Explicit Python business rules run before LLM reasoning.
4. LLMs are used only for ambiguity/language/summarization-type tasks —
   never to make the final approval/denial decision.
5. Missing information must never be guessed or fabricated. Initial
   missing information is handled deterministically through
   `REQUEST_MISSING_INFORMATION` using only approved, authenticated,
   already-authorized sources and permissions. If the authorized
   process cannot resolve it, preserve the value as `MISSING`/`UNKNOWN`,
   stop further retrieval attempts, and route to Human Review.
   Low-confidence AI output and rule-flagged cases continue to route to
   Human Review as defined by the workflow.
6. Keep deterministic facts/rules, AI inference, and human decisions
   clearly separated in the data model — never blended.
7. Workflow states and routing must be explicit (LangGraph graph is the
   source of truth), not buried in nested conditionals.
8. Every workflow transition and decision must be traceable/auditable.
9. Fail safely on LLM or healthcare API failure — route to human review
   or a clear error state, never a silent guess.
10. Workflow state must be preserved while waiting on human review.
11. Prefer the simpler, more explainable design when there's a choice.
12. Don't add technology or abstraction because it's popular or
    "nice to have" — only when a stated requirement needs it.

Full detail: [docs/architecture.md](docs/architecture.md).

## Security Rules

- Never hard-code API keys, passwords, tokens, secrets, DB credentials,
  connection strings, or other sensitive configuration. Use environment
  variables (`.env`, git-ignored) or config files — see
  [.env.example](.env.example) and
  [config/settings.example.yaml](config/settings.example.yaml).
- Never commit real secrets, even temporarily.
- Never use real PHI/PII or real patient/healthcare identifiers —
  synthetic data only.
- Externalize business-sensitive values (thresholds, retry limits,
  workflow limits) to configuration rather than hard-coding them.
  Ordinary technical constants are fine in code.
- Full detail: [docs/security.md](docs/security.md).

### Universal Least-Privilege Escalation Boundary — NON-NEGOTIABLE

This applies to this project and is a standing rule for all future
work, in any project, not only Phase 1. See
[ADR-008](docs/decisions/ADR-008-least-privilege-escalation-and-missing-information.md)
for the full decision record.

Automation (deterministic rules, AI-assisted steps, integrations) may
use ONLY: authenticated APIs it is already configured to call,
explicitly approved FHIR-style/integration endpoints, explicitly
approved data sources, and permissions already granted to the current
service account/user.

Automation must NEVER, including to obtain missing information:
- Exceed the current service-account/user's permissions.
- Bypass or circumvent access controls.
- Fall back to a prohibited or unapproved data source.
- Request, trigger, or imply a permission change for itself.
- Retrieve more PHI/PII or sensitive data than the task actually needs,
  or persist unnecessary PHI/PII.
- Log secrets, credentials, tokens, passwords, connection strings, raw
  LLM prompts, or raw LLM/provider responses.

If required information cannot be obtained within the current
authorized boundary: STOP automated retrieval. Do not broaden
permissions. Do not try another unapproved source. Escalate safely
(route to human review, per the approved workflow) instead. The audit
trail must make it possible to determine what was needed, which
approved source/component was used, what result occurred, why
automation stopped or continued, and what next action was selected —
using only the structured audit fields already defined in this
project's schema, never free-text secrets or unnecessary PHI/PII.

### Missing Information Safety Contract — NON-NEGOTIABLE

See [docs/security.md §8](docs/security.md#8-missing-information-safety-contract)
for the full contract; this is the condensed, binding summary.

Missing/unknown information stays `MISSING`/`UNKNOWN` until verified
evidence arrives from an approved source. It must NEVER be fabricated,
guessed, or inferred and then treated/persisted as a verified fact —
including by AI. AI may explain what is missing, summarize verified
information, or draft a clarification request; AI may NEVER invent a
missing fact, infer one and have it persisted as verified, or use
another case's data to fill the gap.

`REQUEST_MISSING_INFORMATION` means only the explicitly approved
request/retrieval operation through already-authorized channels — it
does NOT mean "search anywhere necessary." **Not explicitly allowed =
DENY**: an integration, source, endpoint, retrieval mechanism, or data
use must be explicitly approved before use; absence of a prohibition is
not permission.

Only the minimum necessary PHI/PII or other sensitive information may
be requested, retrieved, persisted, exposed, or transmitted for that
specific purpose.

If the authorized process cannot resolve missing information: STOP
further automated retrieval attempts — but still continue safe
deterministic state handling, audit recording, and routing/escalation
to Human Review. Human Review is a decision/safety boundary only — it
never expands the automation's own permissions, sources, or access,
before, during, or after review.

## Working Conventions

- Do not describe planned/not-yet-implemented backend behavior as if it
  were implemented — keep README/status claims honest and current.
- Prefer small, explainable changes over broad refactors; this project
  values clarity and auditability over cleverness.
- When adding a new architectural or technology decision, record it as
  a new ADR in [docs/decisions/](docs/decisions/) rather than only
  mentioning it in code or chat.
- Current implementation status is tracked in [README.md](README.md) —
  keep the "Current Status" section accurate as work progresses.
- The LangGraph ↔ SQL persistence orchestration boundary
  (`src/workflow/orchestrator.py`) and the stable node → `step_code`
  mapping (`src/workflow/step_mapping.py`) are **IMPLEMENTED AND
  VALIDATED** (Task 22). Six HTTP endpoints exist in `src/api/app.py`:
  `POST /cases/validate` (deterministic validation only, never
  persists), `POST /workflows` (Task 25B — starts a brand-new
  orchestration run for a fresh/safely-retried case via
  `src/workflow/case_intake_service.py`), `POST /human-review/decisions`
  (Task 23C-7A), `POST /workflows/{trace_id}/resume` (Task 24B-4C —
  same-run/same-trace continuation for an existing run), and two
  read-only lookups (Task 26B) — `GET /workflows/{trace_id}` and
  `GET /human-review/pending/{trace_id}` — that reuse existing
  repository read methods unchanged and never mutate state. The stable
  reference/configuration loader (`src/db/reference_data.py`) is
  implemented, idempotent, and has been run against the real local SQL
  Server database: **97 rows across 14 tables**, including the
  `human_review_statuses`/`human_review_outcomes` domains, the six
  `CASE_CLOSE_*` reason rows (Task 23C), `event_types.
  WORKFLOW_RESUMED` (Task 24B-4D — `event_types` is now 16 rows;
  idempotency re-validated on a second load: `inserted=0`,
  `already_present=97`), and the complete 9-row `workflow_definition_steps`
  catalog (including `REQUEST_MISSING_INFORMATION`, Step 23C-5C). It is
  separate from Alembic and from synthetic business/test fixtures —
  never add a client/case/business row to it, and never silently
  overwrite a conflicting existing row; a real semantic conflict must
  fail loudly. The opt-in real SQL
  Server integration tests (`tests/test_workflow_orchestrator_integration.py`,
  `tests/test_human_review_sql_server_integration.py`,
  `tests/test_workflow_resume_sql_server_integration.py`) are skipped
  by ordinary `pytest`; only run one with
  `RUN_SQL_SERVER_INTEGRATION_TESTS=1` explicitly set, and only after
  the same review-then-approve discipline used for every other
  live-database action in this project. Task 25B has not yet had its
  own opt-in real SQL Server integration test written.
- **Task 23 (human-in-the-loop persistence): IMPLEMENTED AND
  VALIDATED.** Human-review request/decision persistence
  (`src/db/human_review_repository.py`, `src/db/repository.py`,
  `src/db/case_repository.py`, `src/workflow/human_review_service.py`)
  is wired into `src/workflow/orchestrator.py`: a genuine
  `HUMAN_REVIEW_REQUIRED` disposition (FHIR failure, evidence mismatch,
  or AI failure) creates a real `human_reviews` row atomically with the
  `workflow_runs`/`audit_events` writes for that run. All four approved
  outcomes, the shared atomic transaction, and duplicate/cancelled/
  idempotent-replay handling are validated both offline and directly
  against the real local SQL Server database. **NOT IMPLEMENTED:**
  Stage 2 unresolved-missing-information escalation in
  `src/workflow/graph.py` (Stage 1's deterministic
  `REQUEST_MISSING_INFORMATION` routing is implemented).
- **Task 24 (same-run/same-trace resume continuation): IMPLEMENTED AND
  VALIDATED**, both offline and against real SQL Server
  (`tests/test_workflow_resume_sql_server_integration.py`). A
  `CONTINUE_WORKFLOW` Human Review decision (`resume_after_human_review()`)
  moves the existing `workflow_runs` row to `PENDING_RESUME`/
  `CONTINUE_PROCESSING` (`completed_at_utc` stays NULL) — by itself this
  is only an application-level state transition, not automated
  continuation. Automated continuation is
  `src/workflow/resume_service.py`'s `resume_workflow()` (the sole
  public entry point, exposed as `POST /workflows/{trace_id}/resume`):
  it validates resume eligibility and the persisted case identity,
  atomically claims the run via a race-safe conditional `UPDATE` (never
  read-then-write), then re-invokes the SAME compiled LangGraph graph
  on the SAME `trace_id` with fresh, caller-supplied input. There is no
  LangGraph checkpointer anywhere in this project — this is
  application-level re-invocation, never LangGraph checkpoint
  restoration; do not describe it otherwise. `WORKFLOW_RESUMED` is
  recorded only when that automated continuation actually begins, with
  an `event_id` deterministically derived from the authorizing
  `review_id`; `WORKFLOW_STARTED` is never re-emitted on resume. A
  duplicate resume attempt is rejected safely and changes nothing.
  `CONTINUE_WORKFLOW` means automation may continue processing — it is
  never a clinical approval/denial decision.
- **Task 25B (fresh-case workflow intake): IMPLEMENTED AND VALIDATED —
  offline** (`src/workflow/case_intake_service.py`, exposed as
  `POST /workflows`). Validates `client_id` against an existing,
  active, non-deleted `clients` row (no client auto-creation); resolves
  fresh/duplicate/safe-retry case state via a six-field durable
  identity (including `client_id`, deliberately separate from Task
  24's five-field resume identity); claims a case for processing via a
  race-safe conditional `UPDATE` (reusing the existing, previously-
  unused `case_statuses.IN_PROGRESS` value — no migration, no new
  reference-data row); reverts that claim only when no `workflow_runs`
  row was ever created. **Task 25B-1/25B-2 case-status lifecycle
  correction:** `case_status_code` now resolves to `OPEN` after
  ordinary automated completion or a persisted technical `FAILED` run,
  and to `HUMAN_REVIEW_REQUIRED` while a run is genuinely paused for a
  reviewer — for both a direct run and a same-run/same-trace resumed
  run; `CLOSED` remains set only by a genuine Human Review `CLOSE_CASE`
  decision. `case_repository` stays optional on the orchestrator's
  public signature for backward compatibility; the real production
  callers (fresh intake, resume) always supply it. Ordinary pytest:
  525 passed, 4 skipped, 0 failed, at Task 25B's own closure (see the
  Task 25C bullet below for the current total). **Not yet proven
  against real SQL Server** (unlike Tasks 23/24, which are both
  offline- and real-SQL-validated) — see the opt-in integration tests
  above. The Streamlit UI remains not implemented.
- **Task 25C (synthetic FHIR runtime mode): IMPLEMENTED AND VALIDATED —
  offline.** `FHIR_MODE` (`src/config/fhir_settings.py`) controls what,
  if anything, `get_fhir_client()` (`src/api/dependencies.py`) builds:
  `disabled` is the default for unset or blank `FHIR_MODE` and fails
  closed exactly as before Task 25C. An unrecognized `FHIR_MODE` value
  is rejected by configuration validation and is converted by
  `get_fhir_client()` to the same fail-closed
  `FHIRIntegrationNotConfiguredError` path — never normalized to
  `disabled`, and never treated as `synthetic` or `live`. `synthetic`
  (explicit opt-in)
  returns a local, zero-network `FHIRStyleClient`
  (`src/integrations/synthetic_fhir_runtime.py`, backed only by
  `httpx.MockTransport` — no socket/DNS/TLS access is possible) that
  returns one fixed, deterministic evidence Bundle
  (`SYN-LUMBAR-MRI`/`SYN-LOW-BACK-PAIN`) for every case_id; `live`
  remains explicitly **NOT IMPLEMENTED** and also fails closed — the
  word is recognized but never builds a live/unauthenticated client.
  `FHIRStyleClient` itself (`src/integrations/fhir_client.py`) is
  unchanged. This is the one canonical dependency path — no route
  builds a second FHIR client, and both `POST /workflows` and `POST
  /workflows/{trace_id}/resume` already use it, so both now run
  end-to-end locally under `FHIR_MODE=synthetic` through their real,
  un-overridden dependency, not a test-only substitute. Phase 1 local
  prototype/demo infrastructure only — never a production integration,
  and it supplies evidence only, never a clinical approval/denial
  decision. An approved, authenticated **live** production FHIR
  integration remains **NOT IMPLEMENTED**. Every automated test
  controls `FHIR_MODE` explicitly (never relies on a developer's local
  `.env`); the two existing fail-closed API tests were updated to do
  the same. Ordinary pytest: **552 passed, 4 skipped, 0 failed.** No
  real SQL was run, no live FHIR was called, and no live AI was called
  for Task 25C. The Streamlit UI remains **NOT IMPLEMENTED**.
- **Task 26B (Streamlit backend prework): IMPLEMENTED AND VALIDATED —
  offline.** Two read-only endpoints close the gaps found during
  Task 26A's UI design review: `GET /workflows/{trace_id}` (reuses
  `AuditRepository.get_workflow_run()`/`list_audit_events()` unchanged)
  and `GET /human-review/pending/{trace_id}` (reuses
  `HumanReviewRepository.get_pending_review_by_trace_id()` unchanged —
  that method already excludes `COMPLETED`/`CANCELLED` reviews). Both
  are strictly read-only: no write, no new audit event, no FHIR/AI/
  LangGraph call; unknown trace_id → fixed 404; a persistence failure →
  fixed 500. `src/api/dependencies.py` was not changed — both routes
  depend on existing dependency functions only. A new, explicit,
  manually-run setup script (`scripts/setup_demo_client.py`) creates
  the one canonical synthetic demo client
  (`client_id=cli_demo_001`/`client_code=DEMO_HEALTH`/`client_name=
  "Demo Health Plan"` — reusing the example `docs/database/
  reference_data.md` §2 already documented but never loaded) —
  idempotent (`ALREADY_PRESENT` only on an exact canonical-field match)
  and conflict-safe (a differing existing row, or a `client_code`
  collision under a different `client_id`, is reported as a `CONFLICT`
  and never written to or overwritten); never run automatically by
  FastAPI, Streamlit, or `src/db/reference_data.py`. Ordinary pytest:
  **576 passed, 4 skipped, 0 failed**, at Task 26B's own closure (see
  the Task 26C-1 bullet below for the current total). No real SQL was
  run, no live FHIR was called, no live AI was called.
- **Task 26C-1 (Streamlit MVP foundation): IMPLEMENTED AND VALIDATED —
  offline.** `streamlit_app.py` is a thin HTTP/JSON client over
  FastAPI only — it never imports LangGraph, a workflow service, a
  repository, a SQLAlchemy session, `FHIRStyleClient`, the synthetic
  FHIR runtime, or the AI provider; every action goes through
  `src/ui/api_client.py` (`httpx`), the one place that boundary is
  crossed. Three navigation areas exist: Client Requirement Intake
  (explicitly **MOCKED / UI-ONLY** — `st.session_state` only, never
  persisted, never sent to any backend, no invented endpoint), Healthcare
  Case Processing (submits `src/ui/demo_data.py`'s canonical synthetic
  demo case — `client_id=cli_demo_001` matching Task 26B's demo client,
  `requested_service_code=SYN-LUMBAR-MRI`/`diagnosis_code=
  SYN-LOW-BACK-PAIN` matching Task 25C's synthetic FHIR evidence — to
  the real `POST /workflows`), and Audit & Technical View (renders only
  the latest response snapshot already in session state — explicitly
  not a durable lookup). `src/ui/view_helpers.py` renders only an
  explicit field allowlist — never `final_state`, a raw FHIR/LLM field,
  or any other unlisted key, even if the backend response happened to
  contain one. `src/ui/api_client.py` maps every non-2xx response,
  connection failure, and timeout to one fixed, safe message determined
  **locally from the HTTP status code alone** (Task 26C-1B correction)
  — the backend's own response body/`detail` text is never read or
  displayed, so this boundary stays safe even if a future backend
  implementation puts something unsafe there; never a raw exception,
  response text, traceback, secret, connection string, or backend
  internal. No backend file changed; `requirements.txt` was not
  touched (`streamlit`/`httpx` were already pinned dependencies).
  Ordinary pytest: **612 passed, 4 skipped, 0 failed**, at Task 26C-1's
  own closure (see the Task 26C-2 bullet below for the current total).
- **Task 26C-2 (Streamlit Human Review, Resume, durable refresh):
  IMPLEMENTED AND VALIDATED — offline.** `src/ui/api_client.py` gained
  four thin methods sharing the exact same hardened error mapping as
  `start_workflow()` — `get_workflow()`/`get_pending_human_review()`
  (`GET`, read-only, never mutate) and
  `submit_human_review_decision()`/`resume_workflow()` (`POST`); all
  five methods now route through one shared `_request()` helper.
  Inside Healthcare Case Processing: when the last known
  `workflow_status_code` is `HUMAN_REVIEW_REQUIRED`
  (`src/ui/view_helpers.py`'s `is_human_review_pending_eligible()`), an
  explicit "Load Pending Human Review" action discovers `review_id` via
  `GET /human-review/pending/{trace_id}` — the operator never types a
  review_id manually. The decision form offers only
  `ALLOWED_HUMAN_REVIEW_OUTCOMES` — confirmed by test to equal
  `HumanReviewOutcome`'s four real values exactly
  (`CONTINUE_WORKFLOW`/`REQUEST_MORE_INFORMATION`/`ESCALATE`/
  `CLOSE_CASE`) — with no approve/deny control, a fixed
  `reviewer_actor_type_code=HUMAN_REVIEWER` (the real, already-loaded
  `actor_types` row), and, only for `CLOSE_CASE`,
  `CLOSE_CASE_REASON_CODES` — confirmed by test to equal
  `human_review_service.py`'s own `_APPROVED_CLOSE_REASON_CODES`
  exactly, with `close_reason_text` required only for
  `CASE_CLOSE_OTHER` (`requires_close_reason_text()`). When the
  resulting state is `PENDING_RESUME`
  (`is_resume_eligible()`), a Resume action rebuilds the request from
  the existing `current_case_request`'s `case`/
  `completeness_requirements`/`ai_processing_requirements` (no
  `client_id` — confirmed `ResumeWorkflowRequest` has none) and calls
  `POST /workflows/{trace_id}/resume`; `is_same_trace()` refuses to
  apply a response whose `trace_id` does not match the run being
  continued. `normalize_to_workflow_response_shape()` lets
  `extract_workflow_summary()`/`extract_audit_event_rows()` work
  uniformly across all four response shapes (Start/Resume/Snapshot/
  HumanReviewDecision). Audit & Technical View gained an explicit
  "Refresh Workflow State" action calling
  `GET /workflows/{trace_id}` — a durable backend re-fetch, never
  triggered automatically on rerender. No backend file changed.
  Ordinary pytest: **650 passed, 4 skipped, 0 failed.** No real SQL was
  run, no live FHIR was called, no live AI was called. The Streamlit UI
  has not yet been run as a live session against a real FastAPI/SQL
  Server backend.
- Alembic is initialized and in active use (see Fixed Technology
  Decisions and
  [ADR-005](docs/decisions/ADR-005-database-schema-migration-strategy.md)):
  always review a migration revision (including autogenerated
  revisions) before it is executed — never trust autogenerate output
  blindly; never modify the SQL Server schema manually outside an
  approved, version-controlled migration; report migration and test
  results honestly; never claim a migration succeeded unless it was
  actually run and verified. Future schema changes must continue
  through reviewed Alembic revisions, the same way revisions
  `c841e86a8516` and `b9aba5b07ac8` were. SQLite is not a valid dry-run
  target for these revisions (they deliberately use SQL Server-specific
  types such as `mssql.DATETIME2`, which SQLite cannot compile) — never
  alter a migration to make it SQLite-compatible, and never treat
  SQLite execution as a pass/fail gate for them.

## File Metadata Requirement

Every new project file created in future tasks must include a
top-of-file metadata header containing:

- File Name
- Purpose
- Creation Date
- Author

**Formatting rules:**

- **Markdown (`*.md`):** Use a hidden HTML comment block at the very
  top.

  Example:

  ```
  <!--
  File Name: example.md
  Purpose: Short description of the file responsibility.
  Creation Date: YYYY-MM-DD
  Author: K.Kashiwagi
  -->
  ```

- **YAML / YML / .env / .gitignore / similar text configuration
  files:** Use `#` comment syntax.

- **Python files:** Use `#` comment syntax at the top.

- **SQL files:** Use `--` comment syntax at the top.

- **Other source/configuration files:** Use the normal comment syntax
  for that file type.

**Author:**
- Use "K.Kashiwagi" unless explicitly instructed otherwise.

**Creation Date:**
- Use the actual date the file is first created.
- Do not overwrite the original Creation Date when a file is later
  modified.

**Purpose:**
- Must be concise and accurately describe the file's responsibility.

**Important:**
- Metadata must not contain secrets, credentials, PHI/PII, private IDs,
  or sensitive configuration.
- Do not add metadata in a way that breaks the file syntax.
- For formats where comments are not supported, ask before creating
  the file.

## Code Documentation Standard

All program code (not just Python — apply the same spirit to any future
language in this repo) must be written so another engineer can maintain
it without relying on the original developer. This applies to new code
and to existing code being substantially modified.

- Use Professional Simple English. Prefer "Checks whether required
  documents are present" over "Performs deterministic adjudication of
  required-document presence."
- Explain **what** the code does and **why** important logic exists —
  not just how. Obvious syntax does not need a comment.
- Document inputs and outputs when it helps a reader (what a function
  receives, what it returns, what state it changes) — not for every
  trivial line.
- Explain important assumptions, restrictions, and maintenance
  cautions where a maintainer could otherwise misunderstand or
  accidentally break something.
- Make the deterministic-vs-AI-vs-human responsibility boundary
  explicit wherever relevant: what is a deterministic fact, what is
  AI-generated inference (never treated as verified truth), and what
  requires a human decision.
- Document security-sensitive boundaries (e.g., what a component must
  never receive or expose — secrets, credentials, raw provider
  internals, PHI/PII).
- Use a visually separated section-comment block (uppercase section
  name, Purpose/Why/Important Notes as applicable) for meaningful
  logical sections — not for every few lines.
- Give important classes and functions a concise docstring: what it
  represents/does, why it exists, and any real safety or maintenance
  boundary. Keep it short, not an essay.
- Every test should have a short docstring or comment explaining what
  behavior or requirement it protects — not a restatement of its name.
- Avoid over-commenting obvious syntax (e.g., "# Return result" above
  a `return` statement adds no value).
- Never describe planned, mocked, or not-yet-implemented behavior as if
  it were already implemented. Keep the IMPLEMENTED / PLANNED / MOCKED
  distinction honest in comments, the same way it must stay honest in
  [README.md](README.md).
