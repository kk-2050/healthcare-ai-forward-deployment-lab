# File Name: fhir_models.py
# Purpose: Defines the small FHIR-style resource models and the normalized evidence output for Phase 1.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# =====================================================================
# FHIR-STYLE RESOURCE MODELS
# Purpose:
# Defines a deliberately small subset of FHIR-shaped resources:
# ServiceRequest, Condition, DocumentReference, and the Bundle that
# carries them.
#
# Why:
# The FDE role requires REST/JSON integration with healthcare-shaped
# data. Modeling a small, explainable subset — rather than the full
# HL7 FHIR specification — keeps the integration boundary testable and
# easy to reason about, while still using recognizable FHIR field
# names (resourceType, status, intent, code, reasonReference, content).
#
# Important Notes:
# - This is FHIR-style synthetic integration for the Phase 1 prototype,
#   NOT a full HL7 FHIR implementation and NOT conformance-tested
#   against the FHIR specification.
# - Only synthetic resource IDs are ever used here (e.g. "SYN-SR-001").
#   No patient name, date of birth, address, phone, email, insurance/
#   member number, or provider personal information is modeled — this
#   integration never needs that data to do its job.
# - `resourceType` uses Literal values as a Pydantic discriminator, so
#   an unrecognized resource type (e.g. "Patient") is rejected
#   automatically, before any extraction logic runs.
# =====================================================================


class FHIRReference(BaseModel):
    """A FHIR-style reference to another resource, e.g. "Condition/SYN-COND-001"."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reference: str = Field(min_length=1)


class FHIRCoding(BaseModel):
    """One coded value (a system/code/display triple), FHIR's usual
    building block for representing a clinical or service code."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    system: str | None = None
    code: str = Field(min_length=1)
    display: str | None = None


class FHIRCode(BaseModel):
    """A FHIR-style CodeableConcept: a list of possible codings for the
    same concept. This project deterministically uses the first
    coding — see fhir_client.py."""

    model_config = ConfigDict(extra="forbid")

    coding: list[FHIRCoding] = Field(default_factory=list)


class ServiceRequestResource(BaseModel):
    """The requested service/procedure for a prior authorization case,
    including which Condition(s) justify it via reasonReference."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resourceType: Literal["ServiceRequest"]
    id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    code: FHIRCode
    reasonReference: list[FHIRReference] = Field(default_factory=list)


class ConditionResource(BaseModel):
    """A diagnosis/condition resource, referenced by a ServiceRequest's
    reasonReference to justify the requested service."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resourceType: Literal["Condition"]
    id: str = Field(min_length=1)
    code: FHIRCode


class DocumentReferenceContent(BaseModel):
    """A minimal descriptor for one attached document — just enough to
    identify it (its title), never the document's actual content."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1)


class DocumentReferenceResource(BaseModel):
    """A supporting-document resource (e.g. a physical therapy
    summary), referenced by title only — this project never models or
    transmits the document's actual contents."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resourceType: Literal["DocumentReference"]
    id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    content: list[DocumentReferenceContent] = Field(default_factory=list)


# Only these three resource types are ever accepted. The discriminator
# (resourceType) means an unsupported type is rejected by Pydantic with
# a clear "tag not recognized" error before any extraction code runs.
SupportedFHIRResource = Annotated[
    Union[ServiceRequestResource, ConditionResource, DocumentReferenceResource],
    Field(discriminator="resourceType"),
]


class FHIRBundleEntry(BaseModel):
    """One entry in a Bundle, wrapping exactly one supported resource."""

    model_config = ConfigDict(extra="forbid")

    resource: SupportedFHIRResource


class FHIRBundle(BaseModel):
    """
    A small FHIR-style Bundle: a flat list of ServiceRequest,
    Condition, and DocumentReference resources for one synthetic case.

    This is the top-level shape the healthcare-style endpoint returns.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resourceType: Literal["Bundle"]
    type: str = Field(min_length=1)
    entry: list[FHIRBundleEntry] = Field(default_factory=list)


# =====================================================================
# NORMALIZED CASE EVIDENCE
# Purpose:
# Defines the small set of deterministic facts extracted from a
# validated FHIR-style Bundle, in the shape the prior-authorization
# workflow actually needs.
#
# Why:
# Downstream code (deterministic rules, and later LangGraph) should
# never have to understand FHIR-style resource/reference structure.
# This model is the boundary: FHIR-shaped in, plain workflow facts out.
#
# Important Notes:
# This model contains facts only. It intentionally has no approval,
# denial, medical_necessity, payer_decision, or confidence field —
# those concerns belong to deterministic rules and human review, never
# to this integration boundary.
# =====================================================================


class FHIRCaseEvidence(BaseModel):
    """Deterministic facts extracted from a synthetic FHIR-style Bundle
    for one prior authorization case."""

    model_config = ConfigDict(extra="forbid")

    service_request_id: str
    requested_service_code: str
    diagnosis_codes: list[str] = Field(default_factory=list)
    supporting_documentation: list[str] = Field(default_factory=list)

    # Every resource ID that contributed to this evidence (the
    # ServiceRequest, each resolved Condition, each DocumentReference),
    # kept for traceability back to the source Bundle.
    source_resource_ids: list[str] = Field(default_factory=list)


class FHIRIntegrationFailureType(str, Enum):
    """
    The distinct, deterministic ways retrieving healthcare evidence can
    fail. Kept separate (rather than one generic "failed" flag) so a
    future human reviewer or routing rule can see exactly what went
    wrong.
    """

    HTTP_ERROR = "HTTP_ERROR"
    MALFORMED_JSON = "MALFORMED_JSON"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    UNSUPPORTED_RESOURCE_TYPE = "UNSUPPORTED_RESOURCE_TYPE"
    MISSING_SERVICE_REQUEST = "MISSING_SERVICE_REQUEST"
    BROKEN_CONDITION_REFERENCE = "BROKEN_CONDITION_REFERENCE"


class FHIRIntegrationOutcome(BaseModel):
    """
    The validated outcome of one attempt to retrieve FHIR-style case
    evidence.

    Mirrors the project's existing AIAnalysisOutcome pattern (see
    src/ai/contracts.py): success and evidence are populated only on
    success; failure_type and error_message are populated only on
    failure. evidence is never fabricated — on any failure it is
    always None.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    evidence: FHIRCaseEvidence | None = None
    failure_type: FHIRIntegrationFailureType | None = None

    # A short, generic message only — never raw HTTP response bodies,
    # exception text, or resource contents.
    error_message: str | None = None
