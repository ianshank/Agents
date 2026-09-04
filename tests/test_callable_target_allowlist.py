"""The `callable` target must not turn a config file into arbitrary execution.

`CallableTarget` resolves ``params.path`` ("module:attribute") by importing the
module and calling the attribute with the dataset item's ``inputs``. Before this
module's guard there was no allowlist, so a config naming ``subprocess:call``
with a dict of ``inputs`` reached ``Popen`` -- which builds argv by iterating its
argument, making the dict's keys a command line. The command ran, and because
``CallableTarget.run`` reports the callable's return value, the harness reported
``error: None``: a clean-looking eval that had already executed a command.

The control cannot live in the config, because the config is the untrusted
input. It lives in ``EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST``, which the
operator sets and a config author cannot reach.

Note the suite-wide allowlist in ``conftest.py``: these tests set the variable
explicitly via ``monkeypatch`` so each one states the exact allowlist it
exercises rather than inheriting the suite's.
"""

from __future__ import annotations

import pytest

from eval_harness.core._imports import (
    ALLOW_ALL,
    CALLABLE_ALLOWLIST_ENV,
    DisallowedImportError,
    import_allowed_module,
    is_allowed,
    read_allowlist,
)
from eval_harness.core.types import EvalItem
from eval_harness.plugins import TARGETS, bootstrap

bootstrap()

#: The proof-of-concept payload from the security review, defanged. ``/bin/echo``
#: stands in for whatever the attacker would run; the mechanism under test is the
#: import, not the command.
POC_MODULE = "subprocess"
POC_ATTR = "call"


@pytest.fixture(autouse=True)
def _no_inherited_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a denied state, whatever conftest set."""
    monkeypatch.delenv(CALLABLE_ALLOWLIST_ENV, raising=False)


def _callable_target(path: str):
    """Build the target through the registry, as the engine resolves it."""
    return TARGETS.create("callable", {"path": path})


# ---------------------------------------------------------------------------
# 1. The exploit, as a regression test
# ---------------------------------------------------------------------------


class TestTheExploitIsRefused:
    def test_subprocess_target_is_refused_by_default(self) -> None:
        """The exact review finding: a config alone must not reach subprocess."""
        target = _callable_target(f"{POC_MODULE}:{POC_ATTR}")
        item = EvalItem(id="poc", inputs={"/bin/echo": 1, "EXECUTED-FROM-EVAL-CONFIG": 2})

        with pytest.raises(DisallowedImportError):
            target.run(item)

    def test_refusal_precedes_the_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A denied module's import-time side effects must never run.

        Checking after importing would be worth nothing -- importing IS the
        dangerous act for a module whose top level does work.
        """
        imported: list[str] = []
        monkeypatch.setattr(
            "eval_harness.core._imports.import_module",
            lambda name: imported.append(name),  # type: ignore[arg-type,return-value]
        )

        with pytest.raises(DisallowedImportError):
            import_allowed_module(POC_MODULE, env={})

        assert imported == []

    def test_refusal_names_the_variable_and_the_module(self) -> None:
        """An operator hitting this must be able to fix it without reading source."""
        with pytest.raises(DisallowedImportError) as excinfo:
            import_allowed_module(POC_MODULE, env={})

        message = str(excinfo.value)
        assert CALLABLE_ALLOWLIST_ENV in message
        assert POC_MODULE in message

    def test_an_existing_importerror_handler_still_catches_a_refusal(self) -> None:
        """The compatibility claim, exercised rather than restated: code that
        already handled an unresolvable path keeps working unchanged."""
        target = _callable_target(f"{POC_MODULE}:{POC_ATTR}")

        try:
            target.run(EvalItem(id="1", inputs={}))
        except ImportError as exc:
            assert CALLABLE_ALLOWLIST_ENV in str(exc)
        else:
            raise AssertionError("a refused import did not surface as an ImportError")


# ---------------------------------------------------------------------------
# 2. Matching is on module boundaries, not string prefixes
# ---------------------------------------------------------------------------


