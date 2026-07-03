"""Validation, scanning, and eval-gate tooling for the foundation plugin.

Modules:
    schemas   — pinned, doc-derived Pydantic models for manifests and frontmatter
    frontmatter — YAML frontmatter extraction shared by validator and scanner
    validate  — walks the plugin tree and validates every component
    scan      — no-hardcode scanner (model IDs, absolute paths, secrets)
    eval_gate — release gate over skill-creator grading.json results
    jsonlog   — stdlib JSONL structured logging (shared with hooks conventions)
"""

from __future__ import annotations

__version__ = "1.0.0"
