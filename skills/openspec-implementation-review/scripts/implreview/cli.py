"""Argparse wiring for the ``openspec-implementation-review`` skill.

Five subcommands, each a thin shell around the library modules -- see their own docstrings
for the actual logic:

- ``locate``   -- find the change dir, report task-completion state.
- ``detect``   -- report whether the plugin dispatch path looks available.
- ``plan``     -- locate + detect, then print/write the dispatch prompt(s) to actually send.
- ``compose``  -- assemble ``review.md`` from a dispatched reviewer's output.
- ``validate`` -- structurally check an existing ``review.md``.

Exit codes are deliberately distinct per failure kind so a caller (human or agent) can branch
on them without parsing text: ``2`` is a locate/usage failure (change not found, bad args),
``1`` is a found-but-not-ready or found-but-invalid result, ``0`` is success.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from .compose import compose_review
from .detect import DispatchPath, detect_dispatch_path
from .locate import ChangeNotFoundError, current_tree_sha, locate_change
from .prompts import build_dispatch_plan
from .validate import validate_review_file


def _to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/Path/tuple into plain JSON-safe types."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def _print_json(value: Any) -> None:
    """Every subcommand's ``--json`` branch funnels through here -- the only JSON printer."""
    print(json.dumps(_to_jsonable(value), indent=2, sort_keys=True))


def _resolve_tree_sha(repo_root: Path, given: str | None) -> str:
    if given:
        return given
    return current_tree_sha(repo_root) or "<unknown -- not a git repository or git unavailable>"


