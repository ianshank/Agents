"""Tests for scripts/workflow_paths.py.

The logic this module covers used to live inline in
``.github/workflows/required-check-stubs.yml``, where no test could reach it.
That mattered: its hand-rolled YAML reader returned a *truncated* glob list on
three realistic inputs rather than failing, and a short list reads as "the real
workflow did not run", which posts a stub check beside the real job. The three
inputs are pinned below as regression cases even though the parser that got them
wrong is gone -- they are the reason it is gone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import workflow_paths  # noqa: E402
from workflow_paths import (  # noqa: E402
    EXIT_USAGE_ERROR,
    WorkflowPathsError,
    glob_to_regex,
    main,
    pull_request_paths,
    workflow_runs,
)

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _workflow(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wf.yml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. The three inputs the previous inline parser got silently WRONG
# ---------------------------------------------------------------------------


class TestPreviouslyWrongInputs:
    def test_trailing_comment_on_a_list_item_does_not_truncate(self, tmp_path: Path) -> None:
        wf = _workflow(
            tmp_path,
            'name: x\non:\n  pull_request:\n    paths:\n      - "src/**"\n'
            '      - "tests/**"  # only the tests\n      - "scripts/**"\n',
        )

        assert pull_request_paths(wf) == ["src/**", "tests/**", "scripts/**"]

    def test_a_glob_containing_a_space_does_not_truncate(self, tmp_path: Path) -> None:
        wf = _workflow(
            tmp_path,
            'name: x\non:\n  pull_request:\n    paths:\n      - "src/**"\n      - "my dir/**"\n      - "scripts/**"\n',
        )

        assert pull_request_paths(wf) == ["src/**", "my dir/**", "scripts/**"]

    def test_a_negated_filter_is_refused_rather_than_misread(self, tmp_path: Path) -> None:
        """Reading ``!`` literally inverts the filter's meaning. Fail loudly."""
        wf = _workflow(
            tmp_path,
            'name: x\non:\n  pull_request:\n    paths:\n      - "src/**"\n      - "!src/vendor/**"\n',
        )

        with pytest.raises(WorkflowPathsError, match="negated"):
            pull_request_paths(wf)


# ---------------------------------------------------------------------------
# 2. Inputs the previous parser handled, pinned so the rewrite kept them
# ---------------------------------------------------------------------------


class TestStillHandled:
    def test_flow_style_list(self, tmp_path: Path) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["a/**", "b/**"]\n')

        assert pull_request_paths(wf) == ["a/**", "b/**"]

    def test_comment_on_its_own_line(self, tmp_path: Path) -> None:
        wf = _workflow(
            tmp_path,
            'name: x\non:\n  pull_request:\n    paths:\n      # why\n      - "a/**"\n      - "b/**"\n',
        )

        assert pull_request_paths(wf) == ["a/**", "b/**"]

    def test_paths_ignore_declared_before_paths_is_not_read(self, tmp_path: Path) -> None:
        wf = _workflow(
            tmp_path,
            'name: x\non:\n  pull_request:\n    paths-ignore:\n      - "docs/**"\n    paths:\n      - "src/**"\n',
        )

        assert pull_request_paths(wf) == ["src/**"]

    def test_the_norway_problem_key(self, tmp_path: Path) -> None:
        """YAML 1.1 resolves a bare ``on:`` to the boolean True."""
        wf = _workflow(tmp_path, 'name: x\n"on":\n  pull_request:\n    paths: ["a/**"]\n')

        assert pull_request_paths(wf) == ["a/**"]


# ---------------------------------------------------------------------------
# 3. Failure modes are loud, because every one of them means "post a stub"
# ---------------------------------------------------------------------------


class TestFailsClosed:
    @pytest.mark.parametrize(
        ("body", "match"),
        [
            ("name: x\non:\n  push:\n    branches: [main]\n", "pull_request"),
            ("name: x\non:\n  pull_request:\n    branches: [main]\n", "missing or empty"),
            ("name: x\non:\n  pull_request:\n    paths: []\n", "missing or empty"),
            ("just a string\n", "not a mapping"),
            ("name: x\n", "trigger mapping"),
        ],
    )
    def test_unusable_workflow_raises(self, tmp_path: Path, body: str, match: str) -> None:
        with pytest.raises(WorkflowPathsError, match=match):
            pull_request_paths(_workflow(tmp_path, body))

    def test_unreadable_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowPathsError, match="cannot be read"):
            pull_request_paths(tmp_path / "absent.yml")

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowPathsError, match="cannot be read"):
            pull_request_paths(_workflow(tmp_path, "on:\n  pull_request:\n   paths: [\n"))


# ---------------------------------------------------------------------------
# 4. GitHub glob semantics
# ---------------------------------------------------------------------------


