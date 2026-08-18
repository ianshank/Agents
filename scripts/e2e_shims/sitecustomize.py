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
    import sys

    def _wmi_query_disabled(*_args, **_kwargs):
        raise OSError("WMI disabled by e2e harness (query hangs on this host)")

    # Only patch if the hanging symbol exists (Python >= 3.12 on Windows). If a
    # future CPython renames/removes it, leave a stderr breadcrumb so a returning
    # startup hang is diagnosable instead of silently un-shimmed.
    #
    # The breadcrumb is Windows-only on purpose. `_wmi_query` never exists off
    # Windows, so an unconditional `else` printed on *every* interpreter started with
    # this directory on PYTHONPATH -- which is every step of a Linux e2e run. That
    # polluted the stdout/stderr of each child process and broke the one test that
    # asserts a subprocess prints exactly the version string and nothing else. There
    # is no WMI to shim off Windows, so there is nothing to warn about there.
    if hasattr(platform, "_wmi_query"):
        platform._wmi_query = _wmi_query_disabled  # type: ignore[attr-defined]
    elif sys.platform == "win32" and sys.version_info >= (3, 12):
        print(
            "sitecustomize(e2e_shims): platform._wmi_query not found; WMI shim inactive",
            file=sys.stderr,
        )
except Exception:
    # Never let the shim break interpreter startup.
    pass