def _cmd_locate(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    try:
        change = locate_change(repo_root, args.change)
    except ChangeNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        _print_json(change)
    else:
        status = change.tasks_status
        print(f"change: {change.change_id}")
        print(f"dir: {change.change_dir}")
        print(f"inferred: {change.inferred} (from: {change.inferred_from})")
        if status is None:
            print("tasks.md: not found")
        else:
            print(
                f"tasks.md: {status.checked}/{status.total} checked ({'complete' if status.complete else 'incomplete'})"
            )
            for item in status.unchecked_items:
                print(f"  - [ ] {item}")
        print(f"review.md exists: {change.review_exists}")

    if change.tasks_status is not None and not change.tasks_status.complete and not args.allow_incomplete:
        print(
            "error: tasks.md is not fully checked off; pass --allow-incomplete to review anyway",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    detection = detect_dispatch_path(repo_root)
    if args.json:
        _print_json(detection)
        return 0
    print(f"charters_present: {detection.charters_present}")
    print(f"plugin_manifest_present: {detection.plugin_manifest_present}")
    print(f"claude_plugin_root: {detection.claude_plugin_root}")
    print(f"env_signals_plugin_loaded: {detection.env_signals_plugin_loaded}")
    print(f"recommended_path: {detection.recommended_path}")
    print(f"confidence: {detection.confidence}")
    print(f"reason: {detection.reason}")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    try:
        change = locate_change(repo_root, args.change)
    except ChangeNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.force_path:
        path: DispatchPath = args.force_path
    else:
        path = detect_dispatch_path(repo_root).recommended_path

    tree_sha = _resolve_tree_sha(repo_root, args.tree_sha)
    dispatch_plan = build_dispatch_plan(change, tree_sha, path)

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for prompt in dispatch_plan.prompts:
            out_path = out_dir / f"{prompt.subagent_type}.md"
            out_path.write_text(prompt.prompt, encoding="utf-8", newline="\n")
            print(f"wrote {out_path}")
        return 0

    if args.json:
        _print_json(dispatch_plan)
        return 0

    print(f"dispatch path: {dispatch_plan.path}")
    for prompt in dispatch_plan.prompts:
        print(f"\n===== dispatch: {prompt.subagent_type} =====\n")
        print(prompt.prompt)
    return 0


def _cmd_compose(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    try:
        change = locate_change(repo_root, args.change)
    except ChangeNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
    tree_sha = _resolve_tree_sha(repo_root, args.tree_sha)
    path: DispatchPath = args.dispatch_path or detect_dispatch_path(repo_root).recommended_path

    result = compose_review(
        change.review_path,
        change_id=change.change_id,
        tree_sha=tree_sha,
        dispatch_path=path,
        body=body,
        date=args.date,
        overwrite=args.overwrite,
    )
    print(f"{result.mode}: {result.path}")
    if not result.validation.ok:
        print("structural validation FAILED:", file=sys.stderr)
        for err in result.validation.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"structural validation OK (verdict: {result.validation.verdict})")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    if args.path:
        result = validate_review_file(Path(args.path), expected_change_id=args.change)
    else:
        if not args.change:
            print("error: --path or --change is required", file=sys.stderr)
            return 2
        try:
            change = locate_change(repo_root, args.change)
        except ChangeNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        result = validate_review_file(change.review_path, expected_change_id=change.change_id)

    if args.json:
        _print_json(result)
    else:
        print(f"ok: {result.ok}")
        print(f"verdict: {result.verdict}")
        if result.errors:
            print("errors:")
            for err in result.errors:
                print(f"  - {err}")
    return 0 if result.ok else 1


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Repo root (default: current directory).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="implreview",
        description="Locate, detect, compose, and validate an OpenSpec implementation review.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_locate = sub.add_parser("locate", help="Locate an OpenSpec change and report task-completion state.")
    _add_common_args(p_locate)
    p_locate.add_argument("--change", default=None, help="Change id; inferred from branch/commits if omitted.")
    p_locate.add_argument("--allow-incomplete", action="store_true", help="Do not fail on an incomplete tasks.md.")
    p_locate.set_defaults(func=_cmd_locate)

    p_detect = sub.add_parser("detect", help="Report whether the plugin dispatch path looks available.")
    _add_common_args(p_detect)
    p_detect.set_defaults(func=_cmd_detect)

    p_plan = sub.add_parser("plan", help="Compose the dispatch prompt(s) to send for this change.")
    _add_common_args(p_plan)
    p_plan.add_argument("--change", default=None, help="Change id; inferred from branch/commits if omitted.")
    p_plan.add_argument("--tree-sha", default=None, help="Tree SHA to pin (default: git rev-parse HEAD).")
    p_plan.add_argument("--force-path", choices=("plugin", "degraded"), default=None, help="Override detection.")
    p_plan.add_argument("--out-dir", default=None, help="Write each prompt to <out-dir>/<subagent-type>.md.")
    p_plan.set_defaults(func=_cmd_plan)

    p_compose = sub.add_parser("compose", help="Assemble review.md from a dispatched reviewer's output.")
    _add_common_args(p_compose)
    p_compose.add_argument("--change", required=True, help="Change id.")
    p_compose.add_argument(
        "--body-file", required=True, help="File with the reviewer's markdown output ('-' for stdin)."
    )
    p_compose.add_argument("--tree-sha", default=None, help="Tree SHA to record (default: git rev-parse HEAD).")
    p_compose.add_argument("--dispatch-path", choices=("plugin", "degraded"), default=None, help="Which path was used.")
    p_compose.add_argument("--date", default=None, help="Override the follow-up date (default: today, YYYY-MM-DD).")
    p_compose.add_argument(
        "--overwrite", action="store_true", help="Replace an existing review.md instead of appending."
    )
    p_compose.set_defaults(func=_cmd_compose)

    p_validate = sub.add_parser("validate", help="Structurally validate an existing review.md.")
    _add_common_args(p_validate)
    p_validate.add_argument("--change", default=None, help="Change id (resolves its review.md).")
    p_validate.add_argument("--path", default=None, help="Explicit path to a review.md, instead of --change.")
    p_validate.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = args.func
    result: int = func(args)
    return result


__all__ = ["build_parser", "main"]
