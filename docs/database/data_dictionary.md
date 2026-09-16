<!--
File Name: data_dictionary.md
Purpose: Field-level Phase 1 data dictionary with SQL type, nullability, keys, source, business rules, sensitivity, and examples
Creation Date: 2026-09-16
Author: K.Kashiwagi
-->

# Healthcare AI Forward Deployment Lab — Data Dictionary v2.2

**Scope:** All 36 Phase 1 tables and every proposed field.
**Database:** Microsoft SQL Server.
**Naming:** lowercase snake_case.
**Data:** synthetic healthcare data only.

## Column definitions used in this dictionary

- **sql_type** — proposed SQL Server type
- **null_allowed** — whether the physical column accepts NULL
- **attribute** — PK/FK/UK/BUSINESS/CONTROL/TECHNICAL/EXTENSION
- **default** — proposed default
- **description** — semantic meaning
- **fk_reference** — referenced parent field where applicable
- **business_rule** — lifecycle/conditional requirement
- **source** — authoritative producer/source
- **sensitivity** — data-classification guidance
- **example_value** — synthetic example only
- **phase** — implementation scope
- **notes** — additional design notes

> Important: `NULL Allowed = YES` does not override a conditional business rule.
> Example: `completed_at_utc` is nullable while a workflow is running, but required when the workflow reaches a terminal status.


## `clients`

**Category:** Master
**Purpose:** Client/organization using the prior-authorization workflow.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| client_id | nvarchar(64) | NO | PK | — | Immutable internal client identifier. |  | Required for a valid row. | Application-generated identifier | None | cli_0001 | Phase 1 | Synthetic in Phase 1. |
| client_code | nvarchar(64) | NO | UK | — | Stable business code for the client. |  | Required for a valid row. | Seed / controlled configuration | None | DEMO_HEALTH | Phase 1 | Unique. |
| client_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Demo Health Plan | Phase 1 | Synthetic client names only. |
| client_type_code | nvarchar(64) | YES | BUSINESS | NULL | Optional client classification. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Controlled by application configuration in Phase 1. |
| default_country_code | char(2) | YES | FK | NULL | Default country for the client. | countries.country_code | Must reference an active/valid parent record when populated. References countries.country_code. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References countries.country_code. |
| default_time_zone | nvarchar(64) | YES | BUSINESS | NULL | IANA time-zone name used for display/localization. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic value | Phase 1 | Persist operational timestamps in UTC regardless. |
| is_active | bit | NO | BUSINESS | 1 | Whether the client may be used for new cases. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 | Independent of is_deleted. |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled small client metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | Valid JSON only; no secrets/PHI/PII. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `departments`

**Category:** Master
**Purpose:** Organizational department within a client.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| department_id | nvarchar(64) | NO | PK | — | Immutable internal department identifier. |  | Required for a valid row. | Application-generated identifier | None | dep_0001 | Phase 1 |  |
| client_id | nvarchar(64) | NO | FK | — | Owning client. | clients.client_id | Must reference an active/valid parent record when populated. References clients.client_id. | Application-generated identifier | None | cli_0001 | Phase 1 | References clients.client_id. |
| department_code | nvarchar(64) | NO | UK(partial) | — | Department code within the client. |  | Required for a valid row. | Seed / controlled configuration | None | PA_OPERATIONS | Phase 1 | Unique with client_id. |
| department_name | nvarchar(200) | NO | BUSINESS | — | Department display name. |  | Required for a valid row. | Seed / controlled configuration | None | Prior Authorization Operations | Phase 1 |  |
| parent_department_id | nvarchar(64) | YES | FK | NULL | Optional parent department for hierarchy. |  | Must reference an active/valid parent record when populated. Self-reference. | Seed / controlled configuration | None | synthetic_id | Phase 1 | Self-reference. |
| primary_location_id | nvarchar(64) | YES | FK | NULL | Primary operating location. | locations.location_id | Must reference an active/valid parent record when populated. References locations.location_id. | Seed / controlled configuration | None | synthetic_id | Phase 1 | References locations.location_id. |
| is_active | bit | NO | BUSINESS | 1 | Whether the department accepts new work. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled small department metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No secrets/PHI/PII. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `countries`

**Category:** Reference Master
**Purpose:** Country reference list used by locations and clients.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| country_code | char(2) | NO | PK | — | ISO 3166-1 alpha-2 country code. |  | Required for a valid row. | Seed / controlled configuration | None | US | Phase 1 | Example: US, JP. |
| country_name | nvarchar(100) | NO | BUSINESS | — | Country display name. |  | Required for a valid row. | Seed / controlled configuration | None | United States | Phase 1 |  |
| iso3_code | char(3) | YES | UK | NULL | ISO 3166-1 alpha-3 code. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | USA | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the country can be selected for new records. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `locations`

**Category:** Master
**Purpose:** Client operating/processing location.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| location_id | nvarchar(64) | NO | PK | — | Immutable location identifier. |  | Required for a valid row. | Application-generated identifier | None | loc_0001 | Phase 1 |  |
| client_id | nvarchar(64) | NO | FK | — | Owning client. | clients.client_id | Must reference an active/valid parent record when populated. References clients.client_id. | Application-generated identifier | None | cli_0001 | Phase 1 | References clients.client_id. |
| location_code | nvarchar(64) | NO | UK(partial) | — | Location code within the client. |  | Required for a valid row. | Seed / controlled configuration | None | CHI_OPS | Phase 1 | Unique with client_id. |
| location_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Chicago Operations | Phase 1 |  |
| country_code | char(2) | NO | FK | — | Country. | countries.country_code | Must reference an active/valid parent record when populated. References countries.country_code. | Seed / controlled configuration | None | US | Phase 1 | References countries.country_code. |
| state_province | nvarchar(100) | YES | BUSINESS | NULL | State/province/region. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | Synthetic only in Phase 1. |
| city | nvarchar(100) | YES | BUSINESS | NULL | City/locality. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | Synthetic only in Phase 1. |
| postal_code | nvarchar(32) | YES | BUSINESS | NULL | Postal code. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | SYN_CODE | Phase 1 | Synthetic only in Phase 1; no real addresses. |
| time_zone | nvarchar(64) | NO | BUSINESS | — | IANA time-zone identifier. |  | Required for a valid row. | Seed / controlled configuration | None | America/Chicago | Phase 1 | Used for display only; persisted timestamps remain UTC. |
| location_type_code | nvarchar(64) | YES | BUSINESS | NULL | Location type such as OPERATIONS or REVIEW_CENTER. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Application-controlled in Phase 1. |
| is_active | bit | NO | BUSINESS | 1 | Whether the location accepts new work. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled small location metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No precise real addresses in Phase 1. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `case_statuses`

**Category:** Reference Master
**Purpose:** Controlled business lifecycle states for a case.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| case_status_code | nvarchar(64) | NO | PK | — | Case lifecycle code. |  | Required for a valid row. | Seed / controlled configuration | None | OPEN | Phase 1 | Examples: OPEN, IN_PROGRESS, CLOSED. |
| case_status_name | nvarchar(100) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Meaning of the status. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_terminal | bit | NO | BUSINESS | 0 | Whether the status ends normal case processing. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 | CLOSED is terminal but not deleted. |
| sort_order | int | NO | BUSINESS | 0 | Display/order value. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the status is selectable for new transitions. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `reasons`

