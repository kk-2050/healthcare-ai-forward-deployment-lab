<!--
File Name: ADR-008-least-privilege-escalation-and-missing-information.md
Purpose: Records the universal least-privilege/no-permission-elevation security boundary and the two-stage missing-information handling model it grounds
Creation Date: 2026-09-21
Author: K.Kashiwagi
-->

# ADR-008: Least-Privilege Escalation Boundary and Two-Stage Missing-Information Handling

## Status
Accepted

## Context
Task 23 (Human-in-the-Loop persistence + pause/resume) needs
`human_reviews.reason_code` (NOT NULL) to always have a real, approved
value. Investigating the one path with no matching code — a case
routed to `HUMAN_REVIEW_REQUIRED` because required information/
documentation is missing — surfaced a genuine, pre-existing conflict
between two already-approved documents:

- [requirements.md](../requirements.md) FR-6 (original wording): *"The
  system shall route cases to human review when information is
  missing..."* — read literally, every incomplete case needs a human.
- [migration_plan.md §7.A](../database/migration_plan.md#7-status--code-vocabulary-mapping):
  *"Missing required information | Not a `workflow_status_code` —
  represented via `rule_evaluations`, `prior_authorization_cases.case_status_code
  = PENDING_INFORMATION`, and `next_action_code = REQUEST_MISSING_INFORMATION`"*
  — and `workflow_actions.REQUEST_MISSING_INFORMATION.requires_human = 0`
  in the approved reference-data catalog — read together, missing
  information is an *automated* outcome, not a human-review case.

The current LangGraph implementation followed FR-6's literal reading
(every incomplete case → `human_review_required_node`), which is why
the conflict stayed silent until a NOT NULL persistence column forced
the question. This ADR resolves it, and generalizes the resolution
into a standing security principle this project applies everywhere,
not only to missing information.

## Decision

### A. Universal least-privilege escalation boundary (applies project-wide, not only to Task 23)
Automation in this project — any deterministic rule, any AI-assisted
step, any future integration — may **only** use:
1. Authenticated APIs it is already configured to call.
2. Explicitly approved FHIR-style/integration endpoints.
3. Explicitly approved data sources.
4. Permissions already granted to the current service account/user.

Automation must **never**, under any circumstance, including to obtain
missing information:
- Exceed the current service-account/user's permissions.
- Bypass or circumvent access controls.
- Fall back to a prohibited or unapproved data source.
- Request or trigger a permission change for itself.
- Retrieve more PHI/PII or sensitive data than the task actually needs.
- Persist unnecessary PHI/PII.
- Log secrets, credentials, tokens, passwords, connection strings, raw
  LLM prompts, or raw LLM/provider responses (already established
  practice — see [security.md](../security.md) §2 — now stated as a
  boundary automation itself must never cross, not only a logging
  rule).

**If required information cannot be obtained within the current
authorized boundary, automation stops retrying and escalates to a
human — it never broadens its own permissions or tries an unapproved
source instead.** The audit trail must make it possible to determine,
for any such case: what information was needed, which approved source/
component was actually used, what result occurred, why automation
stopped or continued, and what next workflow action was selected —
using only the structured fields this project's audit schema already
defines (`event_type_code`, `source_component_code`, `result_code`,
`reason_code`, `metadata_json` small structured counts,
`workflow_runs.next_action_code`), never free-text secrets or
unnecessary PHI/PII.

### B. Two-stage missing-information model (the concrete application of (A) to case completeness)

**Stage 1 — deterministic, no escalation:**
Required information/documentation is missing on a case →
detected deterministically (unchanged: `src/rules/completeness.py`) →
the run completes with `next_action_code = REQUEST_MISSING_INFORMATION`
→ **no `human_reviews` row is created**. This matches
`workflow_actions.REQUEST_MISSING_INFORMATION.requires_human = 0`
exactly: requesting more information through the case's own approved
intake channel is an automated, no-permission-elevation action, not a
human task.

**Stage 2 — safe escalation, only after Stage 1's approved process still leaves the case unresolved:**
If required information remains unresolved after the approved
information-request process — or the information cannot be obtained
within the current authorized boundary at all (would require
permission expansion, access-control bypass, or an unapproved source),
or the available evidence remains materially ambiguous, or authorized
sources disagree materially, or the case cannot be resolved safely by
deterministic rules — automation stops and escalates: `HUMAN_REVIEW_REQUIRED`,
a `human_reviews` row is durably persisted, with the new reason code
below, using the **same `trace_id`**.

No retry count, timeout, or SLA value is defined by this ADR or by
Task 23's implementation — per [security.md](../security.md) §3,
business-sensitive thresholds are configuration, not something this
ADR invents. The system models an **explicit, externally-supplied**
"unresolved after the approved process" signal
(`CaseWorkflowState.missing_information_escalated`, a plain boolean);
deciding *when* to set it (how many attempts, how long to wait) is a
separate, future, explicitly-configured concern, not decided here.

### C. New reason code (reference-data catalog addition)
`HUMAN_REVIEW_UNRESOLVED_MISSING_INFORMATION` (`reason_type_code =
HUMAN_REVIEW`) — meaning: *required information remained unavailable/
unresolved after the approved information-request/retrieval process,
or could not be obtained within the existing authorized access
boundary.* This is **not** the same meaning as "information was found
missing on first validation" (Stage 1, which never reaches
`human_reviews` at all) — using this code for Stage 1 would be exactly
the kind of code misuse this project's reason-code discipline forbids.
The four existing `HUMAN_REVIEW` reasons
(`HUMAN_REVIEW_EVIDENCE_MISMATCH`, `HUMAN_REVIEW_FHIR_FAILURE`,
`HUMAN_REVIEW_AI_FAILURE`, `HUMAN_REVIEW_AMBIGUITY`) are unchanged and
must not be reused for this meaning either.

