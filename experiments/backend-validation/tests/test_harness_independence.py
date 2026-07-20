"""Guard: only the L2 modules may import the eval harness (spec R1 harness-independence).

The whole point of the L1 layer is that it exercises each backend's OWN SDK/API, unbiased
by the incumbent harness. This test statically asserts that invariant across the package —
if a future edit imports ``eval_harness`` from an L1/core module, this fails loudly.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "backend_validation"

# The ONLY modules permitted to couple to the harness (they carry the precondition gate).
_ALLOWED = {"probes/l2_sink.py", "l2_phase.py"}


def _imports_eval_harness(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "eval_harness" or alias.name.startswith("eval_harness.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "eval_harness" or module.startswith("eval_harness."):
                return True
    return False


def test_only_l2_modules_import_the_harness() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel in _ALLOWED:
            continue
        if _imports_eval_harness(path):
            offenders.append(rel)
    assert offenders == [], f"non-L2 modules import eval_harness (breaks R1 harness-independence): {offenders}"


def test_l2_modules_do_import_the_harness() -> None:
    # Sanity: the allowlist is real, not stale — the L2 modules genuinely use the seam.
    l2_sink = PACKAGE / "probes" / "l2_sink.py"
    text = l2_sink.read_text(encoding="utf-8")
    assert "eval_harness" in text  # imported lazily inside functions, but present
