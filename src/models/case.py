# File Name: case.py
# Purpose: Defines the validated synthetic prior authorization case input model.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# PRIOR AUTHORIZATION CASE MODEL
# Purpose:
# Defines the shape of one synthetic prior authorization case and
# rejects malformed input before any other code runs.
#
# Why:
# The project is deterministic-first: nothing downstream (business
# rules, AI, LangGraph, the API) should ever see a case that is missing
# required fields, has the wrong data types, or contains fields nobody
# asked for. Checking this once, here, keeps every later step simpler.
#
# Important Notes:
# - This model only checks structure (are the right fields present and
#   well-formed?). It does not check completeness of documentation or
#   clinical notes — that is a separate, later step (see
#   src/rules/completeness.py).
# - This model does not decide medical necessity or approval/denial.
# - Only synthetic data should ever be used with this model.
# =====================================================================


class PriorAuthorizationCase(BaseModel):
    """
    A single synthetic prior authorization request.

    This is the project's core data record: one request for a service,
    tied to a synthetic patient/member and provider, with any
    supporting documentation and clinical notes attached.
    """

    # extra="forbid" rejects any field that is not listed below, so a
    # typo or an unexpected client field fails loudly instead of being
    # silently ignored.
    # str_strip_whitespace=True trims leading/trailing spaces from every
    # string field automatically, before the length checks below run.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Required identifiers. min_length=1 means an empty string (or a
    # string that becomes empty after whitespace stripping) is rejected.
    case_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    requested_service_code: str = Field(min_length=1)
    diagnosis_code: str = Field(min_length=1)
    requested_date: date

    # Optional/defaultable fields. default_factory=list gives each case
    # its own independent list, so appending documents to one case can
    # never accidentally affect another case (a classic Python mutable
    # default-argument bug this pattern avoids).
    supporting_documentation: list[str] = Field(default_factory=list)
    clinical_notes: str | None = None