**Category:** Reference Master
**Purpose:** Controlled reasons for case close, logical delete, human review, audit correction, and other business events.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| reason_code | nvarchar(64) | NO | PK | — | Globally unique reason code. |  | Required for a valid row. | Seed / controlled configuration | None | EVIDENCE_MISMATCH_SERVICE_CODE | Phase 1 | Use domain-prefixed codes to keep one-column FKs simple. |
| reason_type_code | nvarchar(64) | NO | BUSINESS | — | Reason domain, e.g. CASE_CLOSE, DELETE, HUMAN_REVIEW, AUDIT_CORRECTION. |  | Required for a valid row. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Application-controlled in Phase 1. |
| reason_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Business definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| requires_text | bit | NO | BUSINESS | 0 | Whether supplemental free text is required. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the reason may be used on new records. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `workflow_definitions`

**Category:** Master
**Purpose:** Versioned workflow definition used to identify exactly which orchestration design processed a run.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| workflow_definition_id | nvarchar(64) | NO | PK | — | Immutable workflow-definition identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| workflow_code | nvarchar(64) | NO | UK(partial) | — | Stable workflow family code. |  | Required for a valid row. | Seed / controlled configuration | None | PRIOR_AUTHORIZATION | Phase 1 |  |
| version_no | nvarchar(32) | NO | UK(partial) | — | Workflow version. |  | Required for a valid row. | Seed / controlled configuration | None | 1.0 | Phase 1 | Unique with workflow_code. |
| workflow_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(1000) | YES | BUSINESS | NULL | Definition summary. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| effective_from_utc | datetime2(3) | NO | BUSINESS | — | Start of validity. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| effective_to_utc | datetime2(3) | YES | BUSINESS | NULL | End of validity. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether this version may start new runs. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `workflow_definition_steps`

**Category:** Configuration Detail
**Purpose:** Ordered steps belonging to a versioned workflow definition.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| workflow_step_id | nvarchar(64) | NO | PK | — | Immutable workflow-step identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| workflow_definition_id | nvarchar(64) | NO | FK | — | Owning workflow definition. | workflow_definitions.workflow_definition_id | Must reference an active/valid parent record when populated. References workflow_definitions.workflow_definition_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References workflow_definitions.workflow_definition_id. |
| step_code | nvarchar(64) | NO | UK(partial) | — | Stable step code within a workflow definition. |  | Required for a valid row. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Unique with workflow_definition_id. |
| step_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| step_order | int | NO | BUSINESS | — | Nominal display/process order. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 | Branching is still governed by LangGraph. |
| source_component_code | nvarchar(64) | YES | FK | NULL | Default component responsible for the step. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | Seed / controlled configuration | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| is_optional | bit | NO | BUSINESS | 0 | Whether a valid path may skip the step. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the step is active in this definition. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `workflow_statuses`

**Category:** Reference Master
**Purpose:** Controlled workflow-run states.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| workflow_status_code | nvarchar(64) | NO | PK | — | Workflow status code. |  | Required for a valid row. | Seed / controlled configuration | None | PROCESSING | Phase 1 | Examples: PROCESSING, HUMAN_REVIEW_REQUIRED, COMPLETED, FAILED. |
| workflow_status_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Status definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_terminal | bit | NO | BUSINESS | 0 | Whether no automated processing should continue. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| requires_human_review | bit | NO | BUSINESS | 0 | Whether the status requires human review. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| sort_order | int | NO | BUSINESS | 0 | Display order. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the status may be assigned to new runs. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `workflow_actions`

**Category:** Reference Master
**Purpose:** Controlled next-step actions recommended or selected by the workflow.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| workflow_action_code | nvarchar(64) | NO | PK | — | Action code. |  | Required for a valid row. | Seed / controlled configuration | None | ROUTE_HUMAN_REVIEW | Phase 1 | Examples: CONTINUE_PROCESSING, REQUEST_MISSING_INFORMATION, ROUTE_HUMAN_REVIEW, COMPLETE_WORKFLOW. |
| workflow_action_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Action definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| requires_human | bit | NO | BUSINESS | 0 | Whether action execution requires a human. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_terminal | bit | NO | BUSINESS | 0 | Whether action ends the workflow run. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the action may be selected. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `requirement_types`

**Category:** Reference Master
**Purpose:** Controlled categories of deterministic requirements/rules.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| requirement_type_code | nvarchar(64) | NO | PK | — | Requirement type code. |  | Required for a valid row. | Seed / controlled configuration | None | REQUIRED_DOCUMENT | Phase 1 | Examples: REQUIRED_DOCUMENT, REQUIRED_FIELD, NOTES_REQUIRED, EVIDENCE_MATCH. |
| requirement_type_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the type may be used in new rules. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `requirement_sets`

**Category:** Master
**Purpose:** Versioned client-specific deterministic requirement set.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| requirement_set_id | nvarchar(64) | NO | PK | — | Immutable requirement-set identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| client_id | nvarchar(64) | NO | FK | — | Client that owns the requirement set. | clients.client_id | Must reference an active/valid parent record when populated. References clients.client_id. | Application-generated identifier | None | cli_0001 | Phase 1 | References clients.client_id. |
| workflow_definition_id | nvarchar(64) | NO | FK | — | Workflow version to which the set applies. | workflow_definitions.workflow_definition_id | Must reference an active/valid parent record when populated. References workflow_definitions.workflow_definition_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References workflow_definitions.workflow_definition_id. |
| set_code | nvarchar(64) | NO | UK(partial) | — | Requirement-set business code. |  | Required for a valid row. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Unique with client_id and version_no. |
| set_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| version_no | nvarchar(32) | NO | UK(partial) | — | Requirement-set version. |  | Required for a valid row. | Seed / controlled configuration | None | 1.0 | Phase 1 |  |
| service_code_scope | nvarchar(64) | YES | BUSINESS | NULL | Optional synthetic service-code scope. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | Clinical if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | Service-code master is intentionally deferred; Phase 1 uses synthetic codes. |
| effective_from_utc | datetime2(3) | NO | BUSINESS | — | Start of validity. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| effective_to_utc | datetime2(3) | YES | BUSINESS | NULL | End of validity. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the set may be selected for new cases. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Small controlled set-level metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No executable code, secrets, PHI, or raw prompts. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `document_types`

**Category:** Reference Master
**Purpose:** Controlled supporting-document types used by completeness checks.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| document_type_code | nvarchar(64) | NO | PK | — | Document type code. |  | Required for a valid row. | Seed / controlled configuration | None | CLINICAL_NOTE | Phase 1 | Examples: CLINICAL_NOTE, IMAGING_REPORT, PT_DOCUMENTATION. |
| document_type_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Document type definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the type may be used on new cases/rules. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `event_categories`

**Category:** Reference Master
**Purpose:** High-level audit-event categories.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| event_category_code | nvarchar(64) | NO | PK | — | Category code. |  | Required for a valid row. | Seed / controlled configuration | None | RULE | Phase 1 | Examples: WORKFLOW, FHIR, RULE, AI, HUMAN, ERROR. |
| event_category_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Category definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the category may be used for new events. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `event_types`

**Category:** Reference Master
**Purpose:** Controlled audit-event types.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| event_type_code | nvarchar(64) | NO | PK | — | Event type code. |  | Required for a valid row. | Seed / controlled configuration | None | COMPLETENESS_CHECKED | Phase 1 | Examples: FHIR_RETRIEVAL_SUCCEEDED, AI_ANALYSIS_SUCCEEDED, WORKFLOW_COMPLETED. |
| event_category_code | nvarchar(64) | NO | FK | — | Event category. | event_categories.event_category_code | Must reference an active/valid parent record when populated. References event_categories.event_category_code. | Seed / controlled configuration | None | RULE | Phase 1 | References event_categories.event_category_code. |
| event_type_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(700) | YES | BUSINESS | NULL | Exact event semantics/trigger. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether new events may use this type. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `actor_types`

