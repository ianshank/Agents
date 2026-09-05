from __future__ import annotations

import os
import pathlib
import socket
import sys
import types
from unittest import mock

import pytest
from hypothesis import HealthCheck, settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
# SRC and ROOT keep their original (highest) precedence; insert(0) prepends, so the
# package layout resolves first. scripts/ is appended at the lowest precedence — it
# only holds standalone tooling modules and must never shadow real packages.
for _p in (
    str(ROOT),
    str(SRC),
    str(ROOT / "agent-core"),
    str(ROOT / "behavioral-regression"),
    str(ROOT / "flow-corpus"),
    str(ROOT / "flow-protocol"),
    str(ROOT / "claude-foundation" / "tools"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))

from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV  # noqa: E402
from eval_harness.plugins import bootstrap  # noqa: E402

bootstrap()

# --------------------------------------------------------------------------- #
# Allowlist for config-named dynamic imports (ADR 0039).
#
# `CallableTarget` turns a config string into executed code, so an unset
# allowlist now means *deny*. The suite is a trusted operator context and must
# still exercise the registered `callable` path (ADR 0032's matrix obligation),
# so it declares its own allowlist here -- once, rather than in each of the
# eleven test modules that resolve a callable.
#
# Enumerated rather than set to "*" on purpose: the gate stays LIVE for the
# whole run, so a test that reached for `subprocess` or `os` would still be
# refused. Each entry earns its place:
#
#   tests       -- `tests._sut`, the suite's system-under-test fixtures.
#   json        -- the matrix M1 correctness row resolves `json:dumps`.
#   eval_harness.targets.testgen
#               -- the M8 testgen cell resolves the suite-execution target from a
#                  config, which is the only way that target is ever reachable.
#                  Narrowed to the module, not the `eval_harness` package: allowlisting
#                  the whole harness would let any config call anything in it.
#   nonexistent -- the matrix M6 error row resolves `nonexistent.module_xyz` to
#                  prove a genuinely missing module still raises ImportError.
#                  Without it, the allowlist would refuse that row first and it
#                  would pass for the wrong reason.
#
# setdefault, not an unconditional set, so an operator can widen it for a local
# debugging run without editing this file.
# --------------------------------------------------------------------------- #
os.environ.setdefault(CALLABLE_ALLOWLIST_ENV, "tests,json,nonexistent,eval_harness.targets.testgen")

# --------------------------------------------------------------------------- #
# Hypothesis profiles. Mirrors agent-core/tests/conftest.py so the whole monorepo shares one
# convention: example counts are config-driven, never hard-coded per test. CI runners are
# noisy, so the ci profile drops the per-example deadline rather than flaking.
# --------------------------------------------------------------------------- #
_HYPOTHESIS_PROFILE_ENV = "HYPOTHESIS_PROFILE"

settings.register_profile("dev", max_examples=50)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.getenv(_HYPOTHESIS_PROFILE_ENV, "dev"))


# --------------------------------------------------------------------------- #
# Shared BrainTrust test doubles. The braintrust SDK is never installed in the offline
# suite, so its `init` / `init_dataset` are faked via sys.modules injection. Single-sourced
# here so the client/sink/dataset test modules don't each re-implement them.
# --------------------------------------------------------------------------- #


class RecordingExperiment:
    """A fake BrainTrust experiment handle that records ``log()`` / ``flush()`` calls."""

    def __init__(self) -> None:
        self.logged: list[dict] = []
        self.flushed = False

    def log(self, **kwargs: object) -> None:
        self.logged.append(dict(kwargs))

    def flush(self) -> None:
        self.flushed = True


@pytest.fixture
def recording_experiment() -> RecordingExperiment:
    """A fresh recording fake for a BrainTrust experiment handle."""
    return RecordingExperiment()


@pytest.fixture
def fake_braintrust(monkeypatch):
    """Return an installer that injects a fake ``braintrust`` module into ``sys.modules``.

    ``install(experiment=None, init_dataset_records=None, init_raises=False, capture=None)``
    makes ``braintrust.init`` return ``experiment`` (or raise when ``init_raises``) and
    ``braintrust.init_dataset`` return ``init_dataset_records``. When ``capture`` (a dict) is
    supplied, whichever init is invoked records its kwargs into it (for plumbing assertions).
    Keeps the offline suite hermetic — the real SDK is never imported.
    """

    def install(
        *,
        experiment: object | None = None,
        init_dataset_records: list | None = None,
        init_raises: bool = False,
        capture: dict | None = None,
    ):
        mod = types.ModuleType("braintrust")

        def _init(**kwargs):
            if capture is not None:
                capture.update(kwargs)
            if init_raises:
                raise RuntimeError("braintrust down")
            return experiment

        def _init_dataset(**kwargs):
            if capture is not None:
                capture.update(kwargs)
            return list(init_dataset_records or [])

        mod.init = _init  # type: ignore[attr-defined]
        mod.init_dataset = _init_dataset  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "braintrust", mod)
        return mod

    return install


# --------------------------------------------------------------------------- #
# Non-loopback egress guard for the M8 pipeline suite.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def matrix_offline_egress_guard(request: pytest.FixtureRequest):
    """Fail a `matrix_offline`-marked test that opens a non-loopback socket.

    Scoped by marker rather than applied suite-wide deliberately: patching
    `socket.connect` for every test would very likely surface other tests that quietly
    dial out. That is a real finding, but it is a different change -- widening this guard
    belongs with the work that fixes whatever it catches, not here.

    Active for the WHOLE marked test, which is what makes it useful for judges. Neither
    `openai.OpenAI(...)` nor `anthropic.Anthropic(...)` opens a socket at construction --
    both build a local HTTP-client wrapper, resolve an API key, and raise a client-side
    auth error if none is found. The network attempt, when there is one, happens at the
    first real request inside `evaluate()` -- during `.run()`, inside the engine's
    scorer-exception handler, which would otherwise convert it into a `0.0`-valued
    "scorer error: ..." ScoreResult and report green. Guarding the whole test catches it
    at the socket instead of letting the engine swallow it.
    """
    if "matrix_offline" not in request.keywords:
        yield
        return

    original_connect = socket.socket.connect
    loopback = {"127.0.0.1", "::1", "localhost"}

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in loopback:
            raise AssertionError(
                f"matrix_offline test attempted network egress to {address!r}; an M8 "
                "pipeline must run entirely offline (inject a client instead)"
            )
        return original_connect(self, address)

    with mock.patch.object(socket.socket, "connect", guarded_connect):
        yield
