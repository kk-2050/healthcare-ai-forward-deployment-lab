<!--
File Name: ADR-003-sql-server.md
Purpose: Records the decision to use local Microsoft SQL Server for Phase 1 persistence.
Creation Date: 2026-09-13
Author: K.Kashiwagi
-->

# ADR-003: Microsoft SQL Server for Persistence

## Status
Accepted

## Context
The workflow needs durable storage for case data, workflow state, and
an audit trail of decisions and transitions. Healthcare enterprise
environments — and the FDE role this project is aligned with — commonly
standardize on Microsoft SQL Server rather than open-source databases
such as PostgreSQL. Demonstrating comfort with SQL Server and T-SQL is
part of the intended portfolio value of this project.

## Decision
Use **Microsoft SQL Server**, running locally, as the persistence layer
for Phase 1. This includes:

- Case/request data
- Workflow state
- Audit log of workflow transitions and decisions

This decision has been reviewed and is fixed for Phase 1. SQL Server
will not be swapped for PostgreSQL or another database engine during
this phase.

## Consequences
- Requires a local SQL Server instance for development.
- Database access will use parameterized queries/ORM patterns to avoid
  SQL injection risk once implementation begins.
- Connection details are supplied via environment variables only (see
  `.env.example`) and are never hard-coded.

## Related
- [[../architecture.md]]
- [[../security.md]]
