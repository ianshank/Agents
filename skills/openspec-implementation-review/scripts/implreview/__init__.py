"""implreview -- locate, detect, compose, and validate an OpenSpec implementation review.

Reviews the *shipped implementation* of an OpenSpec change against its own proposal/design/
tasks/spec, producing ``openspec/changes/<id>/review.md`` in the two-pass shape this repo's
own reviews already use (``openspec/changes/test-skill-validator-library/review.md``,
``openspec/changes/harden-quality-gate-integrity/review.md`` -- the two real precedents
``implreview.validate``'s required shape is actually calibrated against). Complementary to,
and never a replacement for, ``openspec-peer-review`` -- that skill reviews a *plan* before
implementation starts; this reviews the *result* afterward.
"""

from __future__ import annotations

from .compose import ComposeResult, compose_review, default_reviewed_line, render_followup_section, render_new_review
from .detect import DispatchDetection, DispatchPath, detect_dispatch_path
from .locate import ChangeLocation, ChangeNotFoundError, TaskStatus, list_change_ids, locate_change, parse_tasks_status
from .prompts import DispatchPlan, DispatchPrompt, build_dispatch_plan
from .validate import ReviewValidation, validate_review_file, validate_review_structure

__all__ = [
    "ChangeLocation",
    "ChangeNotFoundError",
    "ComposeResult",
    "DispatchDetection",
    "DispatchPath",
    "DispatchPlan",
    "DispatchPrompt",
    "ReviewValidation",
    "TaskStatus",
    "build_dispatch_plan",
    "compose_review",
    "default_reviewed_line",
    "detect_dispatch_path",
    "list_change_ids",
    "locate_change",
    "parse_tasks_status",
    "render_followup_section",
    "render_new_review",
    "validate_review_file",
    "validate_review_structure",
]
