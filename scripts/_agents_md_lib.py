#!/usr/bin/env python3
"""Tier table and checks behind ``scripts/check_agents_md.py``.

Split out from the entrypoint to stay inside the ADR 0019 500-line file budget. The
:data:`TIER1_COMPONENTS` / :data:`TIER2_SUBPACKAGES` / :data:`COVERED_BY_PARENT` tables here
are the single source of truth for which directories carry an ``AGENTS.md``; the CLI only
formats what :func:`collect_findings` returns.

Why the shape of these checks: coding agents read the ``AGENTS.md`` nearest the file they
are editing, and Claude Code loads a subdirectory's copy lazily -- only once it opens a file
there. Nesting is therefore the cure for context bloat rather than a cause of it, but only
while each file stays small and local. Every check below defends one half of that bargain.
See ``docs/plans/agents-md-directory-docs/PLAN.md`` for the evidence behind the thresholds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

AGENTS_FILENAME = "AGENTS.md"

# Budgets, in lines. The 200-line ceiling is the configuration-smell literature's Context
# Bloat threshold, and the number Claude Code's own memory docs give. Nested files are cheap
# -- they load only once an agent opens a file in that directory -- but exist to stay local,
# so they are held well below it. The nested ceilings sit just above a full template instance
# (six sections plus a 15-node diagram is roughly 65 lines), so they bind on prose rather
# than on structure.
EAGER_BUDGET = 200
TIER1_BUDGET = 100
TIER2_BUDGET = 80

# The files loaded at session START, every session, whether or not an agent goes near the
# directory. Claude Code reads "every AGENTS.md and .claude/AGENTS.md in your working
# directory and the directories above it" -- so `.claude/AGENTS.md` is NOT a lazily-loaded
# directory doc like the rest of the tier table. It is a second root-level instruction file.
# Budgeting it separately would be self-deception: the thing that costs a session is their
# SUM, so that is what :func:`check_eager_budget` holds to EAGER_BUDGET.
EAGER_FILES: tuple[str, ...] = (AGENTS_FILENAME, f".claude/{AGENTS_FILENAME}")

# The root is currently the only eager file, so its per-file ceiling equals the eager one.
# check_eager_budget stays as defence in depth: it fires if a .claude/AGENTS.md reappears.
ROOT_BUDGET = EAGER_BUDGET

# Top-level components: every directory an agent may be asked to work inside.
TIER1_COMPONENTS: tuple[str, ...] = (
    ".agents",
    "agent-core",
    "behavioral-regression",
    "claude-foundation",
    "config",
    "corpora",
    "demo",
    "docs",
    "examples",
    "experiments",
    "flow-corpus",
    "flow-protocol",
    "openspec",
    "scripts",
    "skills",
    "src/eval_harness",
    "tests",
)

# Source subpackages, chosen by one rule: an agent editing files here needs a constraint it
# cannot infer from the code, so the nearest-file lookup should land on something useful.
TIER2_SUBPACKAGES: tuple[str, ...] = (
    "agent-core/agent_core/store_sync",
    "flow-corpus/flow_corpus/canary",
    "flow-corpus/flow_corpus/crosscheck",
    "flow-corpus/flow_corpus/holdout",
    "flow-corpus/flow_corpus/keying",
    "flow-corpus/flow_corpus/mutation",
    "flow-corpus/flow_corpus/oracles",
    "flow-corpus/flow_corpus/policy",
    "flow-corpus/flow_corpus/specimens",
    "flow-corpus/flow_corpus/suites",
    "flow-corpus/flow_corpus/suites/sdlc",
    "flow-corpus/flow_corpus/validation",
    "src/eval_harness/agent_core_adapter",
    "src/eval_harness/braintrust_client",
    "src/eval_harness/config",
    "src/eval_harness/core",
    "src/eval_harness/datasets",
    "src/eval_harness/gating",
    "src/eval_harness/judges",
    "src/eval_harness/langfuse_client",
    "src/eval_harness/phoenix_client",
    "src/eval_harness/replay",
    "src/eval_harness/scorers",
    "src/eval_harness/scorers/rca",
    "src/eval_harness/scorers/requirements",
    "src/eval_harness/scorers/test_generation",
    "src/eval_harness/sinks",
    "src/eval_harness/state_adapters",
    "src/eval_harness/targets",
)

# Directories whose *absence* of a file is a decision, with the reason recorded so nobody
# helpfully backfills one. A skill's SKILL.md is already its agent contract (preconditions,
# procedure, output contract, failure handling); a second instruction file beside it invites
# the two to disagree, which is the Conflicting Instructions smell.
COVERED_BY_PARENT: dict[str, str] = {
    ".claude": (
        "Claude Code loads .claude/AGENTS.md EAGERLY, at session start, as a second "
        "root-level instruction file -- not lazily like every other nested file. Putting "
        "directory documentation there taxes every session in the repo whether or not "
        "anyone touches it, so .claude/ is documented in .claude/README.md instead."
    ),
    "skills/*": "SKILL.md is already the agent contract for a skill; see skills/AGENTS.md",
    "docs/decisions": "immutable ADRs; docs/AGENTS.md covers the convention",
    "docs/plans": "plan folders; docs/AGENTS.md covers the convention",
    "docs/roadmap": "epic index; docs/AGENTS.md covers the convention",
    "docs/runbooks": "operational prose; docs/AGENTS.md covers the convention",
    "docs/e2e-matrix": "generated artifact; do not hand-edit",
    "docs/golden-corpus": "contract doc only, no code",
    "scripts/validations": "protected path; one-shot F_0NN gates, not an editable surface",
    "tests/fixtures": "test data; tests/AGENTS.md covers the suite",
    "tests/integration": "same suite and gate as tests/",
    "config/fixtures": "committed calibration fixture; config/AGENTS.md covers it",
    "progress-archive": "rotated session logs; no agent decisions happen here",
}

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Map",
    "## Diagram",
    "## Rules that bite here",
    "## Verify",
    "## Subagents",
    "## See also",
)

# Style vocabulary ruff/mypy already enforce. Restating a linter is the most common smell in
# these files: pure dead weight that competes for attention with real constraints.
LINT_LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsnake_case\b", "naming is enforced by ruff"),
    (r"\bPascalCase\b", "naming is enforced by ruff"),
    (r"\bcamelCase\b", "naming is enforced by ruff"),
    (r"\bline[- ]length\b", "length limits are enforced by ruff"),
    (r"\bindentation\b", "formatting is enforced by ruff format"),
    (r"\bimport order(ing)?\b", "import order is enforced by ruff"),
    (r"\btrailing whitespace\b", "formatting is enforced by ruff format"),
)

MERMAID_DIAGRAM_TYPES: tuple[str, ...] = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "C4Component",
    "C4Context",
    "C4Container",
    "mindmap",
    "timeline",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_MERMAID_OPEN_RE = re.compile(r"^\s*```mermaid\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_GLOB_METACHARS = frozenset("*?[]")


@dataclass(frozen=True)
class Finding:
    """One violation, addressed to whoever has to fix it."""

    path: str
    check: str
    detail: str

    def render(self) -> str:
        return f"  {self.path}: [{self.check}] {self.detail}"


@dataclass
class Doc:
    """An ``AGENTS.md`` loaded once, so every check reads the same bytes."""

    path: Path
    rel: str
    budget: int
    text: str
    lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lines = self.text.splitlines()


def required_dirs() -> dict[str, int]:
    """Map every required directory to its line budget."""
    required = {d: TIER1_BUDGET for d in TIER1_COMPONENTS}
    required.update({d: TIER2_BUDGET for d in TIER2_SUBPACKAGES})
    return required


def _covered_dirs(root: Path) -> list[tuple[Path, str]]:
    """Expand COVERED_BY_PARENT, including its glob forms, to concrete directories."""
    out: list[tuple[Path, str]] = []
    for pattern, reason in COVERED_BY_PARENT.items():
        if any(ch in pattern for ch in _GLOB_METACHARS):
            out.extend((p, reason) for p in sorted(root.glob(pattern)) if p.is_dir())
        else:
            candidate = root / pattern
            if candidate.is_dir():
                out.append((candidate, reason))
    return out


def check_coverage(root: Path) -> list[Finding]:
    """Every required directory has a file; no covered directory does."""
    findings: list[Finding] = []
    for rel in sorted(required_dirs()):
        directory = root / rel
        if not directory.is_dir():
            findings.append(Finding(rel, "coverage", "listed in the tier table but the directory does not exist"))
        elif not (directory / AGENTS_FILENAME).is_file():
            findings.append(Finding(f"{rel}/{AGENTS_FILENAME}", "coverage", "required but missing"))

    for directory, reason in _covered_dirs(root):
        if (directory / AGENTS_FILENAME).is_file():
            rel = directory.relative_to(root).as_posix()
            findings.append(Finding(f"{rel}/{AGENTS_FILENAME}", "coverage", f"must NOT exist - {reason}"))
    return findings


def check_eager_budget(root: Path) -> list[Finding]:
    """The files loaded at session start must fit the Context Bloat ceiling *together*.

    Trimming the root file while adding a `.claude/AGENTS.md` moves lines around without
    reducing what a session actually pays, so the sum is what the ceiling applies to.
    """
    counts: dict[str, int] = {}
    for rel in EAGER_FILES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            counts[rel] = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue  # check_coverage/load_docs already report an unreadable file.

    total = sum(counts.values())
    if total <= EAGER_BUDGET:
        return []
    breakdown = ", ".join(f"{rel} {n}" for rel, n in sorted(counts.items()))
    return [
        Finding(
            " + ".join(sorted(counts)),
            "eager-budget",
            f"{total} lines load at session start ({breakdown}), over the {EAGER_BUDGET}-line "
            f"ceiling by {total - EAGER_BUDGET}; these load whether or not an agent goes near "
            "the directory, so push detail into a lazily-loaded nested file",
        )
    ]


def check_budget(doc: Doc) -> list[Finding]:
    """Line count within the tier ceiling -- the Context Bloat heuristic."""
    count = len(doc.lines)
    if count <= doc.budget:
        return []
    return [
        Finding(
            doc.rel,
            "budget",
            f"{count} lines exceeds the {doc.budget}-line ceiling by {count - doc.budget}; "
            "move directory-local detail into the subdirectory it belongs to",
        )
    ]


def check_sections(doc: Doc) -> list[Finding]:
    """Required headings present, and in the template's order."""
    findings: list[Finding] = []
    seen_at: dict[str, int] = {}
    for index, line in enumerate(doc.lines):
        stripped = line.rstrip()
        if stripped in REQUIRED_SECTIONS and stripped not in seen_at:
            seen_at[stripped] = index

    findings.extend(
        Finding(doc.rel, "sections", f"missing required section {section!r}")
        for section in REQUIRED_SECTIONS
        if section not in seen_at
    )

    positions = [seen_at[s] for s in REQUIRED_SECTIONS if s in seen_at]
    if positions != sorted(positions):
        findings.append(
            Finding(
                doc.rel,
                "sections",
                f"sections out of order; expected {' -> '.join(REQUIRED_SECTIONS)}",
            )
        )
    return findings


