# File Name: __init__.py
# Purpose: Marks src/config as the package containing Phase 1 configuration models and loaders.
# Creation Date: 2026-09-15
# Author: K.Kashiwagi
#
# Module Explanation:
# This package holds configuration concerns that must stay separate
# from business logic: reading environment variables and validating
# them into a typed settings object (settings.py). It never contains
# workflow, rule, or AI logic — only "what values does this project
# need to run, and are they valid?".
