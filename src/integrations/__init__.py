# File Name: __init__.py
# Purpose: Marks src/integrations as the package containing Phase 1 external healthcare/FHIR-style integration adapters.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# This package holds integration code for talking to (synthetic)
# external healthcare systems. Today it contains only a FHIR-style
# adapter (fhir_client.py, fhir_models.py) that reads a small,
# synthetic Bundle over HTTP. It never calls a real healthcare system,
# payer, EHR, or public FHIR server.
