---
name: common
tier: none
description: Shared utilities and validators used by all skills
---

# Common Skill Utilities

This is not a skill itself, but a shared library directory containing utilities and validators used by all skills in the marketplace.

## Contents

- `skill_validator.py`: Shared skill validation logic used by all 11 skills to validate their structure and behavior.
- `__init__.py`: Module exports for the shared validator.

## Usage

This directory is referenced by all skill validation scripts as a common source of truth for validation logic, reducing code duplication across 11 skill implementations.