**Category:** Reference Master
**Purpose:** Controlled types of actors that can initiate or perform actions.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| actor_type_code | nvarchar(64) | NO | PK | — | Actor type code. |  | Required for a valid row. | Seed / controlled configuration | None | SYSTEM | Phase 1 | Examples: SYSTEM, AI_SERVICE, HUMAN_REVIEWER, API_CLIENT. |
| actor_type_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_human | bit | NO | BUSINESS | 0 | Whether this actor type represents a human. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether new records may use this actor type. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `source_components`

**Category:** Reference Master
**Purpose:** Controlled system/component registry for internal Phase 1 components.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| source_component_code | nvarchar(64) | NO | PK | — | Component code. |  | Required for a valid row. | Seed / controlled configuration | None | LANGGRAPH | Phase 1 | Examples: FASTAPI, LANGGRAPH, FHIR_STYLE_CLIENT, AZURE_OPENAI_ADAPTER, STREAMLIT. |
| component_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| component_type_code | nvarchar(64) | YES | BUSINESS | NULL | Optional type such as API, ORCHESTRATOR, ADAPTER, UI. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | SYN_CODE | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Component responsibility. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| version_label | nvarchar(64) | YES | BUSINESS | NULL | Non-secret component/version label. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the component is active. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `result_codes`

**Category:** Reference Master
**Purpose:** Controlled result/outcome codes for technical/business processing events.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| result_code | nvarchar(64) | NO | PK | — | Result code. |  | Required for a valid row. | Seed / controlled configuration | None | SUCCESS | Phase 1 | Examples: SUCCESS, FAILED, COMPLETE, ROUTED, MISSING_INFORMATION. |
| result_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Result semantics. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_success | bit | NO | BUSINESS | 0 | Whether the code represents successful processing. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether new records may use this result. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `failure_categories`

**Category:** Reference Master
**Purpose:** Controlled technical/business failure classifications.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| failure_category_code | nvarchar(64) | NO | PK | — | Failure category code. |  | Required for a valid row. | Seed / controlled configuration | None | AI_OUTPUT_INVALID | Phase 1 | Examples: FHIR_HTTP_ERROR, AI_PROVIDER_FAILED, AI_OUTPUT_INVALID, PERSISTENCE_ERROR. |
| failure_category_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(700) | YES | BUSINESS | NULL | Definition and intended handling. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_retryable | bit | NO | BUSINESS | 0 | Whether retry could be considered by a future policy. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 | Phase 1 scripts do not auto-retry unless explicitly designed. |
| requires_human_review_default | bit | NO | BUSINESS | 1 | Default routing expectation. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether new failures may use the category. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `human_review_statuses`

**Category:** Reference Master
**Purpose:** Controlled lifecycle states for human-review tasks.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| review_status_code | nvarchar(64) | NO | PK | — | Review status code. |  | Required for a valid row. | Seed / controlled configuration | None | REQUESTED | Phase 1 | Examples: REQUESTED, IN_PROGRESS, COMPLETED, CANCELLED. |
| review_status_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_terminal | bit | NO | BUSINESS | 0 | Whether the review task is finished. |  | Required for a valid row. | Seed / controlled configuration | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the status may be used. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `human_review_outcomes`

**Category:** Reference Master
**Purpose:** Controlled non-autonomous human-review outcomes.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| review_outcome_code | nvarchar(64) | NO | PK | — | Review outcome code. |  | Required for a valid row. | Seed / controlled configuration | None | CONTINUE_WORKFLOW | Phase 1 | Examples: CONTINUE_WORKFLOW, REQUEST_MORE_INFORMATION, ESCALATE, CLOSE_CASE. |
| review_outcome_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Outcome definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| returns_to_workflow | bit | NO | BUSINESS | 0 | Whether the case returns to automated workflow. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| closes_case | bit | NO | BUSINESS | 0 | Whether the human action closes the business case. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the outcome may be selected. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 | No AI approval/denial outcome is defined. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `discovery_item_types`

**Category:** Reference Master
**Purpose:** Controlled item types for Client Requirement Intake.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| discovery_item_type_code | nvarchar(64) | NO | PK | — | Item type code. |  | Required for a valid row. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | Examples: STAKEHOLDER, FUNCTIONAL_REQUIREMENT, TECHNICAL_REQUIREMENT, MISSING_INFORMATION, RISK, ACCEPTANCE_CRITERION. |
| discovery_item_type_name | nvarchar(150) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(500) | YES | BUSINESS | NULL | Definition. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| sort_order | int | NO | BUSINESS | 0 | Display order. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic value | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the item type may be used. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `ai_task_types`

**Category:** Reference Master
**Purpose:** Controlled AI task vocabulary used by structured AI analysis.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| ai_task_type_code | nvarchar(64) | NO | PK | — | AI task code. |  | Required for a valid row. | Seed / controlled configuration | None | IDENTIFY_AMBIGUITY | Phase 1 | Examples: SUMMARIZE_NARRATIVE, IDENTIFY_AMBIGUITY, IDENTIFY_TEXT_INCONSISTENCIES, SUGGEST_CLARIFYING_QUESTIONS. |
| ai_task_type_name | nvarchar(200) | NO | BUSINESS | — | Display name. |  | Required for a valid row. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| description | nvarchar(700) | YES | BUSINESS | NULL | Allowed task semantics and boundaries. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Seed / controlled configuration | None | Synthetic example | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the task may be requested. |  | Required for a valid row. | Seed / controlled configuration | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Seed / controlled configuration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Seed / controlled configuration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Seed / controlled configuration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `client_requirement_intakes`

**Category:** Transaction Header
**Purpose:** Captured FDE/client discovery intake used by the Streamlit Client Requirement Intake area.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| intake_id | nvarchar(64) | NO | PK | — | Immutable intake identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| client_id | nvarchar(64) | NO | FK | — | Client for whom requirements are being captured. | clients.client_id | Must reference an active/valid parent record when populated. References clients.client_id. | Application-generated identifier | None | cli_0001 | Phase 1 | References clients.client_id. |
| request_title | nvarchar(200) | NO | BUSINESS | — | Short synthetic title. |  | Required for a valid row. | Streamlit Client Requirement Intake | None | Synthetic value | Phase 1 |  |
| request_summary | nvarchar(2000) | NO | BUSINESS | — | Client request summary. |  | Required for a valid row. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Synthetic/business text only. |
| business_goal_summary | nvarchar(2000) | YES | BUSINESS | NULL | Business goal summary. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Synthetic/business text only. |
| intake_status_code | nvarchar(64) | NO | BUSINESS | DRAFT | Intake lifecycle code. |  | Required for a valid row. | Streamlit Client Requirement Intake | None | SYN_CODE | Phase 1 | Application enum in Phase 1; not a separate master unless workflow expands. |
| submitted_at_utc | datetime2(3) | YES | BUSINESS | NULL | When intake was submitted/finalized for analysis. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| schema_version | nvarchar(32) | NO | TECHNICAL | 1 | Version of the intake structure. |  | Required for a valid row. | Streamlit Client Requirement Intake | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled small intake metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No secrets/PHI/PII. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Streamlit Client Requirement Intake | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Streamlit Client Requirement Intake | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `client_requirement_items`

