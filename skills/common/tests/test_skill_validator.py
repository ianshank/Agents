"""Direct unit tests for ``skills/common/skill_validator.py``.

This exercises the shared grading engine's own internals — frontmatter parsing,
eval-assertion grading, and ``_run_eval``'s real subprocess mechanics (the
python3-token rewrite, shell-quoting, timeout handling) — by importing
``skill_validator`` directly. That is a different contract from the root
``tests/test_validate_skill.py`` suite, which exercises the vendored
``scripts/validate_skill.py`` wrapper's CLI/re-export surface (and, for
``_run_eval``/``grade_idempotent``, monkeypatches around the real subprocess calls).
Nothing here duplicates that file; see ``docs/plans/orbital-drift-alignment/PLAN.md``
Phase 3 for the coverage gap this closes.

Two gaps motivated this file directly: ``grade_file_exists`` had no test anywhere
(only incidental line coverage as a side effect of an unrelated structural-error
test), and ``_run_eval``'s real subprocess mechanics were monkeypatched around
rather than exercised. Both get dedicated, real-subprocess coverage below. The rest
of this file exists because reaching this package's own 95% branch-coverage floor,
measured standalone (``cd skills/common && pytest tests --cov=skill_validator``),
requires covering the module's full surface independently of the root suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
import skill_validator
from skill_validator import (
    _exec,
    _run_eval,
    _run_one_eval,
    _validate_eval_shape,
    check_behavioral,
    check_structural,
    first_path_token,
    grade,
    grade_command_exit_zero,
    grade_exit_nonzero,
    grade_exit_zero,
    grade_file_contains,
    grade_file_exists,
    grade_idempotent,
    grade_output_contains,
    load_evals,
    parse_frontmatter,
)

# A timeout short enough to keep the suite fast, but long enough (vs. the sleep
# command below, and vs. interpreter-startup overhead) to give slower CI runners a
# safe margin before the real subprocess is actually killed. Empirically, a 1s
# timeout against a 3s sleep raises TimeoutExpired at ~1.0-1.1s wall clock.
_SHORT_TIMEOUT = 1
_SLEEP_CMD = 'python3 -c "import time; time.sleep(3)"'

# The ordinary (non-timeout-testing) timeout budget passed to _run_eval/_exec/
# _run_one_eval/check_behavioral everywhere else below. Every call site here is
# expected to complete in well under a second; 10s is just a generous margin over
# interpreter-startup overhead on a slow CI runner.
_TIMEOUT = 10


def _write_skill_md(skill_dir, name: str = "my-skill") -> None:
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when the user asks to validate a skill.\n---\nBody",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# get_validator_module_path
# ---------------------------------------------------------------------------


def test_get_validator_module_path_returns_this_files_directory():
    expected = os.path.dirname(os.path.abspath(skill_validator.__file__))
    assert skill_validator.get_validator_module_path() == expected


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid_yaml_dict(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: my-skill\ndescription: Use whenever needed.\n---\nBody.\n", encoding="utf-8")
    fm, nlines = parse_frontmatter(str(skill_md))
    assert fm == {"name": "my-skill", "description": "Use whenever needed."}
    assert nlines == 5


def test_parse_frontmatter_no_delimiters_returns_none(tmp_path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("Just prose, no frontmatter.\n", encoding="utf-8")
    fm, nlines = parse_frontmatter(str(skill_md))
    assert fm is None
    assert nlines == 1


def test_parse_frontmatter_valid_yaml_non_dict_falls_back(tmp_path):
    """A frontmatter block that is syntactically valid YAML but not a mapping (a
    top-level list) must not be returned as-is: it falls through to the tolerant
    line-by-line fallback parser, which finds no ``key: value`` line in a list."""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\n- item1\n- item2\n---\nBody.\n", encoding="utf-8")
    fm, _nlines = parse_frontmatter(str(skill_md))
    assert fm == {}


def test_parse_frontmatter_yaml_exception_falls_back_with_folded_continuation(tmp_path):
    """A block that raises out of ``yaml.safe_load`` (invalid syntax anywhere in it)
    is caught and the *entire* raw block is reprocessed by the fallback parser --
    including a blank line and a ``#`` comment line (both skipped), a folded
    (indented) continuation line for an earlier key, and a later, unrelated key
    that is what actually breaks the YAML parse."""
    block = "name: my-skill\n\n# a comment line\nnotes: primary line\n  continued line indented\nbroken:\n\tvalue\n"
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(f"---\n{block}---\nBody.\n", encoding="utf-8")
    fm, _nlines = parse_frontmatter(str(skill_md))
    assert fm == {
        "name": "my-skill",
        "notes": "primary line continued line indented",
        "broken": "value",
    }


# ---------------------------------------------------------------------------
# load_evals
# ---------------------------------------------------------------------------


def test_load_evals_missing_file_returns_none(tmp_path):
    errs: list[str] = []
    assert load_evals(str(tmp_path), "evals/evals.json", errs) is None
    assert errs == []


def test_load_evals_invalid_json_syntax_is_a_readable_error(tmp_path):
    (tmp_path / "evals.json").write_text("{not valid json", encoding="utf-8")
    errs: list[str] = []
    assert load_evals(str(tmp_path), "evals.json", errs) is None
    assert any("cannot parse evals.json" in e for e in errs)


def test_load_evals_top_level_list_is_a_readable_error(tmp_path):
    (tmp_path / "evals.json").write_text(json.dumps([{"id": "x"}]), encoding="utf-8")
    errs: list[str] = []
    assert load_evals(str(tmp_path), "evals.json", errs) is None
    assert any("must be a JSON object" in e for e in errs)


def test_load_evals_valid_dict(tmp_path):
    (tmp_path / "evals.json").write_text(json.dumps({"skill": "x", "evals": []}), encoding="utf-8")
    errs: list[str] = []
    data = load_evals(str(tmp_path), "evals.json", errs)
    assert data == {"skill": "x", "evals": []}
    assert errs == []


# ---------------------------------------------------------------------------
# first_path_token
# ---------------------------------------------------------------------------


def test_first_path_token_finds_first_slash_containing_non_flag_token():
    assert first_path_token("run -v bin/tool.sh arg") == "bin/tool.sh"


def test_first_path_token_skips_flag_tokens_even_with_a_slash():
    assert first_path_token("cmd --path=/etc/foo -x") is None


def test_first_path_token_no_slash_tokens_returns_none():
    assert first_path_token("echo hello world") is None


def test_first_path_token_empty_command_returns_none():
    assert first_path_token("") is None


# ---------------------------------------------------------------------------
# _check_eval_file_refs (via check_structural)
# ---------------------------------------------------------------------------


def test_check_eval_file_refs_warns_only_for_missing_scripts_or_bin_refs(tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    _write_skill_md(skill_dir)
    (skill_dir / "bin").mkdir()
    (skill_dir / "bin" / "present.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps(
            {
                "skill": "my-skill",
                "evals": [
                    {"id": "missing-setup", "setup": "scripts/setup_missing.sh"},
                    {"id": "present-run", "run": "bin/present.sh"},
                    {"id": "no-path-token", "run": "echo hello"},
                ],
            }
        ),
        encoding="utf-8",
    )
    errs, warns = check_structural(str(skill_dir), "evals/evals.json")
    assert not errs
    assert any("missing-setup" in w and "scripts/setup_missing.sh" in w for w in warns)
    assert not any("present-run" in w for w in warns)
    assert not any("no-path-token" in w for w in warns)


# ---------------------------------------------------------------------------
# check_structural: base behaviour
# ---------------------------------------------------------------------------


def test_check_structural_missing_skill_md(tmp_path):
    errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    assert "missing" in errs[0]
    assert warns == []


def test_check_structural_no_frontmatter(tmp_path):
    (tmp_path / "SKILL.md").write_text("No frontmatter here.", encoding="utf-8")
    errs, _warns = check_structural(str(tmp_path), "evals/evals.json")
    assert "no YAML frontmatter" in errs[0]


def test_check_structural_placeholders(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: {{skill-name}}\ndescription: {{placeholder}}\n---\nBody", encoding="utf-8"
    )
    errs, _warns = check_structural(str(tmp_path), "evals/evals.json")
    assert any("name' missing or placeholder" in e for e in errs)
    assert any("description' missing or placeholder" in e for e in errs)


def test_check_structural_clean_skill_has_no_errors_or_warnings(tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    _write_skill_md(skill_dir)
    errs, warns = check_structural(str(skill_dir), "evals/evals.json")
    assert errs == []
    assert warns == []


def test_check_structural_warns_on_casing_dir_mismatch_short_desc_and_length(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: MySkill\ndescription: Short.\n---\n" + "\n" * 600, encoding="utf-8")
    _errs, warns = check_structural(str(tmp_path), "evals/evals.json")
    assert any("lowercase-hyphen" in w for w in warns)
    assert any("dir" in w for w in warns)
    assert any("very short" in w for w in warns)
    assert any("trigger phrase" in w for w in warns)
    assert any("lines (>500)" in w for w in warns)


def test_check_structural_with_non_list_evals_value_does_not_crash(tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    _write_skill_md(skill_dir)
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"evals": "oops"}), encoding="utf-8")
    errs, _warns = check_structural(str(skill_dir), "evals/evals.json")  # must not raise
    assert errs == []


def test_check_structural_with_non_iterable_evals_value_does_not_crash(tmp_path):
    # A string ``evals`` value (see the test above) happens to be iterable, so a list
    # comprehension over it would also silently yield [] even without the isinstance
    # guard -- that case alone can't tell "guarded" apart from "unguarded but lucky".
    # None (JSON null) is not iterable at all: without _eval_entries's isinstance
    # check, `for ev in evals` raises TypeError. This is the case that actually
    # proves the guard, not just the fallback behavior it produces.
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    _write_skill_md(skill_dir)
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"evals": None}), encoding="utf-8")
    errs, _warns = check_structural(str(skill_dir), "evals/evals.json")  # must not raise
    assert errs == []


# ---------------------------------------------------------------------------
# _run_eval: real subprocess mechanics (no monkeypatching -- these invoke the
# actual interpreter through a real ``shell=True`` subprocess, as the brief for
# this file requires).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["python3", "python"])
def test_run_eval_rewrites_bare_python_token_to_sys_executable(token, tmp_path, monkeypatch):
    """Proves the *rewrite itself* fires, not just that PATH's own interpreter happens
    to be byte-identical to ``sys.executable`` in this sandbox (both ``python3`` and
    ``python`` on PATH here are symlinks to the very same interpreter running this
    suite, so a mutation that broke the rewrite could otherwise still pass by
    coincidence -- confirmed by hand: mutating the regex to drop the bare ``python``
    alternative left the un-monkeypatched version of this test passing under
    ``python -m pytest``, because ``sys.executable`` for a ``python``-invoked pytest
    run already equals what unrewritten ``python`` resolves to on PATH).
    ``sys.executable`` is monkeypatched to a fake interpreter that, unlike a real
    python, ignores its arguments and always emits a fixed marker -- the assertion
    below can only pass if ``_run_eval`` substituted this mocked value for the bare
    token, causing the shell to invoke the fake interpreter directly. If the rewrite
    doesn't fire, the shell instead resolves the literal token via PATH to the real
    system interpreter, which executes the ``-c`` code for real and prints the genuine
    ``sys.executable`` -- failing the assertion."""
    fake = tmp_path / "fake-interpreter"
    fake.write_text("#!/bin/sh\necho rewritten-to-fake-interpreter\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    r = _run_eval(f'{token} -c "import sys; print(sys.executable)"', ".", _TIMEOUT)
    assert r.returncode == 0
    assert r.stdout.strip() == "rewritten-to-fake-interpreter"


@pytest.mark.parametrize(
    "cmd,expected_stdout",
    [
        ("echo python.exe", "python.exe"),
        ("echo /usr/bin/python", "/usr/bin/python"),
        ("echo mypython3", "mypython3"),
        ("echo python3.11", "python3.11"),
    ],
)
def test_run_eval_does_not_rewrite_non_bare_python_tokens(cmd, expected_stdout):
    """The rewrite regex is word-bounded: a preceding path/word char, or a following
    dot/word char, excludes the match -- so these look-alikes must pass through the
    real shell untouched. Proven by ``echo`` returning the literal text back: if the
    token had been (wrongly) rewritten, stdout would be a python executable path
    instead of the literal string."""
    r = _run_eval(cmd, ".", _TIMEOUT)
    assert r.returncode == 0
    assert r.stdout.strip() == expected_stdout


@pytest.mark.parametrize(
    "dirname",
    [
        "my python bin",
        "py's $HOME (weird)",
    ],
)
def test_run_eval_quotes_sys_executable_path_containing_spaces_and_metacharacters(dirname, tmp_path, monkeypatch):
    """A ``sys.executable`` whose path contains spaces, or classically hard-to-quote
    shell metacharacters (a single quote, ``$``, parentheses -- an unescaped single
    quote inside single-quoting is a common bug), must still work as a single shell
    token after the rewrite -- proves the ``shlex.quote`` wrapping, not just the
    regex substitution. A fake wrapper interpreter is placed at the given path and
    re-execs the real interpreter."""
    wrapper_dir = tmp_path / dirname
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "python3"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(wrapper))
    r = _run_eval("python3 -c \"print('ok-from-wrapper')\"", ".", _TIMEOUT)
    assert r.returncode == 0
    assert r.stdout.strip() == "ok-from-wrapper"


def test_run_eval_shell_quoted_arguments_with_spaces_and_metacharacters_survive():
    """Arguments the eval *author* has already quoted in the command string must
    reach the child process intact through the real ``shell=True`` invocation --
    the rewrite only touches the standalone ``python``/``python3`` token, never the
    rest of the command."""
    cmd = (
        'python3 -c "import sys; [print(a) for a in sys.argv[1:]]" '
        "'arg with spaces' 'arg;with;semicolons' 'arg&&with&&ampersands' 'arg$with$dollar'"
    )
    r = _run_eval(cmd, ".", _TIMEOUT)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "arg with spaces",
        "arg;with;semicolons",
        "arg&&with&&ampersands",
        "arg$with$dollar",
    ]


def test_run_eval_stdin_is_devnull_not_the_terminal():
    """Eval commands never read from the terminal: a command reading stdin must see
    immediate EOF rather than block waiting for input, or see data meant for someone
    else.

    A naive version of this test can't tell "code explicitly redirects stdin to
    DEVNULL" apart from "code passes no stdin= at all and just inherits the parent's,
    which happens to already be empty in this sandbox" -- this pytest worker's own
    fd 0 is already ``/dev/null`` here, so both scenarios look identical if the test
    only checks for an empty read. To close that gap, this test gives *this very
    process* a real, non-empty, pending stdin by piping bytes directly onto fd 0
    (POSIX) before calling ``_run_eval``, then restores the original fd 0 afterward.
    If ``_run_eval`` ever stopped passing ``stdin=subprocess.DEVNULL`` and fell back
    to inheriting the parent's stdin, the child would see -- and echo back -- the
    piped bytes instead of empty string, and the assertion below would fail.
    (Verified by mutation: temporarily deleting the ``stdin=subprocess.DEVNULL`` kwarg
    from ``_run_eval`` makes this test fail, while the old, non-fd-swapping version of
    this test kept passing against that same mutation.)
    """
    marker = b"do-not-read-me-from-the-child\n"
    read_fd, write_fd = os.pipe()
    os.write(write_fd, marker)
    os.close(write_fd)  # EOF follows the marker bytes on the read end
    saved_stdin_fd = os.dup(0)
    try:
        os.dup2(read_fd, 0)
        os.close(read_fd)
        r = _run_eval('python3 -c "import sys; print(repr(sys.stdin.read()))"', ".", _TIMEOUT)
    finally:
        os.dup2(saved_stdin_fd, 0)
        os.close(saved_stdin_fd)
    assert r.returncode == 0
    assert r.stdout.strip() == "''"


def test_run_eval_runs_in_the_given_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    r = _run_eval("python3 -c \"import os; print(os.path.exists('marker.txt'))\"", str(tmp_path), _TIMEOUT)
    assert r.returncode == 0
    assert r.stdout.strip() == "True"


def test_run_eval_nonzero_exit_is_reported():
    r = _run_eval('python3 -c "import sys; sys.exit(7)"', ".", _TIMEOUT)
    assert r.returncode == 7


def test_run_eval_real_timeout_raises_timeout_expired():
    """A command that genuinely exceeds the timeout must raise -- asserted against a
    real, unmocked subprocess, not assumed from the ``except`` clause reading."""
    with pytest.raises(subprocess.TimeoutExpired):
        _run_eval(_SLEEP_CMD, ".", _SHORT_TIMEOUT)


# ---------------------------------------------------------------------------
# _exec: adapts _run_eval, turning a real TimeoutExpired into a None sentinel.
# ---------------------------------------------------------------------------


def test_exec_returns_completed_process_on_success():
    r = _exec('python3 -c "print(1)"', ".", _TIMEOUT)
    assert r is not None
    assert r.returncode == 0


def test_exec_returns_none_on_real_timeout():
    assert _exec(_SLEEP_CMD, ".", _SHORT_TIMEOUT) is None


# ---------------------------------------------------------------------------
# Graders
# ---------------------------------------------------------------------------


def test_grade_exit_zero_pass_fail_and_no_run():
    assert grade_exit_zero({}, 0, "", True, ".", _TIMEOUT)[0] is True
    assert grade_exit_zero({}, 1, "", True, ".", _TIMEOUT)[0] is False
    assert grade_exit_zero({}, 0, "", False, ".", _TIMEOUT)[0] is False


def test_grade_exit_nonzero_pass_fail_and_no_run():
    assert grade_exit_nonzero({}, 1, "", True, ".", _TIMEOUT)[0] is True
    assert grade_exit_nonzero({}, 0, "", True, ".", _TIMEOUT)[0] is False
    assert grade_exit_nonzero({}, 1, "", False, ".", _TIMEOUT)[0] is False


def test_grade_output_contains_pass_fail_and_no_run():
    assert grade_output_contains({"contains": "hi"}, 0, "hi there", True, ".", _TIMEOUT)[0] is True
    assert grade_output_contains({"contains": "nope"}, 0, "hi there", True, ".", _TIMEOUT)[0] is False
    passed, evidence = grade_output_contains({"contains": "hi"}, 0, "", False, ".", _TIMEOUT)
    assert passed is False
    assert "no 'run'" in evidence


def test_grade_file_contains_pass_fail_and_missing_file(tmp_path):
    (tmp_path / "test.txt").write_text("custom content", encoding="utf-8")
    assert (
        grade_file_contains({"path": "test.txt", "contains": "custom"}, 0, "", True, str(tmp_path), _TIMEOUT)[0] is True
    )
    assert (
        grade_file_contains({"path": "test.txt", "contains": "absent"}, 0, "", True, str(tmp_path), _TIMEOUT)[0]
        is False
    )
    passed, evidence = grade_file_contains(
        {"path": "missing.txt", "contains": "x"}, 0, "", True, str(tmp_path), _TIMEOUT
    )
    assert passed is False
    assert "cannot read" in evidence


def test_grade_idempotent_matching_second_run_passes():
    r = grade_idempotent({}, 0, "hello\n", True, ".", _TIMEOUT, run_cmd="python3 -c \"print('hello')\"")
    assert r[0] is True


def test_grade_idempotent_mismatched_second_run_fails():
    r = grade_idempotent({}, 0, "hello\n", True, ".", _TIMEOUT, run_cmd="python3 -c \"print('different')\"")
    assert r[0] is False
    assert "mismatch" in r[1]


def test_grade_idempotent_second_run_nonzero_exit_fails():
    r = grade_idempotent({}, 0, "", True, ".", _TIMEOUT, run_cmd='python3 -c "import sys; sys.exit(1)"')
    assert r[0] is False
    assert "second run failed" in r[1]


def test_grade_idempotent_no_run_fails():
    assert grade_idempotent({}, 0, "", False, ".", _TIMEOUT)[0] is False


def test_grade_idempotent_missing_run_cmd_fails():
    passed, evidence = grade_idempotent({}, 0, "", True, ".", _TIMEOUT, run_cmd=None)
    assert passed is False
    assert "run command is missing" in evidence


def test_grade_idempotent_real_timeout_on_second_run_fails():
    passed, evidence = grade_idempotent({}, 0, "", True, ".", _SHORT_TIMEOUT, run_cmd=_SLEEP_CMD)
    assert passed is False
    assert "timed out" in evidence


def test_grade_command_exit_zero_pass_and_fail():
    assert grade_command_exit_zero({"cmd": 'python3 -c "exit(0)"'}, 0, "", True, ".", _TIMEOUT)[0] is True
    assert grade_command_exit_zero({"cmd": 'python3 -c "exit(1)"'}, 0, "", True, ".", _TIMEOUT)[0] is False


def test_grade_command_exit_zero_real_timeout_fails():
    passed, evidence = grade_command_exit_zero({"cmd": _SLEEP_CMD}, 0, "", True, ".", _SHORT_TIMEOUT)
    assert passed is False
    assert "timed out" in evidence


def test_grade_file_exists_when_present(tmp_path):
    """Confirmed gap: grade_file_exists had no dedicated test anywhere before this
    file (only incidental line execution as a side effect of an unrelated test)."""
    (tmp_path / "present.txt").write_text("x", encoding="utf-8")
    passed, evidence = grade_file_exists({"path": "present.txt"}, 0, "", True, str(tmp_path), _TIMEOUT)
    assert passed is True
    assert "exists" in evidence
    assert "present.txt" in evidence


def test_grade_file_exists_when_absent(tmp_path):
    passed, evidence = grade_file_exists({"path": "absent.txt"}, 0, "", True, str(tmp_path), _TIMEOUT)
    assert passed is False
    assert "absent" in evidence
    assert "absent.txt" in evidence


def test_grade_file_exists_resolves_relative_to_skill_dir_not_cwd(tmp_path):
    sub = tmp_path / "sub" / "dir"
    sub.mkdir(parents=True)
    (sub / "nested.txt").write_text("x", encoding="utf-8")
    passed, _evidence = grade_file_exists({"path": "sub/dir/nested.txt"}, 0, "", True, str(tmp_path), _TIMEOUT)
    assert passed is True


def test_grade_file_exists_path_traversal_is_not_sandboxed(tmp_path):
    """Characterises current behaviour rather than asserting it is desirable:
    ``os.path.join`` + ``os.path.exists`` do not sandbox a ``..``-relative path to
    ``skill_dir`` -- a traversal string can see files outside it. evals.json is
    repo-authored, not adversarial input, so this is not treated as a vulnerability
    to fix; it pins the behaviour so a future change to it is deliberate."""
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    passed, evidence = grade_file_exists({"path": "../outside.txt"}, 0, "", True, str(skill_dir), _TIMEOUT)
    assert passed is True
    assert "exists" in evidence


def test_grade_unknown_assertion_type_fails_with_readable_evidence():
    result = grade({"type": "not_a_real_type"}, 0, "", True, ".", _TIMEOUT)
    assert result["passed"] is False
    assert "unknown assertion type" in result["evidence"]
    assert "not_a_real_type" in result["evidence"]


def test_grade_uses_text_field_as_label_when_present():
    result = grade({"type": "exit_zero", "text": "custom label"}, 0, "", True, ".", _TIMEOUT)
    assert result["text"] == "custom label"
    assert result["passed"] is True


def test_grade_falls_back_to_type_as_label_when_text_absent():
    result = grade({"type": "exit_zero"}, 0, "", True, ".", _TIMEOUT)
    assert result["text"] == "exit_zero"


# ---------------------------------------------------------------------------
# _validate_eval_shape
# ---------------------------------------------------------------------------


def test_validate_eval_shape_no_assertions_is_skipped():
    errs: list[str] = []
    assert _validate_eval_shape("e1", [], True, errs) is False
    assert any("no assertions" in e for e in errs)


def test_validate_eval_shape_executes_nothing_is_flagged_but_not_skipped():
    errs: list[str] = []
    ok = _validate_eval_shape("e1", [{"type": "file_exists", "path": "x"}], False, errs)
    assert ok is True
    assert any("executes nothing" in e for e in errs)


def test_validate_eval_shape_command_exit_zero_counts_as_executing():
    errs: list[str] = []
    ok = _validate_eval_shape("e1", [{"type": "command_exit_zero", "cmd": "echo hi"}], False, errs)
    assert ok is True
    assert not any("executes nothing" in e for e in errs)


def test_validate_eval_shape_only_existence_checks_is_flagged():
    errs: list[str] = []
    ok = _validate_eval_shape("e1", [{"type": "file_exists", "path": "x"}], True, errs)
    assert ok is True
    assert any("only existence checks" in e for e in errs)


def test_validate_eval_shape_behavioral_assertion_present_is_clean():
    errs: list[str] = []
    ok = _validate_eval_shape("e1", [{"type": "exit_zero"}], True, errs)
    assert ok is True
    assert errs == []


# ---------------------------------------------------------------------------
# _run_one_eval / check_behavioral: setup, real timeouts, end-to-end grading
# ---------------------------------------------------------------------------


def test_run_one_eval_setup_succeeds_then_run_executes(tmp_path):
    errs: list[str] = []
    ev = {
        "id": "e1",
        "setup": 'python3 -c "print(1)"',
        "run": "python3 -c \"print('done')\"",
        "assertions": [{"type": "exit_zero"}],
    }
    record = _run_one_eval(ev, str(tmp_path), _TIMEOUT, errs)
    assert record is not None
    assert errs == []
    assert record["expectations"][0]["passed"] is True


def test_run_one_eval_setup_failure_is_recorded_and_skips_run(tmp_path):
    errs: list[str] = []
    ev = {
        "id": "e1",
        "setup": 'python3 -c "import sys; sys.exit(3)"',
        "run": "python3 -c \"print('should not run')\"",
        "assertions": [{"type": "exit_zero"}],
    }
    record = _run_one_eval(ev, str(tmp_path), _TIMEOUT, errs)
    assert record is None
    assert any("setup failed (exit 3)" in e for e in errs)


def test_run_one_eval_setup_real_timeout_is_recorded(tmp_path):
    errs: list[str] = []
    ev = {"id": "e1", "setup": _SLEEP_CMD, "run": 'python3 -c "print(1)"', "assertions": [{"type": "exit_zero"}]}
    record = _run_one_eval(ev, str(tmp_path), _SHORT_TIMEOUT, errs)
    assert record is None
    assert any("setup timed out" in e for e in errs)


def test_run_one_eval_command_exit_zero_only_skips_the_run_step(tmp_path):
    """No ``run`` key at all (``has_run`` is False): a ``command_exit_zero``
    assertion executes its own command directly, so the eval still runs without
    ever entering the ``has_run`` branch that drives ``run_rc``/``run_out``."""
    errs: list[str] = []
    ev = {"id": "e1", "assertions": [{"type": "command_exit_zero", "cmd": 'python3 -c "exit(0)"'}]}
    record = _run_one_eval(ev, str(tmp_path), _TIMEOUT, errs)
    assert record is not None
    assert errs == []
    assert record["expectations"][0]["passed"] is True


def test_run_one_eval_run_real_timeout_is_recorded(tmp_path):
    errs: list[str] = []
    ev = {"id": "e1", "run": _SLEEP_CMD, "assertions": [{"type": "exit_zero"}]}
    record = _run_one_eval(ev, str(tmp_path), _SHORT_TIMEOUT, errs)
    assert record is not None
    assert any("run timed out" in e for e in errs)
    assert record["expectations"][0]["evidence"] == "run exit=124"


def test_check_behavioral_end_to_end_writes_grading_json(tmp_path):
    (tmp_path / "evals.json").write_text(
        json.dumps(
            {
                "skill": "my-skill",
                "evals": [
                    {
                        "id": "test",
                        "run": "python3 -c \"print('success')\"",
                        "assertions": [{"type": "exit_zero"}, {"type": "output_contains", "contains": "success"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errs = check_behavioral(str(tmp_path), "evals.json", _TIMEOUT)
    assert errs == []
    grading = tmp_path / ".skill-validation" / "grading.json"
    assert grading.is_file()
    data = json.loads(grading.read_text(encoding="utf-8"))
    assert data["results"][0]["eval_id"] == "test"


def test_check_behavioral_missing_evals_file_is_a_readable_error(tmp_path):
    errs = check_behavioral(str(tmp_path), "evals.json", _TIMEOUT)
    assert any("needs a parseable" in e for e in errs)


def test_check_behavioral_non_dict_eval_entries_are_ignored(tmp_path):
    (tmp_path / "evals.json").write_text(
        json.dumps(
            {
                "skill": "my-skill",
                "evals": [
                    "bogus-string-entry",
                    {"id": "real", "run": "python3 -c \"print('ok')\"", "assertions": [{"type": "exit_zero"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    errs = check_behavioral(str(tmp_path), "evals.json", _TIMEOUT)  # must not raise on the string entry
    assert errs == []


def test_check_behavioral_skips_evals_with_no_assertions_but_continues(tmp_path):
    (tmp_path / "evals.json").write_text(
        json.dumps(
            {
                "skill": "my-skill",
                "evals": [
                    {"id": "no-asserts", "run": 'python3 -c "print(1)"'},
                    {"id": "real", "run": 'python3 -c "print(2)"', "assertions": [{"type": "exit_zero"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    errs = check_behavioral(str(tmp_path), "evals.json", _TIMEOUT)
    assert any("no-asserts" in e and "no assertions" in e for e in errs)
    grading = json.loads((tmp_path / ".skill-validation" / "grading.json").read_text(encoding="utf-8"))
    assert [r["eval_id"] for r in grading["results"]] == ["real"]
