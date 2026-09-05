#!/usr/bin/env python3
"""Domain logic for the test-generation corpus: templates, mutation, obligations, suites.

Split out of ``gen_testgen_corpus.py`` when that file passed the 500-line hard budget
(``scripts/check_size_budget.py``), following the house answer to that gate — move a
cohesive concern to its own owner (ADR 0036, ADR 0019) rather than trim documentation to
fit. ``scripts/_cli.py``, ``scripts/_config.py`` and ``scripts/_provenance.py`` are the
existing private-helper precedent in this directory.

The seam: everything here is a pure function of its arguments and knows nothing about
files, paths or the CLI. ``gen_testgen_corpus.py`` keeps assembly, the manifest, and the
write/check commands. That is what lets the corpus tests exercise mutation and obligation
derivation without touching a filesystem.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any

#: Input grid every focal method is evaluated over — for equivalence detection, for
#: obligation partitioning, and for nothing else. Small and total: exhaustive over a
#: bounded domain beats sampling, because "equivalent on the grid" is then a statement
#: about the whole domain the corpus ever exercises.
GRID = tuple((n, k) for n in range(-4, 9) for k in range(-2, 5))

#: How ``_behaviour`` encodes "the function raised here" inside a tuple of return values.
#: A sentinel prefix rather than a wrapper type because the tuple is compared for equality
#: and serialised into JSON.
#:
#: Named, with :func:`raises` as its only reader, because the bare ``"!"`` literal was
#: tested with ``.startswith`` at three separate call sites: a reference function that
#: legitimately returned a string beginning with ``"!"`` would have been read as an
#: exception at all three. Today's templates return ``int``, so the collision is latent —
#: which is exactly when it is cheap to close.
RAISE_MARKER = "!"

_HEX = 8
_SCALE = float(16**_HEX)


def raises(value: Any) -> bool:
    """Whether *value* is :func:`_behaviour`'s encoding of a raised exception."""
    return isinstance(value, str) and value.startswith(RAISE_MARKER)


def _bucket(seed: int, key: str) -> float:
    """Map ``(seed, key)`` deterministically into ``[0, 1)``.

    Mirrors ``flow-corpus/flow_corpus/partition.py:22``. Copied as an idiom rather than
    imported: F-011 airgaps ``eval_harness`` from ``flow_corpus``, and this corpus is
    loaded by the harness.
    """
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:_HEX], 16) / _SCALE


# --------------------------------------------------------------------------- templates

#: Control-flow strata, each a template whose body is filled with a threshold and an
#: operator. The names are the dataflow-testing terms the change's proposal cites: a
#: **p-use** is a variable read inside a predicate, a **c-use** a variable read inside a
#: computation. Each template places its parameters in both roles so a suite that only
#: exercises one is visibly weaker.
_TEMPLATES: dict[str, str] = {
    # p-use of neither; c-use of both. The floor case: no branch to get wrong.
    "linear": """
def {name}(n: int, k: int) -> int:
    return n * {t} + k
""",
    # p-use of n; c-use of n and k.
    "single_branch": """
def {name}(n: int, k: int) -> int:
    if n {op} {t}:
        return n + k
    return k - n
""",
    # p-use of n then k; c-use of both in each arm.
    "nested_branch": """
def {name}(n: int, k: int) -> int:
    if n {op} {t}:
        if k {op} 0:
            return n * k
        return n - k
    return k
""",
    # p-use of the induction variable; c-use of n and k.
    "loop": """
def {name}(n: int, k: int) -> int:
    total = k
    for i in range({t}):
        total = total + n - i
    return total
""",
    # p-use inside the loop body: the stratum a suite most often under-covers.
    "loop_branch": """
def {name}(n: int, k: int) -> int:
    total = 0
    for i in range({t}):
        if n {op} i:
            total = total + n
        else:
            total = total - k
    return total
""",
}

#: Thresholds cycled through to vary items within a stratum. Deliberately small and total
#: rather than random: the corpus must regenerate byte-identically.
#:
#: Per stratum, because `{t}` means different things in different templates. In the loop
#: strata it is the iteration count, and a 0 there makes the whole loop body DEAD CODE —
#: the `loop_branch` predicate becomes unreachable, so no mutation inside it can ever be
#: killed and the item silently teaches nothing about the stratum it claims to represent.
#: Caught by reading a generated item rather than by a test, which is why the corpus is
#: committed and reviewable rather than generated on the fly.
_THRESHOLDS: dict[str, tuple[int, ...]] = {
    "linear": (0, 1, 2, 3),
    "single_branch": (0, 1, 2, 3),
    "nested_branch": (0, 1, 2, 3),
    "loop": (1, 2, 3, 4),
    "loop_branch": (1, 2, 3, 4),
}
_OPERATORS = ("<", "<=", ">")