**Category:** Transaction Detail
**Purpose:** Individual stakeholder/requirement/risk/missing-information/acceptance-criterion items belonging to an intake.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| intake_item_id | nvarchar(64) | NO | PK | — | Immutable intake-item identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| intake_id | nvarchar(64) | NO | FK | — | Parent intake. | client_requirement_intakes.intake_id | Must reference an active/valid parent record when populated. References client_requirement_intakes.intake_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References client_requirement_intakes.intake_id. |
| discovery_item_type_code | nvarchar(64) | NO | FK | — | Item type. | discovery_item_types.discovery_item_type_code | Must reference an active/valid parent record when populated. References discovery_item_types.discovery_item_type_code. | Streamlit Client Requirement Intake | None | SYN_CODE | Phase 1 | References discovery_item_types.discovery_item_type_code. |
| sequence_no | int | NO | BUSINESS | 1 | Display/order number within type. |  | Required for a valid row. | Streamlit Client Requirement Intake | None | Synthetic value | Phase 1 |  |
| item_text | nvarchar(3000) | NO | BUSINESS | — | Atomic requirement/stakeholder/risk/etc. statement. |  | Required for a valid row. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Synthetic/business text only. |
| is_resolved | bit | NO | BUSINESS | 0 | Whether an open item has been resolved. |  | Required for a valid row. | Streamlit Client Requirement Intake | None | 0 | Phase 1 |  |
| resolution_text | nvarchar(2000) | YES | BUSINESS | NULL | Resolution summary if applicable. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Synthetic/business text only. |
| resolved_at_utc | datetime2(3) | YES | BUSINESS | NULL | Resolution timestamp. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Streamlit Client Requirement Intake | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Streamlit Client Requirement Intake | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Streamlit Client Requirement Intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `requirement_rules`

**Category:** Configuration Detail
**Purpose:** Atomic deterministic rule/requirement belonging to a requirement set.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| requirement_rule_id | nvarchar(64) | NO | PK | — | Immutable rule identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| requirement_set_id | nvarchar(64) | NO | FK | — | Parent requirement set. | requirement_sets.requirement_set_id | Must reference an active/valid parent record when populated. References requirement_sets.requirement_set_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References requirement_sets.requirement_set_id. |
| requirement_type_code | nvarchar(64) | NO | FK | — | Rule/requirement type. | requirement_types.requirement_type_code | Must reference an active/valid parent record when populated. References requirement_types.requirement_type_code. | Application | None | REQUIRED_DOCUMENT | Phase 1 | References requirement_types.requirement_type_code. |
| document_type_code | nvarchar(64) | YES | FK | NULL | Document type when the rule targets documentation. | document_types.document_type_code | Must reference an active/valid parent record when populated. References document_types.document_type_code. | Application | None | CLINICAL_NOTE | Phase 1 | References document_types.document_type_code. |
| target_field_name | nvarchar(128) | YES | BUSINESS | NULL | Allowed field name when the rule targets a structured field. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application | None | Synthetic example | Phase 1 | Must come from an allowlist; never arbitrary executable code. |
| operator_code | nvarchar(32) | YES | BUSINESS | NULL | Simple deterministic operator such as EXISTS, EQUALS, IN. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application | None | SYN_CODE | Phase 1 | Application-controlled. |
| expected_value_text | nvarchar(500) | YES | BUSINESS | NULL | Simple expected value when needed. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | No secrets/PHI; use only for safe configuration. |
| parameter_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled non-executable rule parameters. |  | Optional controlled rule parameters only; valid JSON, non-executable, allowlisted. | Application | Potentially sensitive if real; synthetic-only in Phase 1 | {"required": true} | Phase 1 | Valid JSON; no code snippets, prompts, secrets, or PHI. |
| sequence_no | int | NO | BUSINESS | 1 | Evaluation/display order. |  | Required for a valid row. | Application | None | Synthetic value | Phase 1 |  |
| is_required | bit | NO | BUSINESS | 1 | Whether failure of this rule means information is incomplete. |  | Required for a valid row. | Application | None | 0 | Phase 1 |  |
| is_active | bit | NO | BUSINESS | 1 | Whether the rule is active. |  | Required for a valid row. | Application | None | 1 | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Application | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Application | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Application | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `prior_authorization_cases`

**Category:** Case Master / Transaction Header
**Purpose:** Persistent case-level business record for the synthetic prior-authorization prototype.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| case_id | nvarchar(64) | NO | PK | — | Immutable internal case identifier. |  | Required for a valid row. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | Synthetic only in Phase 1. |
| client_id | nvarchar(64) | NO | FK | — | Owning client. | clients.client_id | Must reference an active/valid parent record when populated. References clients.client_id. | Application-generated identifier | None | cli_0001 | Phase 1 | References clients.client_id. |
| department_id | nvarchar(64) | YES | FK | NULL | Owning/business department. | departments.department_id | Must reference an active/valid parent record when populated. References departments.department_id. | Application-generated identifier | None | dep_0001 | Phase 1 | References departments.department_id. |
| location_id | nvarchar(64) | YES | FK | NULL | Owning/business location. | locations.location_id | Must reference an active/valid parent record when populated. References locations.location_id. | Application-generated identifier | Potentially sensitive if real; synthetic-only in Phase 1 | loc_0001 | Phase 1 | References locations.location_id. |
| case_status_code | nvarchar(64) | NO | FK | OPEN | Current business lifecycle status. | case_statuses.case_status_code | Must reference an active/valid parent record when populated. References case_statuses.case_status_code. | FastAPI / synthetic case intake | None | OPEN | Phase 1 | References case_statuses.case_status_code. |
| member_id | nvarchar(128) | NO | BUSINESS | — | Synthetic member identifier used by the prototype. |  | Required for a valid row. | FastAPI / synthetic case intake | Sensitive if real; synthetic-only in Phase 1 | SYN_MEMBER_001 | Phase 1 | Synthetic data only; production would require PHI/PII controls. |
| provider_id | nvarchar(128) | NO | BUSINESS | — | Synthetic provider identifier used by the prototype. |  | Required for a valid row. | FastAPI / synthetic case intake | Sensitive if real; synthetic-only in Phase 1 | SYN_PROVIDER_001 | Phase 1 | Provider master intentionally deferred. |
| requested_service_code | nvarchar(64) | NO | BUSINESS | — | Synthetic requested service/procedure code. |  | Required for a valid row. | FastAPI / synthetic case intake | Clinical if real; synthetic-only in Phase 1 | SYN_SERVICE_100 | Phase 1 | Service-code master intentionally deferred. |
| requested_date | date | NO | BUSINESS | — | Date of the authorization request. |  | Required for a valid row. | FastAPI / synthetic case intake | Potentially sensitive if real; synthetic-only in Phase 1 | 2026-09-16 | Phase 1 | Synthetic only. |
| source_component_code | nvarchar(64) | NO | FK | — | Component through which the case entered the system. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | FastAPI / synthetic case intake | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| opened_at_utc | datetime2(3) | NO | BUSINESS | — | Business case-open timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | May differ from created_at_utc if imported. |
| closed_at_utc | datetime2(3) | YES | BUSINESS | NULL | Business case-close timestamp. |  | NULL while case is open; required when case_status_code='CLOSED'. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Closing does not set is_deleted. |
| closed_by | nvarchar(128) | YES | BUSINESS | NULL | Human/system/component that closed the case. |  | NULL while case is open; required when case_status_code='CLOSED'. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when case_status_code=CLOSED. |
| close_reason_code | nvarchar(64) | YES | FK | NULL | Controlled business close reason. | reasons.reason_code | NULL while case is open; required when case_status_code='CLOSED'. | FastAPI / synthetic case intake | None | SYN_CODE | Phase 1 | References reasons.reason_code with CASE_CLOSE domain. |
| close_reason_text | nvarchar(1000) | YES | BUSINESS | NULL | Optional close explanation. |  | NULL allowed; required only when the selected close reason requires text. | FastAPI / synthetic case intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | No PHI/PII unless synthetic. |
| clinical_notes_present | bit | NO | BUSINESS | 0 | Whether clinical narrative was supplied to the workflow. |  | Required for a valid row. | FastAPI / synthetic case intake | None | Synthetic value | Phase 1 | Raw narrative is not stored in Case Master. |
| schema_version | nvarchar(32) | NO | TECHNICAL | 1 | Case record schema version. |  | Required for a valid row. | FastAPI / synthetic case intake | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled small case metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | FastAPI / synthetic case intake | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | Never store raw FHIR, raw prompts/responses, secrets, or real PHI/PII. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | FastAPI / synthetic case intake | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | FastAPI / synthetic case intake | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | FastAPI / synthetic case intake | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `case_diagnoses`

