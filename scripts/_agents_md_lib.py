#!/usr/bin/env python3
"""Tier table and checks behind ``scripts/check_agents_md.py``.

Split out from the entrypoint (and mermaid checks into ``_agents_md_mermaid``) to stay
inside the ADR 0019 500-line file budget. The tier tables here are the single source of
truth; the CLI formats what :func:`collect_findings` returns.
See ``docs/plans/agents-md-directory-docs/PLAN.md`` for threshold evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from _agents_md_mermaid import check_mermaid

AGENTS_FILENAME = "AGENTS.md"

# Budgets in lines. 200 is the Context Bloat threshold; nested ceilings bind on prose.
EAGER_BUDGET = 200
TIER1_BUDGET = 100
TIER2_BUDGET = 80

# Eagerly loaded at session start (Claude Code also loads `.claude/AGENTS.md` when present).
EAGER_FILES: tuple[str, ...] = (AGENTS_FILENAME, f".claude/{AGENTS_FILENAME}")
ROOT_BUDGET = EAGER_BUDGET

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

# Absence is a decision. A skill's SKILL.md is already its agent contract.
COVERED_BY_PARENT: dict[str, str] = {
    ".claude": ("Loads eagerly as a second root instruction file; document in .claude/README.md instead."),
    "skills/**": "SKILL.md is already the agent contract for a skill; see skills/AGENTS.md",
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

LINT_LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsnake_case\b", "naming is enforced by ruff"),
    (r"\bPascalCase\b", "naming is enforced by ruff"),
    (r"\bcamelCase\b", "naming is enforced by ruff"),
    (r"\bline[- ]length\b", "length limits are enforced by ruff"),
    (r"\bindentation\b", "formatting is enforced by ruff format"),
    (r"\bimport order(ing)?\b", "import order is enforced by ruff"),
    (r"\btrailing whitespace\b", "formatting is enforced by ruff format"),
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
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
    """Expand COVERED_BY_PARENT (including globs). Required dirs always win over covered."""
    required = set(required_dirs())
    out: list[tuple[Path, str]] = []
    for pattern, reason in COVERED_BY_PARENT.items():
        if any(ch in pattern for ch in _GLOB_METACHARS):
            matches = [p for p in sorted(root.glob(pattern)) if p.is_dir()]
        else:
            candidate = root / pattern
            matches = [candidate] if candidate.is_dir() else []
        for path in matches:
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover
                continue
            if rel not in required:
                out.append((path, reason))
    return out


def _canonical_agents_paths() -> set[str]:
    """Root file plus every tier-table path — the only AGENTS.md files allowed to exist."""
    return {AGENTS_FILENAME} | {f"{d}/{AGENTS_FILENAME}" for d in required_dirs()}


def check_coverage(root: Path) -> list[Finding]:
    """Root + every required dir has a file; covered dirs do not; no strays elsewhere."""
    findings: list[Finding] = []
    if not (root / AGENTS_FILENAME).is_file():
        findings.append(Finding(AGENTS_FILENAME, "coverage", "required but missing"))

    for rel in sorted(required_dirs()):
        directory = root / rel
        if not directory.is_dir():
            findings.append(
                Finding(
                    rel,
                    "coverage",
                    "listed in the tier table but the directory does not exist",
                )
            )
        elif not (directory / AGENTS_FILENAME).is_file():
            findings.append(Finding(f"{rel}/{AGENTS_FILENAME}", "coverage", "required but missing"))

    covered_rels = {
        f"{directory.relative_to(root).as_posix()}/{AGENTS_FILENAME}" for directory, _ in _covered_dirs(root)
    }
    for directory, reason in _covered_dirs(root):
        if (directory / AGENTS_FILENAME).is_file():
            rel = directory.relative_to(root).as_posix()
            findings.append(Finding(f"{rel}/{AGENTS_FILENAME}", "coverage", f"must NOT exist - {reason}"))

    canonical = _canonical_agents_paths()
    for path in root.rglob(AGENTS_FILENAME):
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in canonical or rel in covered_rels:
            continue
        findings.append(
            Finding(
                rel,
                "coverage",
                "unexpected AGENTS.md outside the tier table and COVERED_BY_PARENT allowances",
            )
        )
    return findings


def check_eager_budget(root: Path) -> list[Finding]:
    """Session-start files must fit the Context Bloat ceiling *together*.

    One Finding per contributing path so ``--paths-only`` emits real paths, not a synthetic
    ``A + B`` string.
    """
    counts: dict[str, int] = {}
    for rel in EAGER_FILES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            counts[rel] = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue

    total = sum(counts.values())
    if total <= EAGER_BUDGET:
        return []
    breakdown = ", ".join(f"{rel} {n}" for rel, n in sorted(counts.items()))
    detail = (
        f"{total} lines load at session start ({breakdown}), over the {EAGER_BUDGET}-line "
        f"ceiling by {total - EAGER_BUDGET}; these load whether or not an agent goes near "
        "the directory, so push detail into a lazily-loaded nested file"
    )
    return [Finding(rel, "eager-budget", detail) for rel in sorted(counts)]


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
            continue
        findings.extend(check_sections(doc))
        findings.extend(check_mermaid(doc))
        findings.extend(check_blind_references(doc))

    return sorted(findings, key=lambda f: (f.path, f.check, f.detail))
