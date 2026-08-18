"""Compose the dispatch prompt(s) for an implementation review.

Two shapes, chosen by :mod:`implreview.detect`'s recommendation:

- **Plugin path** — two short prompts, one per charter (``spec-guardian`` then
  ``peer-reviewer``), because the method already lives in each charter's own frontmatter/body
  (``claude-foundation/agents/spec-guardian.md`` / ``peer-reviewer.md``); the prompt only needs
  to name the target.
- **Degraded path** — one prompt for a ``general-purpose`` subagent with the *entire* two-pass
  method inlined, since a generic subagent has no charter to fall back on. This is the path
  this repo's own sessions actually exercise today (``claude-foundation`` is staged, ADR 0028,
  not plugin-loaded here) — see ``docs/decisions/0028-claude-foundation-staging.md`` and
  ``openspec/AGENTS.md``'s staging precondition. It is written to be self-contained: a reader
  with only this prompt, no other context, can reproduce the method.

Both shapes target the same output contract (:mod:`implreview.validate`'s required shape),
which is itself the shape of the two real precedents this prompt cites:
``openspec/changes/harden-quality-gate-integrity/review.md`` and
``openspec/changes/test-skill-validator-library/review.md`` -- see ``implreview.validate``'s
own module docstring and ``add-openspec-implementation-review/design.md``'s "recalibrated
against real precedent" section for how those two, specifically, were chosen. (A third file,
``openspec/changes/add-panel-judge/review.md``, is a *different* genre -- a pre-implementation
plan review, not this shape -- and is cited elsewhere in this package only for its append,
not-overwrite pattern; see ``implreview.compose``'s module docstring.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .detect import DispatchPath

if TYPE_CHECKING:
    from .locate import ChangeLocation

#: Referenced from every prompt shape so a reader can go look at the real artifact this
#: skill's output is meant to resemble. Both this and ``SECOND_PRECEDENT_REVIEW`` name the
#: two real, already-merged review.md files ``implreview.validate``'s required shape was
#: actually calibrated against (see that module's docstring) -- NOT
#: ``add-panel-judge/review.md``, which is a different genre (a pre-implementation plan
#: review) and correctly fails ``validate_review_file`` (see
#: ``tests/test_validate.py::test_real_add_panel_judge_review_is_a_different_genre_and_correctly_does_not_validate``).
PRECEDENT_REVIEW = "openspec/changes/test-skill-validator-library/review.md"
SECOND_PRECEDENT_REVIEW = "openspec/changes/harden-quality-gate-integrity/review.md"

_OUTPUT_SHAPE = """\
Return your review as your final message text, in exactly this shape (matching {precedent}
and {precedent2}). Do NOT write, create, or edit {review_path} or any other file yourself --
the orchestrating agent captures your returned text and writes the file via this skill's own
`compose` step. A dispatched agent that writes the file directly, in addition to the
orchestrator's own compose step, produces duplicated content -- this is your one job to avoid:

  # Review: {change_id}

  **Reviewed:** <one paragraph: what tree/SHA you reviewed, in how many passes, and the
  house method you followed>

  ## Verdict

  **<APPROVE | APPROVE WITH FOLLOW-UPS | BLOCK>.** <one paragraph summary, stated first,
  before the detailed passes below -- this repo's convention is verdict-first reporting>

  ---

  ## Pass 1 -- mechanical fact-check ({date})

  Give every falsifiable claim in the change's proposal.md/design.md/tasks.md/spec.md exactly
  one verdict: CONFIRMED, CORRECTED (state the correction), or REFUTED (state why) -- each
  with a file:line citation as evidence. Do not accept a claim on the strength of the source
  document alone; re-derive it from the tree.

  ## Pass 2 -- adversarial ({date})

  Separately labeled and dated from Pass 1 even when run the same day (both real precedents
  above date same-day passes independently -- the label matters, not a calendar gap).
  Actively try to break the design or implementation: failure modes, edge cases, contract
  mismatches, silent-drift paths. Verify every attack against the real files before keeping
  it. An attack that dies under verification is RECORDED AS REFUTED, never deleted -- a
  reviewed-and-rejected risk is information the next reviewer needs.

  ## Residual risk

  Anything real but out of scope, low-severity, or a deliberate accepted trade-off.

  ## Overall verdict

  Restate the verdict from the top, plus any follow-ups (numbered, non-blocking) a later
  change should pick up.
