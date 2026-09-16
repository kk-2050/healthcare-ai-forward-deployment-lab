# File Name: __init__.py
# Purpose: Marks src/db as the package containing SQLAlchemy persistence infrastructure (engine, schema, and repository).
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# This package holds the Phase 1 persistence boundary: the declarative
# ORM base and tables (base.py, models.py), the SQL Server engine
# factory (engine.py), and the repository that reads/writes workflow
# run snapshots and audit events (repository.py). It never contains
# workflow, rule, or AI logic -- only "how do we store and retrieve
# traceability data?".