**Category:** Transaction Detail
**Purpose:** Diagnosis-code rows associated with a case.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| case_diagnosis_id | nvarchar(64) | NO | PK | — | Immutable diagnosis-row identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| case_id | nvarchar(64) | NO | FK | — | Parent case. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| diagnosis_code | nvarchar(64) | NO | BUSINESS | — | Synthetic diagnosis code. |  | Required for a valid row. | Synthetic case input / normalized evidence metadata | Clinical if real; synthetic-only in Phase 1 | SYN_DX_001 | Phase 1 | Diagnosis master intentionally deferred. |
| is_primary | bit | NO | BUSINESS | 0 | Whether this is the primary diagnosis for the case. |  | At most one active primary diagnosis per case. | Synthetic case input / normalized evidence metadata | None | 0 | Phase 1 | At most one primary diagnosis per case. |
| sequence_no | int | NO | BUSINESS | 1 | Display/order value. |  | Required for a valid row. | Synthetic case input / normalized evidence metadata | None | Synthetic value | Phase 1 |  |
| source_component_code | nvarchar(64) | YES | FK | NULL | Source of the diagnosis evidence. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | Synthetic case input / normalized evidence metadata | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Synthetic case input / normalized evidence metadata | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Synthetic case input / normalized evidence metadata | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Synthetic case input / normalized evidence metadata | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `case_documents`

**Category:** Transaction Detail
**Purpose:** Metadata/evidence reference for supporting documents associated with a case.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| case_document_id | nvarchar(64) | NO | PK | — | Immutable case-document identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| case_id | nvarchar(64) | NO | FK | — | Parent case. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| document_type_code | nvarchar(64) | NO | FK | — | Document type. | document_types.document_type_code | Must reference an active/valid parent record when populated. References document_types.document_type_code. | Synthetic case input / normalized evidence metadata | None | CLINICAL_NOTE | Phase 1 | References document_types.document_type_code. |
| document_reference | nvarchar(200) | NO | BUSINESS | — | Synthetic/external-safe document reference, not file contents. |  | Required for a valid row. | Synthetic case input / normalized evidence metadata | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | Do not use PHI-bearing filenames. |
| received_at_utc | datetime2(3) | YES | BUSINESS | NULL | When document evidence became available. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| source_component_code | nvarchar(64) | YES | FK | NULL | Component/source that supplied the document evidence. | source_components.source_component_code | Must reference an active/valid parent record when populated. | Synthetic case input / normalized evidence metadata | None | LANGGRAPH | Phase 1 |  |
| is_available | bit | NO | BUSINESS | 1 | Whether the referenced document is currently available to the workflow. |  | Required for a valid row. | Synthetic case input / normalized evidence metadata | None | 0 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled document metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Synthetic case input / normalized evidence metadata | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No raw document content/PHI. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Synthetic case input / normalized evidence metadata | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Synthetic case input / normalized evidence metadata | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Synthetic case input / normalized evidence metadata | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |
## `workflow_runs`

**Category:** Transaction Header
**Purpose:** One execution of the workflow for a case; current state for that run.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| trace_id | nvarchar(64) | NO | PK | — | Immutable workflow-run/trace identifier. |  | Required for a valid row. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 |  |
| case_id | nvarchar(64) | NO | FK | — | Case being processed. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| workflow_definition_id | nvarchar(64) | NO | FK | — | Exact workflow version used. | workflow_definitions.workflow_definition_id | Must reference an active/valid parent record when populated. References workflow_definitions.workflow_definition_id; avoids redundant workflow_version column. | Application-generated identifier | None | synthetic_id | Phase 1 | References workflow_definitions.workflow_definition_id; avoids redundant workflow_version column. |
| workflow_status_code | nvarchar(64) | NO | FK | PROCESSING | Current workflow status. | workflow_statuses.workflow_status_code | Must reference an active/valid parent record when populated. References workflow_statuses.workflow_status_code. | LangGraph workflow orchestration | None | PROCESSING | Phase 1 | References workflow_statuses.workflow_status_code. |
| next_action_code | nvarchar(64) | YES | FK | NULL | Current recommended/selected next workflow action. | workflow_actions.workflow_action_code | Must reference an active/valid parent record when populated. References workflow_actions.workflow_action_code. | LangGraph workflow orchestration | None | SYN_CODE | Phase 1 | References workflow_actions.workflow_action_code. |
| human_review_required | bit | NO | BUSINESS | 0 | Whether the run requires human review. |  | Required for a valid row. | LangGraph workflow orchestration | None | 0 | Phase 1 |  |
| failure_category_code | nvarchar(64) | YES | FK | NULL | Current/terminal failure classification if any. | failure_categories.failure_category_code | NULL for non-failure outcomes; populated for classified technical/workflow failure. | LangGraph workflow orchestration | None | AI_OUTPUT_INVALID | Phase 1 | References failure_categories.failure_category_code. |
| processing_department_id | nvarchar(64) | YES | FK | NULL | Department responsible for this run. | departments.department_id | Must reference an active/valid parent record when populated. May differ from case ownership department. | LangGraph workflow orchestration | None | synthetic_id | Phase 1 | May differ from case ownership department. |
| processing_location_id | nvarchar(64) | YES | FK | NULL | Location responsible for this run. | locations.location_id | Must reference an active/valid parent record when populated. May differ from case ownership location. | LangGraph workflow orchestration | Potentially sensitive if real; synthetic-only in Phase 1 | synthetic_id | Phase 1 | May differ from case ownership location. |
| initiated_by_component_code | nvarchar(64) | NO | FK | — | Component that started the run. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | LangGraph workflow orchestration | None | SYN_CODE | Phase 1 | References source_components.source_component_code. |
| started_at_utc | datetime2(3) | NO | BUSINESS | — | Workflow start timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| completed_at_utc | datetime2(3) | YES | BUSINESS | NULL | Workflow terminal timestamp. |  | NULL while run is non-terminal; required when workflow_status_code is terminal. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| schema_version | nvarchar(32) | NO | TECHNICAL | 1 | Workflow-run record schema version. |  | Required for a valid row. | LangGraph workflow orchestration | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Controlled run metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | LangGraph workflow orchestration | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No raw clinical/FHIR/LLM payloads. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | LangGraph workflow orchestration | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | LangGraph workflow orchestration | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | LangGraph workflow orchestration | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |
## `rule_evaluations`

