<!--
File Name: ADR-001-deterministic-first.md
Purpose: Records the decision to use deterministic validation and rules before LLM reasoning.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# ADR-001: Deterministic-First Architecture

## Status
Accepted

## Context
This project prototypes AI-assisted support for a healthcare Prior
Authorization workflow. Prior authorization decisions can affect patient
care and involve business- and compliance-sensitive rules. An LLM used
carelessly could introduce unpredictable, unexplainable, or unsafe
behavior into a process that historically relies on explicit, auditable
rules.

## Decision
The system will be **deterministic-first**:

- All inputs are validated with explicit schemas (Pydantic) before any
  further processing.
- Explicit Python business rules run before any LLM reasoning is
  invoked.
- LLMs are used only for tasks that are genuinely probabilistic or
  language-based in nature — e.g., summarizing unstructured clinical
  notes, interpreting ambiguous free text, or classifying intent — never
  for the final clinical approval/denial decision.
- The AI does not independently approve or deny a prior authorization
  request. Any AI output that would affect an outcome is treated as a
  recommendation subject to deterministic checks and, where required,
  human review.

## Consequences
- Slightly more upfront engineering effort (explicit rules and
  validation layers) compared to routing everything through an LLM.
- Behavior is easier to explain, test, and audit — a requirement for
  any healthcare workflow support use case.
- LLM failures or low-confidence outputs degrade gracefully into human
  review rather than silently producing an incorrect determination.

## Related
- [[../architecture.md]]
- ADR-002 (LangGraph) implements the explicit state routing this
  decision requires.
