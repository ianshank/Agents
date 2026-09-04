#!/usr/bin/env python3
"""Assert no declared coverage floor has been quietly lowered past its pinned minimum.

The eval-integrity guard (``scripts/eval_protected_paths.py`` +
``scripts/check_protected_changes.py``) protects the files that *define* a gate. It did
not protect the files where the gate *thresholds* live, and nothing asserted the values:

* ``check_charter_invariants.check_coverage_floors_declared`` is existence-only, and says
  so in its own docstring.
* ``tests/test_e2e_matrix.py::test_floor_anchors_agree_with_each_other`` asserts a
  package's two anchors state the *same* number, never *which* number.

So changing ``fail_under = 96`` to ``50`` in ``pyproject.toml`` and the matching
``--cov-fail-under=`` in ``scripts/quality-gate.sh`` passed every gate, with no
``eval-change-approved`` label and no CODEOWNER review. The intended values existed only
as prose in ``docs/CHARTER_ALIGNMENT_AUDIT.md``, which no gate reads.

``coverage-floors.yaml`` is now that declarative source of truth, and this guard enforces
it. **No threshold is hard-coded here**: every number compared comes either from the
manifest or from the source file the manifest names. Raising a declared floor is always
allowed; lowering one requires editing the manifest, which is itself a protected path.

Usage::

    python scripts/check_coverage_floors.py            # human-readable report
    python scripts/check_coverage_floors.py --json     # machine-readable
    python scripts/check_coverage_floors.py --verbose  # debug logging

Exit codes:
    0 - every declared floor is at or above its pinned minimum
    1 - at least one floor is below its pin, missing, or unreadable
    2 - usage error (manifest missing or malformed)
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _cli import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

#: The declarative manifest this guard enforces, relative to the repository root.
#: Single-sourced here so relocating it is a one-line change.
MANIFEST_PATH = Path("coverage-floors.yaml")

#: Exit code for a configuration / usage error (matches the module docstring contract).
EXIT_USAGE_ERROR = 2


class ManifestError(RuntimeError):
    """The floors manifest is missing, unparseable, or structurally invalid."""


@dataclass(frozen=True)
class Source:
    """One file that independently declares a unit's coverage floor."""

    kind: str
    path: str


@dataclass(frozen=True)
class Unit:
    """A gated unit, the floor pinned for it, and every file that declares that floor."""

    name: str
    pinned_minimum: int
    sources: tuple[Source, ...]
    description: str = ""


@dataclass(frozen=True)
class Finding:
    """One way a unit's declared floor fails to honour its pinned minimum."""

    kind: str  # "floor_lowered" | "source_missing" | "floor_unreadable"
    unit: str
    path: str
    source_kind: str
    pinned: int
    declared: int | None
    detail: str


# --- floor extraction: one reader per declared source kind ---------------------------


