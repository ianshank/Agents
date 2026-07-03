#!/usr/bin/env python3
"""Validate a skill end to end.

  python scripts/validate_skill.py --skill . --tier structural
  python scripts/validate_skill.py --skill . --tier structural,behavioral

structural = no side effects; behavioral = runs the task and checks real outputs.
Behavioral writes only under <skill>/.skill-validation/. Exit 0 iff every selected check passes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

BEHAVIORAL_TYPES: set[str] = {"exit_zero", "output_contains", "file_contains", "command_exit_zero"}
WORKDIR: str = ".skill-validation"


def parse_frontmatter(skill_md: str) -> tuple[dict[str, str] | None, int]:
    """Return (frontmatter_dict_or_None, line_count). Prefer real YAML; fall back tolerantly."""
    with open(skill_md, encoding="utf-8") as f:
        text = f.read()
    nlines = len(text.splitlines())
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None, nlines
    block = m.group(1)
    try:
        import yaml

        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return {str(k): ("" if v is None else str(v)) for k, v in data.items()}, nlines
    except Exception:
        pass
    fm: dict[str, str] = {}
    key: str | None = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            fm[key] = val.strip()
        elif key and line[0].isspace():  # folded continuation
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, nlines


def load_evals(skill_dir: str, evals_path: str, errs: list[str]) -> dict[str, Any] | None:
    path = evals_path if os.path.isabs(evals_path) else os.path.join(skill_dir, evals_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError) as e:
        errs.append(f"cannot parse {evals_path}: {e}")
        return None


def first_path_token(cmd: str) -> str | None:
    for tok in cmd.split():
        if "/" in tok and not tok.startswith("-"):
            return tok
    return None


def check_structural(skill_dir: str, evals_path: str) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return [f"missing {skill_md}"], []
    fm, nlines = parse_frontmatter(skill_md)
    if fm is None:
        return ["SKILL.md has no YAML frontmatter (--- ... ---)"], []
    name = fm.get("name", "")
    desc = fm.get("description", "")
    if not name or "{{" in name:
        errs.append(f"frontmatter 'name' missing or placeholder: {name!r}")
    else:
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            warns.append(f"name {name!r} isn't lowercase-hyphen; some loaders require that")
        dirbase = os.path.basename(os.path.abspath(skill_dir))
        if dirbase != name:
            warns.append(f"dir '{dirbase}' != skill name '{name}'")
    if not desc or "{{" in desc:
        errs.append("frontmatter 'description' missing or placeholder (it is the only trigger signal)")
    else:
        if len(desc) < 40:
            warns.append("description very short; triggering will be weak")
        if not re.search(r"\b(use|when|whenever)\b", desc, re.I):
            warns.append("description lacks a 'when to use' cue; add a trigger phrase")
    if nlines > 500:
        warns.append(f"SKILL.md is {nlines} lines (>500); move detail into references/")
    spec = load_evals(skill_dir, evals_path, errs)  # missing evals.json is fine at this tier
    if spec:
        for ev in spec.get("evals", []):
            for key in ("run", "setup"):
                cmd = ev.get(key)
                if cmd:
                    tok = first_path_token(cmd)
                    if (
                        tok
                        and tok.split("/")[0] in ("scripts", "bin")
                        and not os.path.exists(os.path.join(skill_dir, tok))
                    ):
                        warns.append(f"eval {ev.get('id', '?')}: {key} references missing file {tok}")
    return errs, warns


def grade(
    a: dict[str, Any],
    run_rc: int,
    run_out: str,
    has_run: bool,
    skill_dir: str,
    timeout: int,
) -> dict[str, Any]:
    t = a.get("type")
    label = a.get("text") or t

    def res(p: bool, ev: str) -> dict[str, Any]:
        return {"text": label, "passed": bool(p), "evidence": ev}

    if t == "exit_zero":
        if not has_run:
            return res(False, "exit_zero asserted but eval has no 'run' — nothing executed")
        return res(run_rc == 0, f"run exit={run_rc}")
    if t == "output_contains":
        if not has_run:
            return res(False, "output_contains asserted but eval has no 'run'")
        needle = a.get("contains", "")
        return res(needle in run_out, f"stdout {'has' if needle in run_out else 'missing'} {needle!r}")
    if t == "file_exists":
        p = os.path.join(skill_dir, a["path"])
        ex = os.path.exists(p)
        return res(ex, f"{a['path']} {'exists' if ex else 'absent'}")
    if t == "file_contains":
        p = os.path.join(skill_dir, a["path"])
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError as e:
            return res(False, f"cannot read {a['path']}: {e}")
        needle = a.get("contains", "")
        return res(needle in body, f"{a['path']} {'contains' if needle in body else 'lacks'} {needle!r}")
    if t == "command_exit_zero":
        try:
            r = subprocess.run(
                a["cmd"],
                shell=True,
                cwd=skill_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return res(r.returncode == 0, f"`{a['cmd']}` exit={r.returncode}")
        except subprocess.TimeoutExpired:
            return res(False, f"`{a['cmd']}` timed out after {timeout}s")
    return res(False, f"unknown assertion type {t!r}")


def check_behavioral(skill_dir: str, evals_path: str, timeout: int) -> list[str]:
    errs: list[str] = []
    results: list[dict[str, Any]] = []
    spec = load_evals(skill_dir, evals_path, errs)
    if spec is None:
        errs.append(f"behavioral tier needs a parseable {evals_path}")
        return errs
    work = os.path.join(skill_dir, WORKDIR)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    for ev in spec.get("evals", []):
        eid = ev.get("id", "?")
        asserts = ev.get("assertions", [])
        has_run = bool(ev.get("run"))
        if not asserts:
            errs.append(f"eval {eid}: no assertions")
            continue
        if not (has_run or any(a.get("type") == "command_exit_zero" for a in asserts)):
            errs.append(f"eval {eid}: executes nothing (needs a 'run' or a command_exit_zero assertion)")
        if not any(a.get("type") in BEHAVIORAL_TYPES for a in asserts):
            errs.append(f"eval {eid}: only existence checks — add a behavioral assertion")
        if ev.get("setup"):
            try:
                sp = subprocess.run(
                    ev["setup"],
                    shell=True,
                    cwd=skill_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                errs.append(f"eval {eid}: setup timed out after {timeout}s")
                continue
            if sp.returncode != 0:
                detail = (sp.stdout + sp.stderr).strip()[:500]
                errs.append(f"eval {eid}: setup failed (exit {sp.returncode}): {detail}")
                continue
        run_rc, run_out = 0, ""
        if has_run:
            try:
                r = subprocess.run(
                    ev["run"],
                    shell=True,
                    cwd=skill_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                run_rc, run_out = r.returncode, (r.stdout + r.stderr)
            except subprocess.TimeoutExpired:
                run_rc, run_out = 124, f"[timeout after {timeout}s]"
                errs.append(f"eval {eid}: run timed out after {timeout}s")
        graded = [grade(a, run_rc, run_out, has_run, skill_dir, timeout) for a in asserts]
        for g in graded:
            if not g["passed"]:
                errs.append(f"eval {eid}: {g['text']} — {g['evidence']}")
        results.append(
            {
                "eval_id": eid,
                "prompt": ev.get("prompt", ""),
                "expectations": graded,
            }
        )
    with open(os.path.join(work, "grading.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2)
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default=".")
    ap.add_argument("--evals", default="evals/evals.json")
    ap.add_argument("--tier", default="structural")
    ap.add_argument("--timeout", type=int, default=120, help="per-command timeout in seconds")
    args = ap.parse_args()
    tiers = {t.strip() for t in args.tier.split(",") if t.strip()}
    errs: list[str] = []
    warns: list[str] = []
    if "structural" in tiers:
        e, w = check_structural(args.skill, args.evals)
        errs += e
        warns += w
    if "behavioral" in tiers:
        errs += check_behavioral(args.skill, args.evals, args.timeout)
    for warning in warns:
        print(f"[warn] {warning}")
    if errs:
        print("SKILL VALIDATION FAILED:\n  - " + "\n  - ".join(errs))
        return 1
    print(f"OK: skill passed tier(s) {sorted(tiers)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