"""

_TASK_PRELUDE = """\
You are reviewing OpenSpec change `{change_id}` at `{change_dir}`, tree SHA `{tree_sha}`.

Read, in order: `{change_dir}/proposal.md`, `{change_dir}/design.md`, `{change_dir}/tasks.md`,
and every file under `{change_dir}/specs/`. Then read the actual landed diff/files those
documents claim to describe -- not just the documents themselves.
"""


@dataclass(frozen=True)
class DispatchPrompt:
    """One subagent dispatch: which type, and the prompt text to send it."""

    subagent_type: str
    prompt: str


@dataclass(frozen=True)
class DispatchPlan:
    """The full set of dispatches the calling agent should perform, in order."""

    path: DispatchPath
    prompts: tuple[DispatchPrompt, ...]


def _review_path_str(change: ChangeLocation) -> str:
    # .as_posix(), not str(): prompt text must be deterministic across platforms
    # (AGENTS.md "Windows / cross-platform gotchas" -- str(Path) emits backslashes on
    # Windows, which would make the same change produce a different prompt per host).
    return change.review_path.as_posix()


def _change_dir_str(change: ChangeLocation) -> str:
    return change.change_dir.as_posix()


def build_spec_guardian_prompt(change: ChangeLocation, tree_sha: str) -> DispatchPrompt:
    """Prompt for the ``spec-guardian`` charter (plugin path, pass 1 of the review loop)."""
    prompt = (
        _TASK_PRELUDE.format(change_dir=_change_dir_str(change), change_id=change.change_id, tree_sha=tree_sha)
        + "\nApply your standard conformance-review procedure (see your own frontmatter/body) "
        "to this change: does the implementation still match what proposal.md/design.md/"
        "tasks.md/specs/ say it does? Report `Verdict: conforms` or `Verdict: drift` first, "
        "then numbered file:line findings, most consequential first. This is pass 1 of a "
        "two-stage review; a peer-reviewer dispatch follows with your findings as input."
    )
    return DispatchPrompt(subagent_type="spec-guardian", prompt=prompt)


def build_peer_reviewer_prompt(
    change: ChangeLocation, tree_sha: str, *, spec_guardian_findings: str = ""
) -> DispatchPrompt:
    """Prompt for the ``peer-reviewer`` charter (plugin path, pass 2 of the review loop)."""
    handoff = (
        f"\nspec-guardian's conformance findings, for context (do not simply repeat them; "
        f"verify independently):\n\n{spec_guardian_findings}\n"
        if spec_guardian_findings
        else ""
    )
    prompt = (
        _TASK_PRELUDE.format(change_dir=_change_dir_str(change), change_id=change.change_id, tree_sha=tree_sha)
        + handoff
        + "\nApply your standard two-pass procedure (see your own frontmatter/body): pass 1 "
        "mechanically fact-checks every falsifiable claim (CONFIRMED/CORRECTED/REFUTED with "
        "file:line evidence); pass 2, labeled separately, adversarially attacks the design or "
        "implementation, verifying each attack before keeping it and recording refuted "
        "attacks rather than deleting them.\n\n"
        + _OUTPUT_SHAPE.format(
            review_path=_review_path_str(change),
            precedent=PRECEDENT_REVIEW,
            precedent2=SECOND_PRECEDENT_REVIEW,
            change_id=change.change_id,
            date="<today's date, YYYY-MM-DD>",
        )
    )
    return DispatchPrompt(subagent_type="peer-reviewer", prompt=prompt)


def build_degraded_prompt(change: ChangeLocation, tree_sha: str) -> DispatchPrompt:
    """Self-contained prompt for a ``general-purpose`` subagent: the whole method, inlined.

    This is the path this repo's own sessions actually exercise (see module docstring), so it
    is written to need nothing beyond itself -- no charter to fall back on, no assumption the
    dispatched agent has read anything about this skill.
    """
    method = """\