def floor_from_pyproject(text: str) -> int | None:
    """``fail_under`` under ``[tool.coverage.report]``, read without a TOML dependency.

    A regex section read, matching ``check_charter_invariants`` and ``tests._e2e_matrix``:
    ``scripts/`` deliberately carries no ``tomli`` dependency, and a second parsing
    strategy for the same stanza is a second thing to keep in sync.
    """
    section = re.search(r"^\[tool\.coverage\.report\](?P<body>.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return None
    value = re.search(r"^\s*fail_under\s*=\s*\"?(?P<n>\d+)", section.group("body"), re.MULTILINE)
    return int(value.group("n")) if value else None


def floor_from_gate_script(text: str) -> int | None:
    """``--cov-fail-under=N`` from a generated ``quality-gate.sh``.

    The threshold is a generation-time literal, never a live ``$COV_FAIL_UNDER`` override
    (F-054 closed that evasion), so a bare ``--cov-fail-under=N`` is the only form a
    freshly generated script can contain.

    A gate script can carry more than one coverage stage — root's hand-maintained
    ``do_extra()`` adds the ``scripts/`` gate below the generator's marker (it takes its
    floor from ``scripts/.coveragerc`` today, but nothing stops a future stage from passing
    the flag). The *lowest* threshold present is therefore returned: the weakest number in
    the file is the one a reviewer needs to see, and taking the first match would let a
    lowered later stage hide behind an untouched earlier one.
    """
    values = [int(m.group("n")) for m in re.finditer(r"--cov-fail-under=(?P<n>\d+)", text)]
    return min(values) if values else None


def floor_from_coveragerc(text: str) -> int | None:
    """``fail_under`` under ``[report]`` in an INI coverage config."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
        return parser.getint("report", "fail_under")
    except (configparser.Error, ValueError) as exc:
        logger.debug("cannot read a coverage floor from an INI config (%s)", exc)
        return None


#: Extraction kind -> reader. The manifest's ``kind`` field is validated against these
#: keys, so a typo there is a loud manifest error rather than a silently skipped source.
EXTRACTORS: dict[str, Callable[[str], int | None]] = {
    "pyproject": floor_from_pyproject,
    "gate_script": floor_from_gate_script,
    "coveragerc": floor_from_coveragerc,
}


# --- manifest loading ----------------------------------------------------------------


def _require_mapping(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestError(f"{what} must be a mapping, got {type(value).__name__}")
    return {str(k): v for k, v in value.items()}


def _parse_source(raw: object, unit_name: str) -> Source:
    entry = _require_mapping(raw, f"unit {unit_name!r}: each entry of 'sources'")
    kind = entry.get("kind")
    path = entry.get("path")
    if not isinstance(kind, str) or kind not in EXTRACTORS:
        raise ManifestError(f"unit {unit_name!r}: source kind {kind!r} is not one of {sorted(EXTRACTORS)}")
    if not isinstance(path, str) or not path.strip():
        raise ManifestError(f"unit {unit_name!r}: source 'path' must be a non-empty string, got {path!r}")
    return Source(kind=kind, path=path.strip())


def _parse_unit(raw: object) -> Unit:
    entry = _require_mapping(raw, "each entry of 'units'")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestError(f"unit 'name' must be a non-empty string, got {name!r}")
    pinned = entry.get("pinned_minimum")
    # bool is an int subclass; `pinned_minimum: true` is a manifest error, not a floor of 1.
    if not isinstance(pinned, int) or isinstance(pinned, bool) or not 0 <= pinned <= 100:
        raise ManifestError(f"unit {name!r}: 'pinned_minimum' must be an integer percentage 0-100, got {pinned!r}")
    sources = entry.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ManifestError(f"unit {name!r}: 'sources' must be a non-empty list")
    description = entry.get("description")
    return Unit(
        name=name.strip(),
        pinned_minimum=pinned,
        sources=tuple(_parse_source(s, name) for s in sources),
        description=description if isinstance(description, str) else "",
    )


def load_manifest(path: Path) -> tuple[Unit, ...]:
    """Parse the floors manifest at *path*.

    Every structural problem raises :class:`ManifestError` rather than degrading to a
    partial check: a manifest this guard cannot fully understand must never be reported as
    a pass, because that green tick is exactly what a weakened threshold would hide behind.
    """
    if not path.is_file():
        raise ManifestError(f"floors manifest not found: {path.as_posix()}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise ManifestError(f"{path.as_posix()} is not readable YAML: {exc}") from exc
    document = _require_mapping(loaded, f"{path.as_posix()}: the manifest")
    units = document.get("units")
    if not isinstance(units, list) or not units:
        raise ManifestError(f"{path.as_posix()}: 'units' must be a non-empty list")
    parsed = tuple(_parse_unit(u) for u in units)
    names = [u.name for u in parsed]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ManifestError(f"{path.as_posix()}: duplicate unit name(s): {duplicates}")
    logger.debug("loaded %d pinned unit(s) from %s", len(parsed), path.as_posix())
    return parsed


# --- the check -----------------------------------------------------------------------


def check_source(root: Path, unit: Unit, source: Source) -> Finding | None:
    """Compare one source file's declared floor against its unit's pinned minimum."""
    path = root / source.path
    if not path.is_file():
        return Finding(
            kind="source_missing",
            unit=unit.name,
            path=source.path,
            source_kind=source.kind,
            pinned=unit.pinned_minimum,
            declared=None,
            detail="file does not exist; the pinned floor is no longer enforced anywhere",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Finding(
            kind="floor_unreadable",
            unit=unit.name,
            path=source.path,
            source_kind=source.kind,
            pinned=unit.pinned_minimum,
            declared=None,
            detail=f"cannot read the file: {exc}",
        )
    declared = EXTRACTORS[source.kind](text)
    if declared is None:
        return Finding(
            kind="floor_unreadable",
            unit=unit.name,
            path=source.path,
            source_kind=source.kind,
            pinned=unit.pinned_minimum,
            declared=None,
            detail=f"no {source.kind} coverage floor found in the file",
        )
    logger.debug("%s: %s declares %d (pinned >= %d)", unit.name, source.path, declared, unit.pinned_minimum)
    if declared < unit.pinned_minimum:
        return Finding(
            kind="floor_lowered",
            unit=unit.name,
            path=source.path,
            source_kind=source.kind,
            pinned=unit.pinned_minimum,
            declared=declared,
            detail="declared coverage floor is below the pinned minimum",
        )
    return None


def check(root: Path, units: Sequence[Unit]) -> list[Finding]:
    """Every way the tree's declared floors fail to honour *units*, sorted and complete."""
    findings = [finding for unit in units for source in unit.sources if (finding := check_source(root, unit, source))]
    return sorted(findings, key=lambda f: (f.unit, f.path, f.kind))


def render_text(findings: Sequence[Finding], units: Sequence[Unit], manifest: Path) -> str:
    """A human-readable report naming the file, the pinned value and the actual value."""
    source_count = sum(len(u.sources) for u in units)
    if not findings:
        return (
            f"coverage-floors: OK - {source_count} declared floor(s) across {len(units)} unit(s) "
            f"are at or above the minimums pinned in {manifest.as_posix()}."
        )
    lines = [
        f"coverage-floors: FAIL - {len(findings)} of {source_count} declared floor(s) violate {manifest.as_posix()}:"
    ]
    for f in findings:
        actual = str(f.declared) if f.declared is not None else "none"
        lines.append(f"  - {f.path} ({f.unit}): pinned minimum {f.pinned}, actual {actual} - {f.detail}")
    lines.append("")
    lines.append(
        f"  Lowering a coverage floor is a deliberate, reviewed act: raise the value back to at "
        f"least its pinned minimum, or change the pin in {manifest.as_posix()} - a protected path "
        f"needing a CODEOWNER review and the eval-change-approved label."
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Assert every declared coverage floor is at or above its pinned minimum.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="floors manifest, relative to --repo")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the coverage-floor check and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    root = Path(args.repo).resolve()
    manifest = Path(args.manifest)
    try:
        units = load_manifest(root / manifest)
    except ManifestError as exc:
        logger.error("%s", exc)
        print(f"coverage-floors: usage error - {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    findings = check(root, units)

    if args.json:
        print(
            json.dumps(
                {
                    "passed": not findings,
                    "manifest": manifest.as_posix(),
                    "units": sorted((asdict(u) for u in units), key=lambda u: str(u["name"])),
                    "findings": [asdict(f) for f in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text(findings, units, manifest))

    if findings:
        logger.error("%d declared coverage floor(s) below the pinned minimum", len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