class TestBoundaryMatching:
    """The DATA_ROOT bug in miniature: a raw prefix test would admit a sibling."""

    def test_entry_admits_itself(self) -> None:
        assert is_allowed("tests", ("tests",))

    def test_entry_admits_its_submodules(self) -> None:
        assert is_allowed("tests._sut", ("tests",))
        assert is_allowed("tests.a.b.c", ("tests",))

    def test_entry_does_not_admit_a_prefix_sibling(self) -> None:
        assert not is_allowed("tests_evil", ("tests",))
        assert not is_allowed("testsuite.payload", ("tests",))

    def test_unrelated_module_is_not_admitted(self) -> None:
        assert not is_allowed("subprocess", ("tests", "json"))

    def test_sibling_prefix_is_refused_end_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")

        with pytest.raises(DisallowedImportError):
            import_allowed_module("tests_evil")


# ---------------------------------------------------------------------------
# 3. Allowlist parsing is data, not a literal at a call site
# ---------------------------------------------------------------------------


class TestAllowlistParsing:
    def test_unset_is_empty(self) -> None:
        assert read_allowlist(env={}) == ()

    def test_blank_is_empty(self) -> None:
        assert read_allowlist(env={CALLABLE_ALLOWLIST_ENV: "   "}) == ()

    def test_entries_are_split_trimmed_deduped_and_sorted(self) -> None:
        raw = " json , tests,  tests ,my_project "
        assert read_allowlist(env={CALLABLE_ALLOWLIST_ENV: raw}) == ("json", "my_project", "tests")

    def test_reads_the_live_environment_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "alpha,beta")
        assert read_allowlist() == ("alpha", "beta")


# ---------------------------------------------------------------------------
# 4. Legitimate use keeps working
# ---------------------------------------------------------------------------


