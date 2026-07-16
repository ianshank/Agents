from __future__ import annotations

import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
# SRC and ROOT keep their original (highest) precedence; insert(0) prepends, so the
# package layout resolves first. scripts/ is appended at the lowest precedence — it
# only holds standalone tooling modules and must never shadow real packages.
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))

from eval_harness.plugins import bootstrap  # noqa: E402

bootstrap()


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
