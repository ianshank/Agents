"""Portability regression test for the reviewer charters.

`claude-foundation/` is a portable plugin staging area (ADR 0028): everything under
`agents/` is meant to work unmodified in any consumer repo, not just this one
(`README.md`: "the single-source-of-truth alternative to copy-pasting agent config
across repos"). Two existing gates almost cover that property but not quite:

- `foundation_tools.validate` (`check_agents`) parses only the YAML frontmatter of
  each `agents/*.md` file — it never reads the Markdown body, where a charter's actual
  rules live.
- `foundation_tools.scan` catches *absolute* hardcoded paths, but its `absolute-path`
  rule is anchored to filesystem roots (`/home`, `/Users`, `/root`, ...); it says
  nothing about a *repo-relative* literal such as `features.yaml` or `agent-core` used
  as an unconditional fact in prose.

`spec-guardian` and `peer-reviewer` are the two charters most exposed to this risk:
their entire job is comparing a change against "this repo's own conventions"
(`design.md`, "Why portability is the central design problem"), which is exactly the
kind of statement a charter author could accidentally hardcode instead of leaving as
the generic, discovered-at-invocation-time candidate list both charters are supposed
to use. This test reads each charter's body (YAML frontmatter stripped) and fails if
any of a small, commented denylist of this-monorepo-only identifiers shows up.

Not on the denylist, on purpose: `CLAUDE.md`, `AGENTS.md`, `openspec/`,
`docs/decisions/`, `specs/`, `.specify/` — the six generic discovery candidates both
charters legitimately name as "check whether this exists" (`design.md`, "The
resolution: an algorithm, not a target"). Naming a candidate to probe for is the
correct, portable pattern this test protects; only treating one as an unconditional
fact would be the regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foundation_tools.frontmatter import load_frontmatter

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

# The two charters this audit finding is about. explorer.md/test-runner.md predate
# them and already have their own portability track record, but nothing below fires
# on a clean file, so adding either later costs nothing.
CHARTERS = ("spec-guardian", "peer-reviewer")

# label -> pattern. Each pattern identifies something specific to the ianshank/Agents
# monorepo; a hit means this-repo knowledge leaked into a component meant to be
# consumed, unmodified, by other repos.
_DENYLIST: dict[str, re.Pattern[str]] = {
    # This repo's own GitHub owner/name. A portable charter must never assume which
    # repo — or even which host — it is being run against.
    "repo-slug": re.compile(r"ianshank/Agents", re.IGNORECASE),
    # Sibling top-level packages that exist only in *this* monorepo's layout
    # (agent-core/, behavioral-regression/, flow-corpus/, flow-protocol/,
    # src/eval_harness/). Naming any of them as fact assumes a directory layout no
    # consumer repo is guaranteed to have.
    "sibling-package-agent-core": re.compile(r"\bagent-core\b"),
    "sibling-package-behavioral-regression": re.compile(r"\bbehavioral-regression\b"),
    "sibling-package-flow-corpus": re.compile(r"\bflow-corpus\b"),
    "sibling-package-flow-protocol": re.compile(r"\bflow-protocol\b"),
    "sibling-package-eval-harness": re.compile(r"\beval_harness\b"),
    # This repo's own feature-tracking scheme: features.yaml and its F-NNN / F_NNN
    # IDs (e.g. scripts/validations/F_055.py). A conformance/review charter must
    # *discover* a repo's tracking surface, never assume this repo's ID format.
    "feature-id-scheme": re.compile(r"\bF[-_]\d{3}\b"),
    "feature-manifest": re.compile(r"\bfeatures\.yaml\b"),
    # A hardcoded absolute filesystem path: never portable across machines, let alone
    # repos. foundation_tools.scan already catches most of these in agents/*.md, but
    # only for the directories/suffixes it scans; kept here too so this specific
    # property is verifiable on its own, independent of scan.py's scope.
    "absolute-path": re.compile(r"(?:^|[\s\"'(:,])/(?:home|Users|root)/[\w./-]+"),
}

# The six generic discovery candidates both charters are supposed to name as
# *candidates to check for* — the correct, portable pattern, not a violation.
_ALLOWED_DISCOVERY_LIST = (
    "CLAUDE.md",
    "AGENTS.md",
    "openspec/",
    "docs/decisions/",
    "specs/",
    ".specify/",
)


def _charter_body(name: str) -> str:
    """Return charter ``name``'s Markdown body with YAML frontmatter stripped."""
    _, body = load_frontmatter(AGENTS_DIR / f"{name}.md")
    return body


@pytest.mark.parametrize("charter", CHARTERS)
def test_charter_body_has_no_monorepo_specific_identifiers(charter: str) -> None:
    body = _charter_body(charter)
    hits = [label for label, pattern in _DENYLIST.items() if pattern.search(body)]
    assert hits == [], (
        f"{charter}.md body contains monorepo-specific identifiers {hits}; "
        "claude-foundation charters must stay portable (ADR 0028)."
    )


@pytest.mark.parametrize("charter", CHARTERS)
def test_charter_keeps_the_generic_discovery_list(charter: str) -> None:
    """The denylist targets hardcoded *facts*, not the legitimate, generic
    "check whether this exists" candidates — confirm those are still present so a
    future denylist edit can't silently sweep them up too."""
    body = _charter_body(charter)
    for convention in _ALLOWED_DISCOVERY_LIST:
        assert convention in body, f"{charter}.md dropped the {convention!r} discovery candidate"
