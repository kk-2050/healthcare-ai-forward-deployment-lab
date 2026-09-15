# File Name: __init__.py
# Purpose: Marks src/rules as the package containing Phase 1 deterministic business-rule functions.
# Creation Date: 2026-09-14
# Author: K.Kashiwagi
#
# Module Explanation:
# This package holds the deterministic-first business logic: checking
# whether a case has everything it needs (completeness.py) and deciding
# whether an approved AI task was requested (ai_routing.py). Nothing in
# this package calls an LLM or makes a clinical approval/denial decision.