class TestGlobSemantics:
    @pytest.mark.parametrize(
        ("glob", "path", "expected"),
        [
            ("src/**", "src/a/b/c.py", True),
            ("src/**", "src/a.py", True),
            ("src/**", "other/a.py", False),
            ("src/*.py", "src/a.py", True),
            ("src/*.py", "src/a/b.py", False),  # * must not span /
            ("src/?.py", "src/a.py", True),
            ("src/?.py", "src/ab.py", False),
            ("Makefile", "Makefile", True),
            ("Makefile", "agent-core/Makefile", False),
            ("a.b", "axb", False),  # the dot is escaped, not a wildcard
        ],
    )
    def test_matching(self, glob: str, path: str, expected: bool) -> None:
        assert bool(glob_to_regex(glob).match(path)) is expected


# ---------------------------------------------------------------------------
# 5. The trigger decision, and the real workflows in this repository
# ---------------------------------------------------------------------------


class TestWorkflowRuns:
    def test_one_matching_file_is_enough(self, tmp_path: Path) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')

        assert workflow_runs(wf, ["docs/readme.md", "src/a.py"]) is True

    def test_no_matching_file_means_it_does_not_run(self, tmp_path: Path) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')

        assert workflow_runs(wf, ["docs/readme.md"]) is False

    def test_no_changed_files_means_it_does_not_run(self, tmp_path: Path) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')

        assert workflow_runs(wf, []) is False

    @pytest.mark.parametrize(
        "workflow",
        [
            "quality-gates.yml",
            "eval-harness-ci.yml",
            "agent-core-ci.yml",
            "behavioral-regression-ci.yml",
            "flow-corpus-ci.yml",
            "claude-foundation-ci.yml",
            "architecture-drift.yml",
        ],
    )
    def test_every_real_workflow_this_gate_reads_is_parseable(self, workflow: str) -> None:
        """The stub gate names these seven; an unparseable one reds the gate and
        leaves every required context unreported."""
        assert pull_request_paths(WORKFLOW_DIR / workflow)

    def test_a_makefile_change_triggers_quality_gates(self) -> None:
        """Pins the protected-path wiring: the Makefiles that invoke the gates
        must reach the workflow that runs the protected-path guard."""
        assert workflow_runs(WORKFLOW_DIR / "quality-gates.yml", ["agent-core/Makefile"]) is True


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------


class TestCli:
    @staticmethod
    def _changed(tmp_path: Path, *paths: str) -> Path:
        f = tmp_path / "changed.txt"
        f.write_text("\n".join(paths) + "\n", encoding="utf-8")
        return f

    def test_writes_key_value_lines_to_the_output_file(self, tmp_path: Path) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')
        out = tmp_path / "out.txt"

        code = main(
            [
                "--changed-files",
                str(self._changed(tmp_path, "src/a.py")),
                "--workflow",
                f"alpha={wf}",
                "--output",
                str(out),
            ]
        )

        assert code == 0
        assert out.read_text(encoding="utf-8").strip() == "alpha=true"

    def test_appends_rather_than_truncating(self, tmp_path: Path) -> None:
        """It writes to $GITHUB_OUTPUT, which other steps also write to."""
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')
        out = tmp_path / "out.txt"
        out.write_text("preexisting=1\n", encoding="utf-8")

        main(
            [
                "--changed-files",
                str(self._changed(tmp_path, "docs/x.md")),
                "--workflow",
                f"a={wf}",
                "--output",
                str(out),
            ]
        )

        assert out.read_text(encoding="utf-8").splitlines() == ["preexisting=1", "a=false"]

    def test_prints_when_no_output_file_is_given(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        wf = _workflow(tmp_path, 'name: x\non:\n  pull_request:\n    paths: ["src/**"]\n')

        main(["--changed-files", str(self._changed(tmp_path, "src/a.py")), "--workflow", f"a={wf}"])

        assert capsys.readouterr().out.strip() == "a=true"

    def test_malformed_workflow_argument_is_a_usage_error(self, tmp_path: Path) -> None:
        code = main(["--changed-files", str(self._changed(tmp_path, "src/a.py")), "--workflow", "no-equals-sign"])

        assert code == EXIT_USAGE_ERROR

    def test_an_unusable_workflow_exits_two_rather_than_defaulting(self, tmp_path: Path) -> None:
        """The whole point of failing closed: never answer 'did not run' by accident."""
        wf = _workflow(tmp_path, "name: x\non:\n  push:\n    branches: [main]\n")

        code = main(["--changed-files", str(self._changed(tmp_path, "src/a.py")), "--workflow", f"a={wf}"])

        assert code == EXIT_USAGE_ERROR

    def test_module_exposes_a_main_for_the_workflow_to_call(self) -> None:
        assert callable(workflow_paths.main)