# --------------------------------------------------------------------------- mutation


class _MutationOperator(ast.NodeTransformer):
    """Apply exactly ONE mutation, identified by its index among eligible sites.

    One at a time, deliberately: a mutant carrying two independent faults can be killed
    by a test that detects either, which makes "this suite killed the mutant" a weaker
    statement than it looks.
    """

    def __init__(self, kind: str, target_index: int) -> None:
        self.kind = kind
        self.target_index = target_index
        self._seen = 0
        self.applied = False

    def _take(self) -> bool:
        hit = self._seen == self.target_index
        self._seen += 1
        if hit:
            self.applied = True
        return hit

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if self.kind != "relational" or not node.ops:
            return node
        swap: dict[type, type] = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
        replacement = swap.get(type(node.ops[0]))
        if replacement is not None and self._take():
            node.ops = [replacement()]
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if self.kind != "arithmetic":
            return node
        swap: dict[type, type] = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add}
        replacement = swap.get(type(node.op))
        if replacement is not None and self._take():
            node.op = replacement()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if self.kind != "constant" or not isinstance(node.value, int) or isinstance(node.value, bool):
            return node
        if self._take():
            return ast.Constant(value=node.value + 1)
        return node


_MUTATION_KINDS = ("relational", "arithmetic", "constant")

#: Mutants attempted per kind per focal method. Bounded so the corpus stays small enough
#: that a target can run every mutant per item inside a wall-clock limit.
_MAX_SITES_PER_KIND = 3


def _mutate(source: str, kind: str, index: int) -> str | None:
    """The source with one *kind* mutation applied at *index*, or ``None`` if no such site."""
    tree = ast.parse(source)
    transformer = _MutationOperator(kind, index)
    mutated = transformer.visit(copy.deepcopy(tree))
    if not transformer.applied:
        return None
    ast.fix_missing_locations(mutated)
    return ast.unparse(mutated)


# --------------------------------------------------------------------------- behaviour


def _behaviour(source: str, name: str) -> tuple[Any, ...]:
    """The function's output over :data:`GRID`, with exceptions recorded as their type.

    Compiled in an empty namespace. The sources are this generator's own templates, not
    model output — the untrusted-code path is the *target*, which runs generated suites in
    a subprocess sandbox.
    """
    namespace: dict[str, Any] = {}
    exec(compile(source, f"<corpus:{name}>", "exec"), namespace)
    fn = namespace[name]
    results: list[Any] = []
    for n, k in GRID:
        try:
            results.append(fn(n, k))
        except Exception as exc:  # a raise is behaviour too, and mutants can introduce one
            results.append(f"{RAISE_MARKER}{type(exc).__name__}")
    return tuple(results)


@dataclass
class _Mutant:
    id: str
    kind: str
    source: str
    equivalent: bool
    #: Grid indices where this mutant differs from the reference. Empty iff equivalent.
    differs_at: tuple[int, ...] = field(default_factory=tuple)


def _build_mutants(source: str, name: str, reference: tuple[Any, ...]) -> list[_Mutant]:
    """Every distinct single-site mutant, with equivalence DECIDED against the grid."""
    mutants: list[_Mutant] = []
    seen: set[str] = {source}
    for kind in _MUTATION_KINDS:
        for index in range(_MAX_SITES_PER_KIND):
            mutated = _mutate(source, kind, index)
            if mutated is None or mutated in seen:
                continue
            seen.add(mutated)
            behaviour = _behaviour(mutated, name)
            differs = tuple(i for i, (a, b) in enumerate(zip(reference, behaviour, strict=True)) if a != b)
            mutants.append(
                _Mutant(
                    id=f"M{len(mutants) + 1}",
                    kind=kind,
                    source=mutated,
                    equivalent=not differs,
                    differs_at=differs,
                )
            )
    return mutants