**Category:** Transaction Detail
**Purpose:** Persisted deterministic validation/business-rule evaluation result.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| rule_evaluation_id | nvarchar(64) | NO | PK | — | Immutable evaluation identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| trace_id | nvarchar(64) | NO | FK | — | Workflow run in which evaluation occurred. | workflow_runs.trace_id | Must reference an active/valid parent record when populated. References workflow_runs.trace_id. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 | References workflow_runs.trace_id. |
| case_id | nvarchar(64) | NO | FK | — | Case evaluated. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| requirement_rule_id | nvarchar(64) | YES | FK | NULL | Configured rule that was evaluated, if applicable. | requirement_rules.requirement_rule_id | Must reference an active/valid parent record when populated. References requirement_rules.requirement_rule_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References requirement_rules.requirement_rule_id. |
| evaluation_type_code | nvarchar(64) | NO | BUSINESS | — | Evaluation family, e.g. COMPLETENESS or EVIDENCE_CONSISTENCY. |  | Required for a valid row. | Deterministic rule engine | None | SYN_CODE | Phase 1 | Application-controlled in Phase 1. |
| result_code | nvarchar(64) | NO | FK | — | Evaluation result. | result_codes.result_code | Must reference an active/valid parent record when populated. References result_codes.result_code. | Deterministic rule engine | None | SUCCESS | Phase 1 | References result_codes.result_code. |
| passed | bit | NO | BUSINESS | — | Whether the deterministic check passed. |  | Required for a valid row. | Deterministic rule engine | None | 0 | Phase 1 |  |
| reason_code | nvarchar(64) | YES | FK | NULL | Controlled reason for a significant failure/routing result. | reasons.reason_code | One deterministic check/evaluation row stores at most one reason_code; multiple mismatches create multiple evaluation rows. | Deterministic rule engine | None | EVIDENCE_MISMATCH_SERVICE_CODE | Phase 1 | References reasons.reason_code. |
| source_component_code | nvarchar(64) | NO | FK | — | Component performing the evaluation. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | Deterministic rule engine | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| evaluated_at_utc | datetime2(3) | NO | BUSINESS | — | Evaluation timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Small structured result metadata, such as missing_document_count. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Deterministic rule engine | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No raw clinical text. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Deterministic rule engine | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Deterministic rule engine | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Deterministic rule engine | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `integration_executions`

**Category:** Transaction Detail
**Purpose:** Technical record of a healthcare/FHIR-style external integration execution without storing raw payloads.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| integration_execution_id | nvarchar(64) | NO | PK | — | Immutable integration execution identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| trace_id | nvarchar(64) | NO | FK | — | Workflow run. | workflow_runs.trace_id | Must reference an active/valid parent record when populated. References workflow_runs.trace_id. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 | References workflow_runs.trace_id. |
| case_id | nvarchar(64) | NO | FK | — | Case. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| source_component_code | nvarchar(64) | NO | FK | — | Adapter/client component making the call. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | FHIR-style integration adapter | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| operation_code | nvarchar(64) | NO | BUSINESS | — | Controlled operation name, e.g. FETCH_CASE_EVIDENCE. |  | Required for a valid row. | FHIR-style integration adapter | None | SYN_CODE | Phase 1 | Application/config controlled in Phase 1. |
| target_system_code | nvarchar(64) | NO | BUSINESS | — | Non-secret logical target system identifier. |  | Required for a valid row. | FHIR-style integration adapter | None | SYN_CODE | Phase 1 | External System Master deferred until multiple production integrations exist. |
| http_status_code | smallint | YES | TECHNICAL | NULL | HTTP status if applicable. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | FHIR-style integration adapter | None | SYN_CODE | Phase 1 |  |
| result_code | nvarchar(64) | NO | FK | — | Execution result. | result_codes.result_code | Must reference an active/valid parent record when populated. References result_codes.result_code. | FHIR-style integration adapter | None | SUCCESS | Phase 1 | References result_codes.result_code. |
| failure_category_code | nvarchar(64) | YES | FK | NULL | Failure category. | failure_categories.failure_category_code | Must reference an active/valid parent record when populated. References failure_categories.failure_category_code. | FHIR-style integration adapter | None | AI_OUTPUT_INVALID | Phase 1 | References failure_categories.failure_category_code. |
| started_at_utc | datetime2(3) | NO | TECHNICAL | — | Call start timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| completed_at_utc | datetime2(3) | YES | TECHNICAL | NULL | Call completion timestamp. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| duration_ms | int | YES | TECHNICAL | NULL | Elapsed milliseconds. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | FHIR-style integration adapter | None | 125 | Phase 1 |  |
| retry_count | smallint | NO | TECHNICAL | 0 | Number of retries used by this execution. |  | Required for a valid row. | FHIR-style integration adapter | None | 1 | Phase 1 | Expected 0 unless explicitly designed. |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Safe technical metadata, counts, resource types. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | FHIR-style integration adapter | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | Never raw request/response payloads, secrets, or PHI. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | FHIR-style integration adapter | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | FHIR-style integration adapter | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | FHIR-style integration adapter | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `ai_analysis_runs`

**Category:** Transaction Header/Detail
**Purpose:** Validated AI-analysis execution metadata and structured synthetic output.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| ai_analysis_id | nvarchar(64) | NO | PK | — | Immutable AI-analysis identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| trace_id | nvarchar(64) | NO | FK | — | Workflow run. | workflow_runs.trace_id | Must reference an active/valid parent record when populated. References workflow_runs.trace_id. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 | References workflow_runs.trace_id. |
| case_id | nvarchar(64) | NO | FK | — | Case. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| source_component_code | nvarchar(64) | NO | FK | — | AI adapter/service component. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | AI analysis service after structured-output validation | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| model_reference | nvarchar(128) | YES | TECHNICAL | NULL | Non-secret model family/deployment alias. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | AI analysis service after structured-output validation | None | Synthetic value | Phase 1 | Never API key, endpoint, or secret configuration. |
| result_code | nvarchar(64) | NO | FK | — | AI execution result. | result_codes.result_code | Must reference an active/valid parent record when populated. References result_codes.result_code. | AI analysis service after structured-output validation | None | SUCCESS | Phase 1 | References result_codes.result_code. |
| failure_category_code | nvarchar(64) | YES | FK | NULL | Failure category if AI processing failed. | failure_categories.failure_category_code | Must reference an active/valid parent record when populated. References failure_categories.failure_category_code. | AI analysis service after structured-output validation | None | AI_OUTPUT_INVALID | Phase 1 | References failure_categories.failure_category_code. |
| output_validated | bit | NO | TECHNICAL | 0 | Whether structured output passed application validation. |  | Required for a valid row. | AI analysis service after structured-output validation | None | 0 | Phase 1 |  |
| validated_output_json | nvarchar(max) | YES | BUSINESS | NULL | Validated structured AI result for synthetic Phase 1 cases. |  | Persist only Pydantic-validated structured output; synthetic data only; no raw prompt/response. | AI analysis service after structured-output validation | Sensitive if real; synthetic-only in Phase 1 | {"summary":"Synthetic summary","ambiguities":[]} | Phase 1 | Synthetic only. Production requires protected clinical data storage/retention/access controls. |
| started_at_utc | datetime2(3) | NO | TECHNICAL | — | AI call start timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| completed_at_utc | datetime2(3) | YES | TECHNICAL | NULL | AI call completion timestamp. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| duration_ms | int | YES | TECHNICAL | NULL | Elapsed milliseconds. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | AI analysis service after structured-output validation | None | 125 | Phase 1 |  |
| schema_version | nvarchar(32) | NO | TECHNICAL | 1 | Structured-output schema version. |  | Required for a valid row. | AI analysis service after structured-output validation | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Safe AI metadata such as requested_task_count. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | AI analysis service after structured-output validation | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No raw prompt/raw response/secrets. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | AI analysis service after structured-output validation | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | AI analysis service after structured-output validation | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | AI analysis service after structured-output validation | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `ai_analysis_tasks`