def _mermaid_blocks(doc: Doc) -> tuple[list[list[str]], list[Finding]]:
    """Split out every mermaid fence. An unterminated fence is itself a finding.

    A dropped closing fence does not simply run to end-of-file: the next fence *opener*
    (```bash under ``## Verify``, say) would otherwise be read as the close, silently
    swallowing the rest of the document into the diagram. Hitting an opener while still
    inside a block is therefore the unterminated case, reported where it happens.
    """
    blocks: list[list[str]] = []
    findings: list[Finding] = []
    current: list[str] | None = None
    for line in doc.lines:
        if current is None:
            if _MERMAID_OPEN_RE.match(line):
                current = []
            continue
        if _FENCE_CLOSE_RE.match(line):
            blocks.append(current)
            current = None
            continue
        if line.lstrip().startswith("```"):
            findings.append(Finding(doc.rel, "mermaid", f"unterminated ```mermaid fence before {line.strip()!r}"))
            current = None
            continue
        current.append(line)
    if current is not None:
        findings.append(Finding(doc.rel, "mermaid", "unterminated ```mermaid fence"))
    return blocks, findings


def check_mermaid(doc: Doc) -> list[Finding]:
    """A diagram per file, with accessibility metadata and a GitHub-safe label set."""
    blocks, findings = _mermaid_blocks(doc)
    if not blocks:
        findings.append(Finding(doc.rel, "mermaid", "no ```mermaid diagram; every AGENTS.md carries one"))
        return findings

    for number, block in enumerate(blocks, start=1):
        label = f"diagram {number}"
        body = [ln for ln in block if ln.strip()]
        if not body:
            findings.append(Finding(doc.rel, "mermaid", f"{label} is empty"))
            continue

        header = body[0].strip()
        if not any(header.startswith(kind) for kind in MERMAID_DIAGRAM_TYPES):
            findings.append(Finding(doc.rel, "mermaid", f"{label} has an unrecognised type: {header!r}"))
        joined = "\n".join(block)
        findings.extend(
            Finding(doc.rel, "mermaid", f"{label} is missing {keyword} - screen readers need it")
            for keyword in ("accTitle:", "accDescr:")
            if keyword not in joined
        )
        for line in block:
            if not line.isascii():
                findings.append(
                    Finding(
                        doc.rel,
                        "mermaid",
                        f"{label} has non-ASCII text ({line.strip()!r}); "
                        "GitHub's renderer breaks on emoji and extended characters",
                    )
                )
                break
    return findings


