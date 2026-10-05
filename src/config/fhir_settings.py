# File Name: fhir_settings.py
# Purpose: Defines and loads the validated FHIR_MODE runtime-mode configuration that controls which FHIR-style client get_fhir_client() may construct.
# Creation Date: 2026-10-02
# Author: K.Kashiwagi
#
# Module Explanation:
# This project has no approved, authenticated live FHIR integration
# contract yet (see src/api/dependencies.py's get_fhir_client()).
# FHIR_MODE is the one explicit setting that controls what, if
# anything, that dependency is allowed to construct:
#
#   disabled  (default)  -- fail closed; no FHIR client is built.
#   synthetic (opt-in)    -- a local, zero-network, synthetic-only
#                            FHIRStyleClient is built (Task 25C).
#   live      (not built) -- explicitly NOT IMPLEMENTED; fails closed
#                            exactly like disabled, never a live client.
#
# WHY disabled IS THE DEFAULT:
# Per the Universal Least-Privilege Escalation Boundary (docs/security.md
# Section 7 / CLAUDE.md: "Not explicitly allowed = DENY"), an
# integration must never be used merely because its absence was not
# forbidden. A developer who has not set FHIR_MODE at all, or left it
# blank, has not explicitly asked for anything -- deny by default.
#
# WHY live FAILS CLOSED HERE TOO:
# "live" names the future, not-yet-built mode so the contract is
# forward-documented, but this project has no authenticated production
# FHIR integration to construct. Recognizing the word "live" and then
# failing closed anyway is deliberate: it is never silently treated as
# "synthetic" or "disabled" by accident, and no live/unauthenticated
# client is ever constructed.
#
# WHY AN UNRECOGNIZED VALUE IS A HARD ERROR, NOT A SILENT DEFAULT:
# A typo (e.g. "synthetc") must never be silently treated as
# "disabled" (which would hide a configuration mistake) or as
# "synthetic" (which would be worse -- silently granting a capability
# nobody asked for correctly). Pydantic validation rejects it outright
# here; get_fhir_client() turns that rejection into the same safe,
# fail-closed behavior "disabled" already has (see that function's own
# docstring) -- never a different, less safe outcome.
#
# WHAT THIS FILE DELIBERATELY DOES NOT CONTAIN:
# No FHIR base URL, API key, token, username/password, or OAuth/SMART
# configuration of any kind. This setting controls ONLY which
# construction path get_fhir_client() takes -- it is not where a future
# live integration's credentials would ever be read from.

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

FHIRMode = Literal["disabled", "synthetic", "live"]


class FHIRRuntimeSettings(BaseModel):
    """Validated FHIR_MODE runtime-mode configuration. See this module's
    docstring above for exactly what each of the three allowed modes
    does and why "disabled" is the default."""

    model_config = ConfigDict(extra="forbid")

    mode: FHIRMode = "disabled"

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        """Strips whitespace and lower-cases a raw string value before
        it is checked against the three recognized modes below --
        " Synthetic " and "SYNTHETIC" are both accepted as the same
        mode, but any word other than the three recognized ones is
        rejected (never silently coerced to a default)."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or "disabled"
        return value


# =====================================================================
# ENVIRONMENT LOADER
# Purpose:
# Reads FHIR_MODE from an environment-like mapping and validates it
# into FHIRRuntimeSettings.
#
# Why no automatic .env loading:
# Same policy as load_azure_openai_settings()/load_database_settings()
# (src/config/settings.py, src/config/database.py): this function reads
# from plain environment variables (or an injected mapping in tests)
# and never calls a .env-loading library itself, so it behaves the
# same in a local shell, CI/CD, a container, or a future secret
# manager. Loading a local .env file remains the caller's explicit
# responsibility (see src/api/dependencies.py's get_fhir_client()).
# =====================================================================
def load_fhir_runtime_settings(
    env: Mapping[str, str] | None = None,
) -> FHIRRuntimeSettings:
    """
    Loads and validates FHIR runtime-mode settings from an
    environment-like source.

    If `env` is not supplied, reads from the real process environment
    (os.environ). Tests should always supply an explicit `env` mapping
    instead, so tests stay isolated and repeatable and never depend on
    a developer's local .env file.

    FHIR_MODE absent or blank resolves to "disabled" -- the safe
    default. Raises a Pydantic ValidationError if FHIR_MODE is set to
    anything other than "disabled", "synthetic", or "live" (whitespace/
    case-insensitive) -- never silently treated as a default or as
    "synthetic".
    """
    source = os.environ if env is None else env
    raw_value = source.get("FHIR_MODE", "")

    return FHIRRuntimeSettings(mode=raw_value)


__all__ = ["FHIRMode", "FHIRRuntimeSettings", "load_fhir_runtime_settings"]
