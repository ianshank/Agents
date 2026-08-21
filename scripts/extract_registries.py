#!/usr/bin/env python3
"""Extract component registries and registered items via AST analysis.

Provides reusable AST-based extraction of:
1. Dynamic `Registry` variable declarations from `plugins.py`.
2. All `@<REGISTRY>.register(...)` decorator calls across source files.
3. Drift verification against markdown documentation tables and listings.

Usage:
    python scripts/extract_registries.py --check
    python scripts/extract_registries.py --json
    python scripts/extract_registries.py --src src/eval_harness --plugins src/eval_harness/plugins.py
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import pathlib
import re
import sys
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger("extract_registries")


def configure_logging(verbose: bool = False) -> None:
    """Configure standard logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def discover_registries(plugins_path: str | pathlib.Path) -> dict[str, str]:
    """Dynamically discover Registry instance variables in plugins.py via AST.

    Args:
        plugins_path: Path to the plugins.py file.

    Returns:
        Mapping from registry variable name (e.g. 'SCORERS') to doc section key (e.g. 'scorers').
    """
    path = pathlib.Path(plugins_path)
    if not path.is_file():
        logger.warning("Plugins file not found: %s", path)
        return {}

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        logger.error("Failed to parse plugins file %s: %s", path, exc)
        return {}

    registries: dict[str, str] = {}

    for node in tree.body:
        target_name: str | None = None
        call_node: ast.Call | None = None

        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            if isinstance(node.target, ast.Name):
                target_name = node.target.id
            call_node = node.value
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if node.targets and isinstance(node.targets[0], ast.Name):
                target_name = node.targets[0].id
            call_node = node.value

        if target_name and call_node:
            func_id = getattr(call_node.func, "id", "")
            if func_id == "Registry" and call_node.args:
                first_arg = call_node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    kind = first_arg.value
                    key = kind + "s" if not kind.endswith("s") else kind
                    registries[target_name] = key

    logger.debug("Discovered %d registries: %s", len(registries), registries)
    return registries


def _extract_string_value(node: ast.AST) -> str | None:
    """Extract string value from an AST node if constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_decorator_component_name(dec: ast.Call) -> str | None:
    """Extract component name from positional or keyword args in @REGISTRY.register."""
    if dec.args:
        comp_name = _extract_string_value(dec.args[0])
        if comp_name:
            return comp_name

    if dec.keywords:
        for kw in dec.keywords:
            if kw.arg in ("name", "key"):
                comp_name = _extract_string_value(kw.value)
                if comp_name:
                    return comp_name

    return None


def _process_file_decorators(
    py_file: pathlib.Path,
    target_keys: set[str] | None,
    found: dict[str, set[str]],
) -> None:
    """Scan a single Python file for registration decorators and populate `found`."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError) as exc:
        logger.debug("Skipping unparseable python file %s: %s", py_file, exc)
        return

    for node in ast.walk(tree):
        decorators: list[ast.expr] = getattr(node, "decorator_list", [])
        for dec in decorators:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "register"):
                continue

            val = dec.func.value
            if not isinstance(val, ast.Name):
                continue

            reg_name = val.id
            if target_keys is not None and reg_name not in target_keys:
                continue

            if reg_name not in found:
                found[reg_name] = set()

            comp_name = _extract_decorator_component_name(dec)
            if comp_name:
                found[reg_name].add(comp_name)
                logger.debug("Found component: %s -> %s in %s", reg_name, comp_name, py_file)


def extract_components(
    src_dir: str | pathlib.Path,
    registries: dict[str, str] | None = None,
) -> dict[str, set[str]]:
    """Scan source directory for `@<REGISTRY>.register(...)` decorators via AST.

    Args:
        src_dir: Root directory of source files to scan.
        registries: Mapping of registry variables to keys. If None, all registries found will be tracked.

    Returns:
        Mapping from registry variable name to set of registered component names.
    """
    path = pathlib.Path(src_dir)
    if not path.is_dir():
        logger.warning("Source directory not found: %s", path)
        return {}

    target_keys = set(registries.keys()) if registries is not None else None
    found: dict[str, set[str]] = {k: set() for k in target_keys} if target_keys else {}

    for py_file in sorted(path.rglob("*.py")):
        _process_file_decorators(py_file, target_keys, found)

    return found