def _build_obligations(reference: tuple[Any, ...], mutants: list[_Mutant]) -> list[dict[str, Any]]:
    """Atomic behavioural obligations, each with a mutant that provably breaks it.

    An obligation is an equivalence class of grid inputs under *which mutants detect a
    difference there* — its "distinguishing signature". Two inputs with the same signature
    cannot be told apart by anything in this mutant set, so they are one behaviour, not
    two. Its witness is the mutant in that signature that differs on the FEWEST grid points
    overall: the most specific evidence available that a suite exercised this behaviour
    rather than something merely adjacent to it.

    An earlier cut partitioned by *output value* instead, which produced a median of 16
    obligations per item and a maximum of 43 — those are test cases ("returns 47 for this
    input"), not obligations, and a recall denominator built from them would measure how
    exhaustively a suite enumerated the grid rather than whether it covered the behaviour.

    Inputs with an empty signature are dropped: no non-equivalent mutant distinguishes
    them, so no suite could ever be shown to cover them, and an obligation like that would
    cap recall below 1.0 for reasons that have nothing to do with the suite.
    """
    signatures: dict[tuple[str, ...], list[int]] = {}
    for index in range(len(reference)):
        signature = tuple(sorted(m.id for m in mutants if not m.equivalent and index in m.differs_at))
        if not signature:
            continue
        signatures.setdefault(signature, []).append(index)

    by_id = {m.id: m for m in mutants}
    obligations: list[dict[str, Any]] = []
    for signature, indices in sorted(signatures.items()):
        witness = min((by_id[mid] for mid in signature), key=lambda m: (len(m.differs_at), m.id))
        obligations.append(
            {
                "id": f"OB-{len(obligations) + 1}",
                "description": (
                    f"the behaviour distinguished by {'+'.join(signature)} across {len(indices)} grid input(s)"
                ),
                "witness_mutant": witness.id,
            }
        )
    return obligations


# --------------------------------------------------------------------------- suites

#: The module name the sandbox writes the focal implementation to. Every generated suite
#: imports from it, so the target can swap the reference for a mutant without touching the
#: suite. Named here because the generator writes the import and the target writes the file
#: -- two places that must agree, single-sourced.
FOCAL_MODULE = "focal"

#: How many test functions the thorough suite splits its cases across. More than one so a
#: "collected" count above 1 is meaningful; small enough that the suite stays readable.
_THOROUGH_CHUNKS = 4

#: Reference suites shipped WITH each item, and what each exists to pin.
#:
#: These are corpus fixtures, not agent output. The corpus states a task; an agent's suite
#: is what gets scored against it. But four scorers with no known dynamic range are four
#: scorers nobody can calibrate, so each item carries suites whose scores are known in
#: advance -- the "10 known-good and 10 known-bad" the change's task 6.4 asks to dry-run.
SUITE_KINDS = ("thorough", "weak", "broken", "false_alarm")


def _case_lines(name: str, reference: tuple[Any, ...], indices: list[int]) -> list[str]:
    """`assert` lines pinning the reference's own behaviour at *indices*."""
    lines: list[str] = []
    for index in indices:
        n, k = GRID[index]
        expected = reference[index]
        # Callers must filter raising indices out first -- `_build_suites` does, via
        # `live`. An earlier cut emitted `with pytest_raises():` here instead, which is
        # undefined in the generated suite (the header imports only the focal function) and
        # in the runner (deliberately pytest-free). It was unreachable, so it never fired;
        # a reachable version would have turned a "thorough" fixture into a NameError at
        # import -- silently reclassifying the corpus's known-GOOD suite as its known-BROKEN
        # one, and taking the calibration with it. Refusing is the honest form of a branch
        # that cannot be written correctly here.
        if raises(expected):
            raise ValueError(
                f"_case_lines cannot pin a raising reference value ({expected!r} at grid index {index}); "
                "filter raising indices out before calling, as _build_suites does"
            )
        lines.append(f"    assert {name}({n}, {k}) == {expected!r}")
    return lines


def _covering_indices(mutants: list[_Mutant]) -> list[int]:
    """A small set of grid indices that distinguishes every non-equivalent mutant.

    Greedy set cover: repeatedly take the index that separates the most still-undetected
    mutants. Deterministic (ties break on the lower index), so the corpus regenerates
    byte-identically.

    Why not simply assert every grid point: a "thorough" suite that pins all 91 inputs is
    not what a competent engineer writes, and shipping one as the known-good reference
    would make the corpus reward exhaustive enumeration over behavioural coverage. It also
    made the committed corpus four times larger than it needed to be.
    """
    remaining = {m.id: set(m.differs_at) for m in mutants if not m.equivalent}
    chosen: list[int] = []
    while remaining:
        counts: dict[int, int] = {}
        for indices in remaining.values():
            for index in indices:
                counts[index] = counts.get(index, 0) + 1
        if not counts:
            break  # mutants with no differing index cannot be distinguished at all
        best = min(counts, key=lambda i: (-counts[i], i))
        chosen.append(best)
        remaining = {mid: idx for mid, idx in remaining.items() if best not in idx}
    return sorted(chosen)


def _assertable_indices(reference: tuple[Any, ...]) -> list[int]:
    """Grid indices whose reference value can be pinned with a plain ``assert``."""
    return [i for i, value in enumerate(reference) if not raises(value)]