def check_links(doc: Doc, root: Path) -> list[Finding]:
    """Every relative link resolves from the file's own directory."""
    findings: list[Finding] = []
    for target in _LINK_RE.findall(doc.text):
        raw = target.strip().split(" ", 1)[0]
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1]
        if not raw or raw.startswith(("http://", "https://", "mailto:", "#", "/")):
            continue
        if any(ch in raw for ch in _GLOB_METACHARS):
            continue
        cleaned = raw.split("#", 1)[0].split("?", 1)[0]
        if not cleaned:
            continue
        resolved = (doc.path.parent / cleaned).resolve()
        if not resolved.exists():
            try:
                shown = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                shown = resolved.as_posix()
            findings.append(Finding(doc.rel, "links", f"dead relative link {raw!r} -> {shown}"))
    return findings


def check_lint_leakage(doc: Doc) -> list[Finding]:
    """Reject style rules the linters already enforce."""
    findings: list[Finding] = []
    for pattern, reason in LINT_LEAK_PATTERNS:
        match = re.search(pattern, doc.text, flags=re.IGNORECASE)
        if match:
            findings.append(
                Finding(
                    doc.rel,
                    "lint-leakage",
                    f"{match.group(0)!r} - {reason}; delete the rule, keep the budget",
                )
            )
    return findings


