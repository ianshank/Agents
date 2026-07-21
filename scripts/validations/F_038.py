#!/usr/bin/env python3
"""Validation script for F-038 — BrainTrust integration (sink + dataset + autoevals scorer).

Asserts the additive, SDK-optional invariants of the BrainTrust seam WITHOUT installing or
importing the real ``braintrust`` / ``autoevals`` SDKs — the offline CI job (quality-gates)
has neither the braintrust SDK nor a network. Importing ``eval_harness`` does not import
either SDK (both are lazy), so the registries, the no-op factory, the config schema, and the
packaging/CI config can all be checked deterministically and offline.

Checks:
    1. The ``braintrust`` sink, ``autoevals`` scorer, and ``braintrust`` dataset are registered.
    2. ``build_client(enabled=False)`` is a no-op ``NullBrainTrustClient`` (disabled ⇒ no-op).
    3. The integration is additive: ``EvalConfig`` gained no ``braintrust`` field, and
       ``SCHEMA_VERSION`` is a non-empty string (configured via component params, not a schema bump).
    4. ``pyproject.toml`` declares the ``braintrust`` and ``autoevals`` optional extras.
    5. CI discipline: ``autoevals`` is installed in the offline job; the ``braintrust`` SDK is not.
    6. No hardcoded credentials/URLs in ``braintrust_client`` (creds come from the environment).

Deterministic and offline: reads source/config files and the in-process registries; runs no
external SDK. Exit codes: 0 - all checks passed; 1 - one or more checks failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
_SRC = os.path.join(_ROOT, "src")
for _p in reversed((_SRC, _HERE, _SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check, configure_logging, report

logger = logging.getLogger(__name__)


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _registered(registry, name: str) -> bool:
    try:
        registry.get(name)
        return True
    except Exception:
        return False


def validate() -> int:
    errors: list[str] = []

    from eval_harness.braintrust_client import NullBrainTrustClient, build_client
    from eval_harness.config.models import EvalConfig
    from eval_harness.plugins import DATASETS, SCORERS, SINKS, bootstrap
    from eval_harness.version import SCHEMA_VERSION

    bootstrap()

    # 1. Registration.
    check(_registered(SINKS, "braintrust"), "braintrust sink is registered", errors)
    check(_registered(SCORERS, "autoevals"), "autoevals scorer is registered", errors)
    check(_registered(DATASETS, "braintrust"), "braintrust dataset source is registered", errors)

    # 2. Disabled ⇒ no-op (works without the SDK installed).
    client = build_client(enabled=False, project_name="p", experiment_name="r")
    check(isinstance(client, NullBrainTrustClient), "build_client(enabled=False) returns NullBrainTrustClient", errors)

    # 3. Additive: no new config field, schema version intact.
    check("braintrust" not in EvalConfig.model_fields, "EvalConfig gained no 'braintrust' field (additive)", errors)
    check(bool(SCHEMA_VERSION), f"SCHEMA_VERSION is set ({SCHEMA_VERSION!r})", errors)

    # 4. Packaging extras.
    pyproject = _read("pyproject.toml")
    check("braintrust = [" in pyproject, "pyproject declares the 'braintrust' extra", errors)
    check("autoevals = [" in pyproject, "pyproject declares the 'autoevals' extra", errors)

    # 5. CI discipline (offline job installs autoevals, not the braintrust SDK).
    ci = _read(".github/workflows/eval-harness-ci.yml")
    install = " ".join(ln for ln in ci.splitlines() if 'pip install -e ".[' in ln)
    check("autoevals" in install, "autoevals is installed in the offline CI job", errors)
    check("braintrust" not in install, "braintrust SDK is kept OUT of the offline CI job", errors)

    # 6. No hardcoded credentials/URLs in the client (creds come from the environment).
    client_src = _read("src/eval_harness/braintrust_client/__init__.py")
    check("api.braintrust.dev" not in client_src, "no hardcoded BrainTrust URL in braintrust_client", errors)
    check(
        'api_key="' not in client_src and "api_key='" not in client_src,
        "no hardcoded api_key in braintrust_client",
        errors,
    )

    return report(logger, "F-038", errors)


if __name__ == "__main__":
    configure_logging()
    sys.exit(validate())
