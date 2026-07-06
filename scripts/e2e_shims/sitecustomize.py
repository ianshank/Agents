"""Auto-loaded interpreter shim for the e2e harness.

Python imports ``sitecustomize`` at startup (before pytest loads its plugins). On
this locked-down Windows host, ``platform.uname()`` -> ``win32_ver()`` ->
``platform._wmi_query()`` hangs indefinitely because WMI is blocked. Hypothesis
calls ``platform.system()`` at import time, and Hypothesis is an auto-loaded pytest
plugin, so that hang wedges *every* test suite before a single test runs.

We make ``_wmi_query`` fail fast with ``OSError``; ``platform._win32_ver`` already
wraps it in ``try/except OSError`` and falls back to a subprocess-free path
(``sys.getwindowsversion`` + ``winreg``). This only loads when this directory is on
PYTHONPATH (the runner adds it), so it never affects normal interpreter use.
"""

from __future__ import annotations

try:
    import platform

    def _wmi_query_disabled(*_args, **_kwargs):
        raise OSError("WMI disabled by e2e harness (query hangs on this host)")

    # Only patch if the hanging symbol exists (Python >= 3.12 on Windows).
    if hasattr(platform, "_wmi_query"):
        platform._wmi_query = _wmi_query_disabled  # type: ignore[attr-defined]
except Exception:
    # Never let the shim break interpreter startup.
    pass
