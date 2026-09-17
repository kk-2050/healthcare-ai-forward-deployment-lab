<!--
File Name: phase1_relational_erd_mermaid.md
Purpose: Phase 1 canonical relational database ERD and relationship reference
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# Phase 1 Canonical Relational Database ERD

**Status:** DESIGN BASELINE — target Phase 1 relational model; not fully implemented.

> This is a relationship-focused ERD. [data_dictionary.md](../data_dictionary.md) is authoritative for field-level definitions; [constraints_and_indexes.md](../constraints_and_indexes.md) is authoritative for physical constraints, keys, and indexes. See [data_model.md](../data_model.md) for the full narrative design rationale.

```mermaid
flowchart LR
  subgraph organization["Organization"]
    clients["clients"]
    departments["departments"]
    locations["locations"]
    countries["countries"]
  end
  subgraph requirements["Requirements"]
    discovery_item_types["discovery_item_types"]
    client_requirement_intakes["client_requirement_intakes"]
    client_requirement_items["client_requirement_items"]
    requirement_types["requirement_types"]
    requirement_sets["requirement_sets"]
    requirement_rules["requirement_rules"]
    document_types["document_types"]
  end
  subgraph workflow_reference["Workflow Reference"]
    case_statuses["case_statuses"]
    reasons["reasons"]
    workflow_definitions["workflow_definitions"]
    workflow_definition_steps["workflow_definition_steps"]
    workflow_statuses["workflow_statuses"]
    workflow_actions["workflow_actions"]
  end
  subgraph audit_reference["Audit Reference"]
    event_categories["event_categories"]
    event_types["event_types"]
    actor_types["actor_types"]
    source_components["source_components"]
    result_codes["result_codes"]
    failure_categories["failure_categories"]
  end
  subgraph ai_human_reference["Ai Human Reference"]
    human_review_statuses["human_review_statuses"]
    human_review_outcomes["human_review_outcomes"]
    ai_task_types["ai_task_types"]
  end
  subgraph case_processing["Case Processing"]
    prior_authorization_cases["prior_authorization_cases"]
    case_diagnoses["case_diagnoses"]
    case_documents["case_documents"]
    workflow_runs["workflow_runs"]
    rule_evaluations["rule_evaluations"]
    integration_executions["integration_executions"]
    ai_analysis_runs["ai_analysis_runs"]
    ai_analysis_tasks["ai_analysis_tasks"]
    human_reviews["human_reviews"]
    audit_events["audit_events"]
  end
  countries -->|"default_country_code"| clients
  clients -->|"client_id"| departments
  departments -. "parent_department_id" .-> departments
  locations -->|"primary_location_id"| departments
  clients -->|"client_id"| locations
  countries -->|"country_code"| locations
  clients -->|"client_id"| client_requirement_intakes
  client_requirement_intakes -->|"intake_id"| client_requirement_items
  discovery_item_types -->|"discovery_item_type_code"| client_requirement_items
  workflow_definitions -->|"workflow_definition_id"| workflow_definition_steps
  source_components -->|"source_component_code"| workflow_definition_steps
  clients -->|"client_id"| requirement_sets
  workflow_definitions -->|"workflow_definition_id"| requirement_sets
  requirement_sets -->|"requirement_set_id"| requirement_rules
  requirement_types -->|"requirement_type_code"| requirement_rules
  document_types -->|"document_type_code"| requirement_rules
  clients -->|"client_id"| prior_authorization_cases
  departments -->|"department_id"| prior_authorization_cases
  locations -->|"location_id"| prior_authorization_cases
  case_statuses -->|"case_status_code"| prior_authorization_cases
  source_components -->|"source_component_code"| prior_authorization_cases
  reasons -->|"close_reason_code"| prior_authorization_cases
  prior_authorization_cases -->|"case_id"| case_diagnoses
  source_components -->|"source_component_code"| case_diagnoses
  prior_authorization_cases -->|"case_id"| case_documents
  document_types -->|"document_type_code"| case_documents
  source_components -->|"source_component_code"| case_documents
  prior_authorization_cases -->|"case_id"| workflow_runs
  workflow_definitions -->|"workflow_definition_id"| workflow_runs
  workflow_statuses -->|"workflow_status_code"| workflow_runs
  workflow_actions -->|"next_action_code"| workflow_runs
  failure_categories -->|"failure_category_code"| workflow_runs
  departments -->|"processing_department_id"| workflow_runs
  locations -->|"processing_location_id"| workflow_runs
  source_components -->|"initiated_by_component_code"| workflow_runs
  workflow_runs -->|"trace_id"| rule_evaluations
  prior_authorization_cases -->|"case_id"| rule_evaluations
  requirement_rules -->|"requirement_rule_id"| rule_evaluations
  result_codes -->|"result_code"| rule_evaluations
  reasons -->|"reason_code"| rule_evaluations
  source_components -->|"source_component_code"| rule_evaluations
  workflow_runs -->|"trace_id"| integration_executions
  prior_authorization_cases -->|"case_id"| integration_executions
  source_components -->|"source_component_code"| integration_executions
  result_codes -->|"result_code"| integration_executions
  failure_categories -->|"failure_category_code"| integration_executions
  workflow_runs -->|"trace_id"| ai_analysis_runs
  prior_authorization_cases -->|"case_id"| ai_analysis_runs
  source_components -->|"source_component_code"| ai_analysis_runs
  result_codes -->|"result_code"| ai_analysis_runs
  failure_categories -->|"failure_category_code"| ai_analysis_runs
  ai_analysis_runs -->|"ai_analysis_id"| ai_analysis_tasks
  ai_task_types -->|"ai_task_type_code"| ai_analysis_tasks
  result_codes -->|"result_code"| ai_analysis_tasks
  workflow_runs -->|"trace_id"| human_reviews
  prior_authorization_cases -->|"case_id"| human_reviews
  human_review_statuses -->|"review_status_code"| human_reviews
  human_review_outcomes -->|"review_outcome_code"| human_reviews
  reasons -->|"reason_code"| human_reviews
  departments -->|"assigned_department_id"| human_reviews
  locations -->|"assigned_location_id"| human_reviews
  actor_types -->|"reviewer_actor_type_code"| human_reviews
  source_components -->|"source_component_code"| human_reviews
  workflow_runs -->|"trace_id"| audit_events
  prior_authorization_cases -->|"case_id"| audit_events
  event_types -->|"event_type_code"| audit_events
  event_categories -->|"event_category_code"| audit_events
  workflow_statuses -->|"workflow_status_code"| audit_events
  workflow_definition_steps -->|"workflow_step_id"| audit_events
  source_components -->|"source_component_code"| audit_events
  actor_types -->|"actor_type_code"| audit_events
  result_codes -->|"result_code"| audit_events
  failure_categories -->|"failure_category_code"| audit_events
  reasons -->|"reason_code"| audit_events
  audit_events -. "related_event_id" .-> audit_events
```

## Control-field policy

Every persistent table except `audit_events` includes:

`is_deleted`, `created_at_utc`, `created_by`, `updated_at_utc`, `updated_by`, `deleted_at_utc`, `deleted_by`, `delete_reason_code`, `delete_reason_text`.

`audit_events` is append-only / immutable.

For readability, the universal `delete_reason_code -> reasons.reason_code` relationship is documented as a policy rather than drawing an edge from every non-audit table.

## Related documentation

- [data_model.md](../data_model.md) — canonical data model and normalization rationale
- [data_dictionary.md](../data_dictionary.md) — authoritative field-level dictionary
- [reference_data.md](../reference_data.md) — proposed controlled seed/reference-data catalog
- [constraints_and_indexes.md](../constraints_and_indexes.md) — authoritative relational integrity, uniqueness, CHECK constraint, and index catalog
- [phase1_relational_erd_overview.svg](phase1_relational_erd_overview.svg) — relationship-oriented visual overview
- [phase1_relational_erd_full.svg](phase1_relational_erd_full.svg) — detailed field-level/reference view
- [../../decisions/ADR-004-phase1-canonical-data-model.md](../../decisions/ADR-004-phase1-canonical-data-model.md) — the architecture decision record for this model