You are acting as this repo's independent implementation reviewer for OpenSpec change
`{change_id}`. `claude-foundation`'s spec-guardian/peer-reviewer charters are not loaded in
this session (ADR 0028: claude-foundation is a staging directory, not an installed plugin
here), so you are performing their combined method directly, in character, rather than by
dispatching them.

Follow this two-pass method exactly -- it is this repo's own house convention for a review.md,
used for real in {precedent} and {precedent2}. Read both if you want worked examples of the
expected rigor before you start.

PASS 1 -- mechanical fact-check.
Pin the tree SHA you are reviewing (you were given `{tree_sha}`; confirm it with
`git rev-parse HEAD` if you have shell access, otherwise state you are trusting the given
value). Re-derive every falsifiable claim in the change's proposal.md/design.md/tasks.md and
every specs/*/spec.md scenario against the CURRENT tree -- read the file:line, run the
command, execute the config -- never accept a claim on the strength of the source document
alone. Give each claim exactly one verdict:
  - CONFIRMED -- the claim holds, cite the file:line that proves it.
  - CORRECTED -- the claim is close but wrong in a stated way; give the correction.
  - REFUTED -- the claim does not hold; state why, with evidence.

PASS 2 -- adversarial, labeled and dated separately from pass 1 (even if run the same day --
the separate label is what matters, both real precedents above date same-day passes this way).
Assume the design or implementation is wrong and try to prove it: failure modes, edge cases,
contract mismatches with the rest of the repo, silent-drift paths, anything pass 1's
claim-by-claim reading would not surface on its own. Verify every attack against the real
files or by actually running something -- never keep an attack you have only reasoned about
in the abstract. An attack that dies under verification is RECORDED AS REFUTED, with the
reasoning that refuted it, never deleted -- a reviewed-and-rejected risk is information the
next reviewer needs, exactly as both precedent reviews do.

Read only: do not write, create, or edit ANY file, including {review_path} itself. Return
your complete review as the text of your final message -- the orchestrating agent captures
it and writes the file via this skill's own `compose` step, exactly once.
"""
    prompt = method.format(
        change_id=change.change_id,
        tree_sha=tree_sha,
        precedent=PRECEDENT_REVIEW,
        precedent2=SECOND_PRECEDENT_REVIEW,
        review_path=_review_path_str(change),
    )
    prompt += "\n" + _TASK_PRELUDE.format(
        change_dir=_change_dir_str(change), change_id=change.change_id, tree_sha=tree_sha
    )
    prompt += "\n" + _OUTPUT_SHAPE.format(
        review_path=_review_path_str(change),
        precedent=PRECEDENT_REVIEW,
        precedent2=SECOND_PRECEDENT_REVIEW,
        change_id=change.change_id,
        date="<today's date, YYYY-MM-DD>",
    )
    return DispatchPrompt(subagent_type="general-purpose", prompt=prompt)


def build_dispatch_plan(change: ChangeLocation, tree_sha: str, path: DispatchPath) -> DispatchPlan:
    """The ordered dispatch(es) the calling agent should perform for *path*."""
    if path == "plugin":
        spec_guardian = build_spec_guardian_prompt(change, tree_sha)
        peer_reviewer = build_peer_reviewer_prompt(change, tree_sha)
        return DispatchPlan(path="plugin", prompts=(spec_guardian, peer_reviewer))
    return DispatchPlan(path="degraded", prompts=(build_degraded_prompt(change, tree_sha),))