**Category:** Transaction Detail
**Purpose:** One requested/completed AI task within an AI analysis run.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| ai_analysis_task_id | nvarchar(64) | NO | PK | — | Immutable AI-task-row identifier. |  | Required for a valid row. | Application-generated identifier | None | synthetic_id | Phase 1 |  |
| ai_analysis_id | nvarchar(64) | NO | FK | — | Parent AI analysis. | ai_analysis_runs.ai_analysis_id | Must reference an active/valid parent record when populated. References ai_analysis_runs.ai_analysis_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References ai_analysis_runs.ai_analysis_id. |
| ai_task_type_code | nvarchar(64) | NO | FK | — | Requested AI task. | ai_task_types.ai_task_type_code | Must reference an active/valid parent record when populated. References ai_task_types.ai_task_type_code. | AI analysis service after structured-output validation | None | IDENTIFY_AMBIGUITY | Phase 1 | References ai_task_types.ai_task_type_code. |
| was_requested | bit | NO | BUSINESS | 1 | Whether task was requested. |  | Required for a valid row. | AI analysis service after structured-output validation | None | 0 | Phase 1 |  |
| was_completed | bit | NO | BUSINESS | 0 | Whether validated provider output completed the task. |  | Required for a valid row. | AI analysis service after structured-output validation | None | 0 | Phase 1 |  |
| result_code | nvarchar(64) | YES | FK | NULL | Task-level result. | result_codes.result_code | Must reference an active/valid parent record when populated. References result_codes.result_code. | AI analysis service after structured-output validation | None | SUCCESS | Phase 1 | References result_codes.result_code. |
| sequence_no | int | NO | BUSINESS | 1 | Task order. |  | Required for a valid row. | AI analysis service after structured-output validation | None | Synthetic value | Phase 1 |  |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | AI analysis service after structured-output validation | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | AI analysis service after structured-output validation | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | AI analysis service after structured-output validation | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |

## `human_reviews`

**Category:** Transaction Header/Detail
**Purpose:** Human-in-the-loop review task and outcome. AI never writes a clinical approval/denial decision.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| review_id | nvarchar(64) | NO | PK | — | Immutable human-review identifier. |  | Required for a valid row. | Application-generated identifier | None | review_550e8400-e29b-41d4-a716-446655440003 | Phase 1 |  |
| trace_id | nvarchar(64) | NO | FK | — | Workflow run requiring review. | workflow_runs.trace_id | Must reference an active/valid parent record when populated. References workflow_runs.trace_id. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 | References workflow_runs.trace_id. |
| case_id | nvarchar(64) | NO | FK | — | Case. | prior_authorization_cases.case_id | Must reference an active/valid parent record when populated. References prior_authorization_cases.case_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| review_status_code | nvarchar(64) | NO | FK | REQUESTED | Review lifecycle status. | human_review_statuses.review_status_code | Must reference an active/valid parent record when populated. References human_review_statuses.review_status_code. | Human reviewer / Streamlit review UI | None | REQUESTED | Phase 1 | References human_review_statuses.review_status_code. |
| review_outcome_code | nvarchar(64) | YES | FK | NULL | Human review outcome. | human_review_outcomes.review_outcome_code | NULL until review is complete; required when review_status_code='COMPLETED'. | Human reviewer / Streamlit review UI | None | CONTINUE_WORKFLOW | Phase 1 | References human_review_outcomes.review_outcome_code. |
| reason_code | nvarchar(64) | NO | FK | — | Why review is required. | reasons.reason_code | Must reference an active/valid parent record when populated. References reasons.reason_code with HUMAN_REVIEW domain. | Human reviewer / Streamlit review UI | None | EVIDENCE_MISMATCH_SERVICE_CODE | Phase 1 | References reasons.reason_code with HUMAN_REVIEW domain. |
| assigned_department_id | nvarchar(64) | YES | FK | NULL | Department responsible for review. | departments.department_id | Must reference an active/valid parent record when populated. References departments.department_id. | Human reviewer / Streamlit review UI | None | synthetic_id | Phase 1 | References departments.department_id. |
| assigned_location_id | nvarchar(64) | YES | FK | NULL | Location responsible for review. | locations.location_id | Must reference an active/valid parent record when populated. References locations.location_id. | Human reviewer / Streamlit review UI | Potentially sensitive if real; synthetic-only in Phase 1 | synthetic_id | Phase 1 | References locations.location_id. |
| requested_at_utc | datetime2(3) | NO | BUSINESS | — | Review request timestamp. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| started_at_utc | datetime2(3) | YES | BUSINESS | NULL | Human review start timestamp. |  | NULL until a reviewer starts/accepts the task. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| completed_at_utc | datetime2(3) | YES | BUSINESS | NULL | Human review completion timestamp. |  | NULL until review is complete; required when review_status_code='COMPLETED'. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 |  |
| reviewer_actor_type_code | nvarchar(64) | YES | FK | NULL | Reviewer actor type. | actor_types.actor_type_code | NULL until a reviewer starts/accepts the task. | Human reviewer / Streamlit review UI | None | SYN_CODE | Phase 1 | Normally HUMAN_REVIEWER. |
| reviewer_reference | nvarchar(128) | YES | BUSINESS | NULL | Synthetic reviewer reference; future authenticated user ID. |  | NULL until a reviewer starts/accepts the task. | Application actor context; synthetic reference in Phase 1 | Sensitive if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | No real person identifiers in Phase 1. |
| review_note_text | nvarchar(2000) | YES | BUSINESS | NULL | Synthetic review note. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Human reviewer / Streamlit review UI | Sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Phase 1 synthetic only; production would require protected data controls. |
| source_component_code | nvarchar(64) | NO | FK | — | Component through which review is recorded. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | Human reviewer / Streamlit review UI | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Small controlled review metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Human reviewer / Streamlit review UI | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | No PHI/PII except synthetic. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC creation timestamp. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required on insert; immutable after creation. |
| created_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that created the row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Phase 1 uses synthetic/system identifiers; production may use authenticated actor IDs. |
| updated_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp of the most recent update. |  | Required; initialize to created_at_utc and update on every mutable business change. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Updated whenever a mutable business field changes. |
| updated_by | nvarchar(128) | NO | CONTROL | — | User, system, or component that most recently updated the row. |  | Required; initialize to created_by and update on every mutable business change. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Must identify the actor/component responsible for the change. |
| is_deleted | bit | NO | CONTROL | 0 | Logical-delete flag. 0=active record, 1=logically deleted. |  | Required. Default 0. Business closure does not set this flag. | Human reviewer / Streamlit review UI | None | 0 | Phase 1 | Business closure does not set this flag. |
| deleted_at_utc | datetime2(3) | YES | CONTROL | NULL | UTC logical-delete timestamp. |  | NULL while is_deleted=0; required when is_deleted=1. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Required when is_deleted=1. |
| deleted_by | nvarchar(128) | YES | CONTROL | NULL | User, system, or component that logically deleted the row. |  | NULL while is_deleted=0; required when is_deleted=1. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Required when is_deleted=1. |
| delete_reason_code | nvarchar(64) | YES | FK/CONTROL | NULL | Controlled logical-delete reason. | reasons.reason_code | NULL while is_deleted=0; required when is_deleted=1. | Human reviewer / Streamlit review UI | None | SYN_CODE | Phase 1 | References reasons.reason_code; for reasons table itself this is application-validated to avoid a self-FK dependency. |
| delete_reason_text | nvarchar(1000) | YES | CONTROL | NULL | Optional explanation supplementing delete_reason_code. |  | NULL allowed; supplemental explanation only. Never store PHI/PII/secrets. | Human reviewer / Streamlit review UI | Potentially sensitive if real; synthetic-only in Phase 1 | Synthetic example | Phase 1 | Do not place PHI/PII or secrets here. |
## `audit_events`

**Category:** Append-only Audit History
**Purpose:** Immutable, append-only audit record of significant events. Corrections are new events, never updates/deletes.
**Table note:** No updated_at_utc, updated_by, is_deleted, deleted_at_utc, deleted_by, or delete reason fields. Append-only by design.

