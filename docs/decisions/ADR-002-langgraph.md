<!--
File Name: ADR-002-langgraph.md
Purpose: Records the decision to use LangGraph for explicit stateful workflow orchestration.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# ADR-002: LangGraph for Workflow Orchestration

## Status
Accepted

## Context
The prior authorization workflow has multiple distinct stages
(validation, deterministic rules, optional LLM step, human review,
persistence) with conditional branching between them (e.g., missing
information, low-confidence AI output, mandatory human review). This
needs to be modeled as an explicit state machine rather than ad-hoc
imperative code, so that:

- Every state and transition is visible and testable.
- The workflow can pause and resume (e.g., while waiting on human
  review) without losing state.
- The routing logic is auditable and does not hide decisions inside
  nested conditionals.

## Decision
Use **LangGraph** as the workflow/state-machine layer for orchestrating
the prior authorization process. LangGraph will define:

- Explicit nodes for each processing stage (validation, business rules,
  LLM step, human review, persistence).
- Explicit conditional edges for routing decisions (e.g., "missing
  information?", "AI needed?", "valid and safe?", "human review
  required?").
- Workflow state that can be checkpointed while waiting on external
  input (human review).

This decision has been reviewed and is fixed for Phase 1. LangGraph
will not be swapped for another state-machine or workflow library
during this phase.

## Consequences
- Adds a dependency and a learning curve, but produces an explicit,
  inspectable graph of the workflow — valuable both for correctness and
  for demonstrating architecture clearly in a portfolio context.
- Human-in-the-loop review can be modeled as a first-class pause/resume
  point in the graph rather than a bolted-on side process.

## Related
- [[../architecture.md]]
- [[ADR-001-deterministic-first.md]]