def extract_section_text(doc_content: str, key: str) -> str | None:
    """Extract documentation section text for a given registry key."""
    # Pattern 1: Indented block e.g. "  scorers/\n    accuracy\n    ..."
    m1 = re.search(rf"^  {re.escape(key)}/\s+(.*?)(?=^  \w+[/.]|\Z)", doc_content, re.M | re.S)
    if m1:
        return m1.group(1)

    # Pattern 2: Markdown table cell e.g. "| `scorers/` | accuracy, ... |"
    m2 = re.search(rf"\|\s*`?{re.escape(key)}/?`?\s*\|([^|]*)\|", doc_content)
    if m2:
        return m2.group(1)

    # Pattern 3: Heading or list item
    m3 = re.search(
        rf"(?:^\s*#+\s+[^\n]*{re.escape(key)}[^\n]*|^\s*[*+-]\s+`?{re.escape(key)}`?:?[^\n]*)\s*\n([\s\S]+?)(?=\n\s*#+|\Z)",
        doc_content,
        re.M,
    )
    if m3:
        return m3.group(1)

    return None


def check_docs_drift(
    src_dir: str | pathlib.Path = "src/eval_harness",
    plugins_path: str | pathlib.Path = "src/eval_harness/plugins.py",
    doc_paths: Sequence[str | pathlib.Path] | None = None,
) -> list[str]:
    """Check that all registered components are documented in the specified markdown docs.

    Returns:
        List of problem descriptions (empty if no drift).
    """
    registries = discover_registries(plugins_path)
    if not registries:
        return ["No registries discovered from plugins file"]

    found = extract_components(src_dir, registries)
    problems: list[str] = []

    if doc_paths is None:
        doc_paths = ["README.md", pathlib.Path(src_dir) / "README.md"]

    docs: dict[str, str] = {}
    for doc_path in doc_paths:
        p = pathlib.Path(doc_path)
        if p.is_file():
            try:
                docs[str(p)] = p.read_text(encoding="utf-8")
            except OSError as exc:
                problems.append(f"Failed to read doc file {p}: {exc}")
        else:
            logger.debug("Doc file not found, skipping: %s", p)

    for var, key in registries.items():
        names = found.get(var, set())
        if not names:
            problems.append(f"no @{var}.register(...) found - extractor may be broken or registry empty")
            continue

        for doc_name, doc_content in docs.items():
            section_text = extract_section_text(doc_content, key)
            if section_text is None:
                continue

            missing = sorted(n for n in names if not re.search(rf"\b{re.escape(str(n))}\b", section_text))
            if missing:
                problems.append(f"{doc_name}: {key}/ omits registered component(s): {missing}")

    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for extracting registries and checking doc drift."""
    parser = argparse.ArgumentParser(description="Extract component registries and check documentation drift.")
    parser.add_argument(
        "--src", default="src/eval_harness", help="Source directory containing components (default: src/eval_harness)"
    )
    parser.add_argument(
        "--plugins", default="src/eval_harness/plugins.py", help="Path to plugins.py defining Registry instances"
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=["README.md", "src/eval_harness/README.md"],
        help="Markdown docs to check for component mentions",
    )
    parser.add_argument("--json", action="store_true", help="Output discovered registries and components as JSON")
    parser.add_argument(
        "--check", action="store_true", help="Assert that markdown docs match component registries (exit 1 on drift)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    registries = discover_registries(args.plugins)
    found = extract_components(args.src, registries)

    if args.json:
        payload: dict[str, Any] = {
            "registries": registries,
            "components": {k: sorted(list(v)) for k, v in found.items()},
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.check or not args.json:
        problems = check_docs_drift(args.src, args.plugins, args.docs)
        if problems:
            print("REGISTRY DRIFT DETECTED:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("READMEs match the component registries:", {k: len(v) for k, v in found.items()})

    return 0


if __name__ == "__main__":
    sys.exit(main())