| field_name | sql_type | null_allowed | attribute | default | description | fk_reference | business_rule | source | sensitivity | example_value | phase | notes |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| event_id | nvarchar(64) | NO | PK | — | Immutable audit event identifier. |  | Required for a valid row. | Application-generated identifier | None | evt_550e8400-e29b-41d4-a716-446655440002 | Phase 1 |  |
| trace_id | nvarchar(64) | NO | FK | — | Workflow run. | workflow_runs.trace_id | Must reference an active/valid parent record when populated. References workflow_runs.trace_id. | Application-generated identifier | None | trace_550e8400-e29b-41d4-a716-446655440001 | Phase 1 | References workflow_runs.trace_id. |
| case_id | nvarchar(64) | NO | FK | — | Case. | prior_authorization_cases.case_id | Intentional denormalization; must match workflow_runs.case_id for the same trace_id. | Application-generated identifier | None | case_550e8400-e29b-41d4-a716-446655440000 | Phase 1 | References prior_authorization_cases.case_id. |
| event_type_code | nvarchar(64) | NO | FK | — | What happened. | event_types.event_type_code | Must reference an active/valid parent record when populated. References event_types.event_type_code. | Audit service / workflow event emission | None | COMPLETENESS_CHECKED | Phase 1 | References event_types.event_type_code. |
| event_category_code | nvarchar(64) | NO | FK | — | High-level event category. | event_categories.event_category_code | Intentional denormalization; must match event_types.event_category_code for the event_type_code. | Audit service / workflow event emission | None | RULE | Phase 1 | References event_categories.event_category_code. Stored for efficient audit filtering; validated against event type. |
| workflow_status_code | nvarchar(64) | YES | FK | NULL | Workflow status at event time. | workflow_statuses.workflow_status_code | Must reference an active/valid parent record when populated. References workflow_statuses.workflow_status_code. | Audit service / workflow event emission | None | PROCESSING | Phase 1 | References workflow_statuses.workflow_status_code. |
| workflow_step_id | nvarchar(64) | YES | FK | NULL | Version-specific workflow step, if applicable. | workflow_definition_steps.workflow_step_id | Must reference an active/valid parent record when populated. References workflow_definition_steps.workflow_step_id. | Application-generated identifier | None | synthetic_id | Phase 1 | References workflow_definition_steps.workflow_step_id. |
| source_component_code | nvarchar(64) | NO | FK | — | Where the event occurred. | source_components.source_component_code | Must reference an active/valid parent record when populated. References source_components.source_component_code. | Audit service / workflow event emission | None | LANGGRAPH | Phase 1 | References source_components.source_component_code. |
| actor_type_code | nvarchar(64) | NO | FK | — | Type of actor responsible. | actor_types.actor_type_code | Must reference an active/valid parent record when populated. References actor_types.actor_type_code. | Audit service / workflow event emission | None | SYSTEM | Phase 1 | References actor_types.actor_type_code. |
| actor_identifier | nvarchar(128) | YES | BUSINESS | NULL | Synthetic actor or future authenticated actor reference. |  | Optional; NULL represents not applicable, not yet known, or not yet reached in the lifecycle. | Application actor context; synthetic reference in Phase 1 | Sensitive if real; synthetic-only in Phase 1 | Synthetic value | Phase 1 | Do not store real identities in Phase 1. |
| result_code | nvarchar(64) | NO | FK | — | Outcome of the event. | result_codes.result_code | Must reference an active/valid parent record when populated. References result_codes.result_code. | Audit service / workflow event emission | None | SUCCESS | Phase 1 | References result_codes.result_code. |
| failure_category_code | nvarchar(64) | YES | FK | NULL | Failure category if event represents a failure. | failure_categories.failure_category_code | Must reference an active/valid parent record when populated. References failure_categories.failure_category_code. | Audit service / workflow event emission | None | AI_OUTPUT_INVALID | Phase 1 | References failure_categories.failure_category_code. |
| reason_code | nvarchar(64) | YES | FK | NULL | Business/technical reason when relevant. | reasons.reason_code | Must reference an active/valid parent record when populated. References reasons.reason_code. | Audit service / workflow event emission | None | EVIDENCE_MISMATCH_SERVICE_CODE | Phase 1 | References reasons.reason_code. |
| related_event_id | nvarchar(64) | YES | FK | NULL | Original/related event for correction or causal linkage. |  | NULL normally; populate when this event corrects or directly relates to a prior immutable audit event. | Audit service / workflow event emission | None | synthetic_id | Phase 1 | Self-reference; preserves immutable correction chains. |
| occurred_at_utc | datetime2(3) | NO | BUSINESS | — | When the event actually occurred. |  | Required for a valid row. | Application / workflow clock (UTC) | None | 2026-09-16T22:01:15.000Z | Phase 1 |  |
| schema_version | nvarchar(32) | NO | TECHNICAL | 1 | Audit-event schema version. |  | Required for a valid row. | Audit service / workflow event emission | None | 1 | Phase 1 |  |
| metadata_json | nvarchar(max) | YES | EXTENSION | NULL | Small structured event metadata. |  | Optional controlled extension only; keys must be allowlisted. No relational keys, statuses, PHI/PII, secrets, raw FHIR, or raw LLM content. | Audit service / workflow event emission | Potentially sensitive if real; synthetic-only in Phase 1 | {"missing_document_count": 1} | Phase 1 | Never raw clinical notes, FHIR payloads, prompts/responses, credentials, or secrets. |
| created_at_utc | datetime2(3) | NO | CONTROL | CURRENT_UTC | UTC timestamp when the audit row was persisted. |  | Required on INSERT; immutable after creation. | Application / workflow clock (UTC) | None | 2026-09-16T22:00:00.000Z | Phase 1 | Append-only. |
| created_by | nvarchar(128) | NO | CONTROL | — | Actor/component that persisted the audit row. |  | Required on INSERT; Phase 1 uses synthetic/system actor identifiers. | Application actor context; synthetic reference in Phase 1 | None | Synthetic value | Phase 1 | Append-only; not updated later. |

## Appendix A — Mandatory control-field compliance

| table_name | all_9_present | missing_fields |
|---|---:|---|
| `clients` | YES | — |
| `departments` | YES | — |
| `countries` | YES | — |
| `locations` | YES | — |
| `case_statuses` | YES | — |
| `reasons` | YES | — |
| `workflow_definitions` | YES | — |
| `workflow_definition_steps` | YES | — |
| `workflow_statuses` | YES | — |
| `workflow_actions` | YES | — |
| `requirement_types` | YES | — |
| `requirement_sets` | YES | — |
| `document_types` | YES | — |
| `event_categories` | YES | — |
| `event_types` | YES | — |
| `actor_types` | YES | — |
| `source_components` | YES | — |
| `result_codes` | YES | — |
| `failure_categories` | YES | — |
| `human_review_statuses` | YES | — |
| `human_review_outcomes` | YES | — |
| `discovery_item_types` | YES | — |
| `ai_task_types` | YES | — |
| `client_requirement_intakes` | YES | — |
| `client_requirement_items` | YES | — |
| `requirement_rules` | YES | — |
| `prior_authorization_cases` | YES | — |
| `case_diagnoses` | YES | — |
| `case_documents` | YES | — |
| `workflow_runs` | YES | — |
| `rule_evaluations` | YES | — |
| `integration_executions` | YES | — |
| `ai_analysis_runs` | YES | — |
| `ai_analysis_tasks` | YES | — |
| `human_reviews` | YES | — |

`audit_events` is intentionally excluded because it is append-only/immutable.

## Related documentation

- [data_model.md](data_model.md) — canonical data model and normalization rationale
- [reference_data.md](reference_data.md) — proposed controlled seed/reference-data catalog
- [constraints_and_indexes.md](constraints_and_indexes.md) — relational integrity, uniqueness, CHECK constraint, and index catalog
- [../decisions/ADR-004-phase1-canonical-data-model.md](../decisions/ADR-004-phase1-canonical-data-model.md) — the architecture decision record for this model