class TestAllowedUseStillWorks:
    def test_allowed_module_resolves_and_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")
        target = _callable_target("tests._sut:summarize")

        out = target.run(EvalItem(id="1", inputs={"text": "x"}))

        assert out.output == "summary: x"
        assert out.error is None

    def test_one_entry_of_several_is_enough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "json,tests,my_project")
        assert _callable_target("tests._sut:summarize").run(EvalItem(id="1", inputs={"text": "y"})).output

    def test_missing_module_inside_the_allowlist_still_raises_modulenotfound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Allowed-but-absent must not be reported as a trust refusal."""
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "nonexistent")

        with pytest.raises(ModuleNotFoundError):
            import_allowed_module("nonexistent.module_xyz")

    def test_malformed_path_is_still_a_value_error(self) -> None:
        """The 'module:function' shape check is unchanged and runs first."""
        with pytest.raises(ValueError, match="must be 'module:function'"):
            _callable_target("no_colon_here").run(EvalItem(id="1", inputs={}))


# ---------------------------------------------------------------------------
# 5. The explicit escape hatch
# ---------------------------------------------------------------------------


class TestAllowAll:
    def test_wildcard_admits_anything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, ALLOW_ALL)
        assert import_allowed_module("json") is not None

    def test_wildcard_warns_every_time_it_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It must not be possible to set this in CI and quietly forget it."""
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, ALLOW_ALL)

        with caplog.at_level("WARNING", logger="eval_harness.core._imports"):
            import_allowed_module("json")

        assert any(CALLABLE_ALLOWLIST_ENV in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. A refusal aborts the run instead of becoming N identical item failures
# ---------------------------------------------------------------------------


class TestRefusalAbortsTheRun:
    """A trust decision is not an item outcome.

    Under ``item_error_policy='record'`` an ordinary target error becomes a
    visibly-failed item. A refusal must not: every item would fail identically,
    producing a "completed" run that is exactly the misleading artefact the
    record policy exists to prevent.
    """

    @staticmethod
    def _run_with_target(path: str, max_workers: int, **run_overrides: object) -> None:
        from eval_harness.config import load_config_dict
        from eval_harness.engine import EvalEngine
        from eval_harness.langfuse_client import NullLangfuseClient
        from eval_harness.version import SCHEMA_VERSION

        run: dict[str, object] = {"name": "t", "run_id": "fixed-deny", "seed": 1, "max_workers": max_workers}
        run.update(run_overrides)
        config = load_config_dict(
            {
                "schema_version": SCHEMA_VERSION,
                "run": run,
                "dataset": {
                    "type": "inline",
                    "params": {"items": [{"id": str(i), "inputs": {"q": "x"}, "expected": "x"} for i in range(3)]},
                },
                "target": {"type": "callable", "params": {"path": path}},
                "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
                "sinks": [],
            }
        )
        EvalEngine.from_config(config, langfuse_client=NullLangfuseClient()).run()

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_refusal_propagates_out_of_run(self, max_workers: int, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")

        with pytest.raises(DisallowedImportError):
            self._run_with_target(f"{POC_MODULE}:{POC_ATTR}", max_workers)

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_a_missing_module_aborts_too(self, max_workers: int, monkeypatch: pytest.MonkeyPatch) -> None:
        """An allowed-but-absent module is the same useless run as a refused one.

        Both mean the target cannot serve any item, so both abort. Treating only
        the refusal as fatal left a config typo producing a "completed" run with
        every item failed identically -- the artefact the rule exists to prevent.
        """
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "totally_absent_pkg")

        with pytest.raises(ModuleNotFoundError):
            self._run_with_target("totally_absent_pkg.mod:fn", max_workers, item_error_policy="record")

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_a_refusal_is_not_converted_into_a_scored_error(
        self, max_workers: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CallableTarget.run resolves OUTSIDE its own try/except, so the gate
        cannot be silently disabled by the broad handler that turns target
        failures into TargetOutput(error=...)."""
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")

        with pytest.raises(DisallowedImportError):
            self._run_with_target(f"{POC_MODULE}:{POC_ATTR}", max_workers, item_error_policy="record")


# ---------------------------------------------------------------------------
# 7. Allowlisting a module is not allowlisting everything reachable through it
# ---------------------------------------------------------------------------


class TestReExportBypass:
    """A one-line re-export must not launder a denied module into an allowed one.

    ``from subprocess import call`` in a package's ``__init__.py`` is utterly
    ordinary. With only the *module* gated, a config of ``my_project:call``
    then reached ``subprocess.call`` through a module the operator does trust --
    the same clean-looking eval that had already run a command. So the object's
    defining module has to clear the allowlist too.
    """

    @staticmethod
    def _package(tmp_path, name: str, body: str):
        """Build an importable package under a name unique to the calling test.

        Each test gets its own name because ``sys.modules`` caches by name: two
        tests writing different bodies to the same package name would silently
        share whichever one imported first, and the second would assert against
        the first's source.
        """
        pkg = tmp_path / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text(body, encoding="utf-8")
        return pkg.parent

    def test_reexported_denied_callable_is_refused(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = self._package(tmp_path, "reexport_denied", "from subprocess import call\n")
        monkeypatch.syspath_prepend(str(root))
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "reexport_denied")

        with pytest.raises(DisallowedImportError, match="re-exports"):
            _callable_target("reexport_denied:call").run(EvalItem(id="1", inputs={"/bin/true": 1}))

    def test_the_refusal_names_the_real_defining_module(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = self._package(tmp_path, "reexport_named", "from subprocess import call\n")
        monkeypatch.syspath_prepend(str(root))
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "reexport_named")

        with pytest.raises(DisallowedImportError) as excinfo:
            _callable_target("reexport_named:call").run(EvalItem(id="1", inputs={}))

        assert "subprocess" in str(excinfo.value)

    def test_an_internal_re_export_is_still_allowed(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The common, legitimate case must keep working: a package surfacing its
        own submodule's function at top level."""
        root = self._package(tmp_path, "reexport_internal", "from .impl import run\n")
        (root / "reexport_internal" / "impl.py").write_text("def run(inputs):\n    return 'ok'\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(root))
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "reexport_internal")

        out = _callable_target("reexport_internal:run").run(EvalItem(id="1", inputs={}))

        assert out.output == "ok"
        assert out.error is None

    def test_an_object_with_no_determinable_module_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unattributable is not the same as harmless."""
        import types

        from eval_harness.core._imports import resolve_allowed_attribute

        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "anything")
        module = types.ModuleType("anything")
        opaque: object = object.__new__(type("Opaque", (), {"__module__": None}))
        module.thing = opaque  # type: ignore[attr-defined]

        with pytest.raises(DisallowedImportError, match="cannot be determined"):
            resolve_allowed_attribute(module, "thing")