### D. FR-6 correction
FR-6 is corrected (not silently — see
[requirements.md](../requirements.md) §7 for the exact revised text and
its own note explaining the change) to read: missing information is
handled deterministically first via an approved information-request
process; only if it remains unresolved through that approved process,
or cannot be obtained within existing authorized permissions/sources,
does the case route to human review.

## Rationale
- Resolves a real, previously-silent conflict between two approved
  documents (FR-6 vs. `migration_plan.md` §7.A) by checking both
  against the actual reference-data catalog
  (`workflow_actions.REQUEST_MISSING_INFORMATION.requires_human = 0`),
  which only one reading was consistent with.
- Keeps `human_reviews.reason_code`'s NOT NULL constraint intact and
  meaningful — every review row now has an honest, specific reason,
  never a reused/misapplied existing code.
- Matches this project's existing least-privilege principle
  ([security.md](../security.md) §4) and extends it from "credentials
  are scoped narrowly" to "automation never tries to widen its own
  access, ever, even to finish a task" — a stronger, more general
  statement of the same idea.
- Avoids inventing retry/timeout/SLA business values this task has no
  approved source for, per [security.md](../security.md) §3's existing
  configuration-vs-hard-coding rule.
- Keeps AI fully out of this decision: the escalation flag and the
  human-review outcome are both supplied externally (by the
  application boundary and, eventually, a human reviewer,
  respectively) — never derived from AI output, preserving
  [ADR-001](ADR-001-deterministic-first.md).

## Consequences
- `src/workflow/state.py`/`graph.py`/`nodes.py` gain one new explicit
  input field and one new terminal node distinguishing "case complete
  but missing info, request it" from "needs a human" — a real,
  reviewed routing-behavior change, not merely a persistence-layer
  addition.
- `reasons` (reference data) gains exactly one new approved row; no
  new `event_types`/`event_categories`/other catalog table is needed —
  every other auditable fact Task 23 needs already has an approved
  code (see the Final Report's audit-catalog inspection).
- Stage 1's automated "request missing information" outcome is
  representable and auditable today, even though the actual
  request/response transport (e.g., notifying a case submitter) is not
  built in Task 23 and remains future work — this ADR only fixes the
  *routing and persistence* semantics, not that transport.
- This ADR's Part A (the universal boundary) is recorded in
  [CLAUDE.md](../../CLAUDE.md) as a standing rule for all future work
  in this repository, not only for Task 23.

## Alternatives Considered

**Alternative A — Reuse `HUMAN_REVIEW_AMBIGUITY` for unresolved missing information.** Rejected: explicitly a different business meaning ("material ambiguity in the evidence" vs. "information never arrived through the approved channel"); reusing it would make the persisted reason inaccurate, which is exactly what this project's reason-code discipline (`reference_data.md` §1: "do not reuse a retired code for a different meaning") already warns against, extended here to *any* code, not only retired ones.

**Alternative B — Change `human_reviews.reason_code` to nullable.** Rejected: the canonical design documents it as required with no exception noted anywhere; loosening it would be changing approved schema to route around a real semantic gap, not fixing the gap.

**Alternative C — Leave FR-6 as originally worded and treat every incomplete case as requiring human review (today's actual behavior).** Rejected: contradicts the already-approved `workflow_actions.REQUEST_MISSING_INFORMATION.requires_human = 0` and `migration_plan.md` §7.A target design, and would route every incomplete case to a human unnecessarily, which is not the automated, least-privilege-first behavior this project otherwise commits to.

## Related
- [ADR-001-deterministic-first.md](ADR-001-deterministic-first.md)
- [ADR-007-trace-id-and-workflow-step-mapping.md](ADR-007-trace-id-and-workflow-step-mapping.md)
- [../requirements.md](../requirements.md) — FR-6 (corrected)
- [../security.md](../security.md) — least-privilege, configuration-vs-hard-coding
- [../database/reference_data.md](../database/reference_data.md) — reasons catalog, workflow_actions
- [../database/migration_plan.md](../database/migration_plan.md) §7.A — status/code vocabulary mapping
