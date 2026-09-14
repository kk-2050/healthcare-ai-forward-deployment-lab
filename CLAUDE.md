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

## Architecture Principles (apply to all implementation work)

1. Deterministic-first: explicit code and rules before LLM reasoning.
2. Validate all inputs (Pydantic) before anything reaches the AI step.
3. Explicit Python business rules run before LLM reasoning.
4. LLMs are used only for ambiguity/language/summarization-type tasks —
   never to make the final approval/denial decision.
5. Missing information, low-confidence AI output, or rule-flagged cases
   go to human review, not a guessed outcome.
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