def check_blind_references(doc: Doc) -> list[Finding]:
    """A 'See also' row needs a trigger, not just a path."""
    findings: list[Finding] = []
    try:
        start = doc.lines.index("## See also")
    except ValueError:
        return findings

    for line in doc.lines[start + 1 :]:
        if line.startswith("## "):
            break
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0]:
            continue
        if set(cells[0]) <= set("-: ") or cells[0].lower().startswith("doc"):
            continue
        if not cells[1]:
            findings.append(
                Finding(
                    doc.rel,
                    "blind-reference",
                    f"{cells[0]} has no 'Read it when' trigger; a bare path gets ignored",
                )
            )
    return findings


def load_docs(root: Path) -> tuple[list[Doc], list[Finding]]:
    """Load the root file plus every required file that exists."""
    docs: list[Doc] = []
    findings: list[Finding] = []
    wanted: list[tuple[Path, int]] = [(root / AGENTS_FILENAME, ROOT_BUDGET)]
    wanted.extend((root / rel / AGENTS_FILENAME, budget) for rel, budget in sorted(required_dirs().items()))

    for path, budget in wanted:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(rel, "read", f"cannot read as UTF-8: {exc}"))
            continue
        docs.append(Doc(path=path, rel=rel, budget=budget, text=text))
    return docs, findings


def collect_findings(root: Path) -> list[Finding]:
    """Run every check. The root file is exempt from the nested-file section template."""
    docs, findings = load_docs(root)
    findings.extend(check_coverage(root))
    findings.extend(check_eager_budget(root))

    for doc in docs:
        findings.extend(check_budget(doc))
        findings.extend(check_links(doc, root))
        findings.extend(check_lint_leakage(doc))
        if doc.rel == AGENTS_FILENAME:
            # The root file is cross-cutting orientation, not a directory description: it
            # carries neither the section template nor a local diagram.
            continue
        findings.extend(check_sections(doc))
        findings.extend(check_mermaid(doc))
        findings.extend(check_blind_references(doc))

    return sorted(findings, key=lambda f: (f.path, f.check, f.detail))