def _weakest_index(candidates: list[int], mutants: list[_Mutant]) -> int:
    """The candidate grid index distinguishing the FEWEST non-equivalent mutants.

    ``weak`` used to assert ``live[0]``, which is the first element of the greedy set cover
    and therefore, by construction, the point separating the MOST mutants. The known-BAD
    fixture was being built from the single strongest assertion available. Measured on the
    committed corpus, that made ``weak`` byte-identical to ``thorough`` apart from the test
    function's name for **32 of the 60 items** — over half the calibration set had no
    dynamic range at all on the mutation axis, and nothing detected it because every check
    on these suites compared text rather than running them.

    *candidates* is the whole non-raising grid, deliberately, not the covering set: for
    exactly those 32 items the cover is a SINGLE index, so choosing within it leaves no
    choice to make and the two suites stay identical. The dynamic range lives in the grid
    points the cover did not need.

    A point that still kills at least one mutant is preferred when one exists: a ``weak``
    suite killing nothing is indistinguishable from a suite that never reached the fault,
    which is a different fixture (``blind``) making a different point. Ties break on the
    lower index, so the corpus regenerates byte-identically.
    """
    counts = {i: sum(1 for m in mutants if not m.equivalent and i in m.differs_at) for i in candidates}
    killers = {i: c for i, c in counts.items() if c > 0}
    pool = killers or counts
    return min(pool, key=lambda i: (pool[i], i))


def weak_is_strictly_weaker(item: dict[str, Any]) -> bool:
    """Whether *item*'s ``weak`` suite really does kill fewer mutants than ``thorough``.

    Reads a serialised corpus item so both callers can use it: the manifest builder, which
    has only dicts, and a test, which reads what shipped rather than what a generator would
    produce now.

    Not always achievable in principle — an item whose every non-equivalent mutant differs
    at every grid point admits no strictly-weaker single assertion — so this is **measured
    into the manifest** rather than assumed. The corpus then reports how much of itself can
    actually calibrate the mutation axis instead of claiming all of it can. On the corpus
    that motivated it the honest figure was 28 of 60; the ``weak`` fixture now selects from
    the whole grid rather than the covering set, and it is 60 of 60.
    """
    non_equivalent = [m for m in item["mutants"] if not m["equivalent"]]
    if not non_equivalent:
        return False
    reference = _behaviour(item["reference"], item["focal_name"])
    candidates = _assertable_indices(reference)
    if not candidates:
        return False
    mutants = [
        _Mutant(m["id"], m["kind"], m["source"], m["equivalent"], tuple(m["differs_at"])) for m in item["mutants"]
    ]
    weak_index = _weakest_index(candidates, mutants)
    weak_kills = sum(1 for m in non_equivalent if weak_index in m["differs_at"])
    return weak_kills < len(non_equivalent)


def _build_suites(name: str, reference: tuple[Any, ...], mutants: list[_Mutant]) -> dict[str, str]:
    """One suite per kind, each with a known relationship to the scorers.

    ``thorough`` asserts the reference at a minimal set of inputs that distinguishes every
    non-equivalent mutant, so it kills all of them and scores 1.0 on all four. ``weak`` asserts one point. ``broken``
    raises during collection, which is the non-executable case ``test_executability``
    exists to separate from a merely bad suite. ``false_alarm`` is ``thorough`` plus one
    assertion the reference does not satisfy, so it fails on correct code while still
    killing mutants -- the exact shape that a single blended quality score would hide.
    """
    header = f"from {FOCAL_MODULE} import {name}\n\n"
    covering = _covering_indices(mutants)
    live = [i for i in covering if not raises(reference[i])]
    if not live:  # every distinguishing input raises; fall back to the first usable point
        live = [i for i, value in enumerate(reference) if not raises(value)][:1]

    chunk = max(1, len(live) // _THOROUGH_CHUNKS)
    thorough_bodies: list[str] = []
    for part, start in enumerate(range(0, len(live), chunk)):
        lines = _case_lines(name, reference, live[start : start + chunk])
        if lines:
            thorough_bodies.append(f"def test_part_{part}():\n" + "\n".join(lines))
    thorough = header + "\n\n".join(thorough_bodies) + "\n"

    first = live[0]
    weak_index = _weakest_index(_assertable_indices(reference), mutants)
    weak = header + "def test_one_case():\n" + "\n".join(_case_lines(name, reference, [weak_index])) + "\n"

    broken = header + "raise RuntimeError('suite fails at import time')\n"

    wrong = reference[first]
    sentinel = (wrong + 1) if isinstance(wrong, int) else 0
    false_alarm = thorough + f"\n\ndef test_false_alarm():\n    assert {name}{GRID[first]} == {sentinel!r}\n"
    return {"thorough": thorough, "weak": weak, "broken": broken, "false_alarm": false_alarm}
