# File Name: base.py
# Purpose: Defines the SQLAlchemy declarative base and the prototype schema-creation helper.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The shared SQLAlchemy declarative base for every ORM table in this project."""


# =====================================================================
# PROTOTYPE SCHEMA CREATION
# Purpose:
# Creates every table declared against Base on the given engine.
#
# Why:
# Task 18A needs a simple, explicit way to stand up the schema for
# offline repository tests (an in-memory SQLite engine).
#
# Important Notes:
# - Prototype schema creation only. Production migration tooling (e.g.
#   Alembic) is planned, not implemented here.
# - Do not call this against a real Microsoft SQL Server in Task 18A --
#   Task 18B is the first task allowed to touch a live SQL Server.
# - This function performs no data migration and no rollback plan; it
#   is create-only, matching a fresh prototype database.
# =====================================================================
def create_database_schema(engine: Engine) -> None:
    """Creates all tables declared against Base on the given engine."""
    Base.metadata.create_all(engine)
