"""eval-backend-validation_v1: claimed-vs-observed evidence for the D-0 eval-backend decision.

Probes emit raw observables; the human-signed rubric (RUBRIC.md) maps observables to marks.
This package never judges, never selects a platform, and never writes outside its own subtree.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Marks are defined ONCE, as escapes: the repo-wide ruff config selects RUF001-003
# (ambiguous-unicode), so the glyphs may appear literally only in YAML/Markdown.
MARK_FULL = "●"  # filled circle
MARK_PARTIAL = "◐"  # half circle
MARK_ABSENT = "—"  # em dash
MARK_HUMAN = "HUMAN"  # rubric could not resolve; routed to the human queue
CLAIM_TBD = "CLAIM_TBD"  # claimed mark not yet transcribed from the external matrix

VALID_MARKS = (MARK_FULL, MARK_PARTIAL, MARK_ABSENT)
VALID_CLAIMS = (*VALID_MARKS, CLAIM_TBD)
