"""Shared filesystem path-confinement helper for the read and the write path.

Lives in ``core`` (which depends on nothing outside the stdlib) so both
``eval_harness.datasets`` — reading a dataset file named by a config — and
``eval_harness.sinks`` — creating and overwriting a report file named by a config
— can share one containment rule instead of each inventing its own. Neither
component gains a new import edge: both already depend on ``core``.

Containment is decided by :meth:`pathlib.Path.is_relative_to` on the *resolved*
paths, never by a string prefix. A string prefix is not a path prefix: with a root
of ``/srv/data``, ``str("/srv/data-secrets/leak.jsonl").startswith("/srv/data")``
is ``True``, so a sibling directory whose name merely begins with the root's name
escaped confinement. ``experiments/backend-validation/backend_validation/deploy.py``
already checks bind mounts this way; this is the same rule, single-sourced.

Two roots, deliberately separate (see the constants below): confining writes to the
read root would turn a read-only corpus directory into a writable one.

Purity: the only filesystem contact is ``Path.resolve`` — including the existence
check, which is expressed as ``resolve(strict=True)`` rather than a separate
``exists()`` call. Nothing here opens, creates or stats a path by itself.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Env var naming the root that dataset *reads* are confined to. Unset means
#: "no confinement" (the historical default), which only warns.
DATA_ROOT_ENV = "DATA_ROOT"

#: Env var naming the root that sink *writes* are confined to. Deliberately NOT
#: ``DATA_ROOT``: a deployment that mounts its dataset corpus read-only and names
#: it as the read root must not thereby declare that corpus a legal write target.
OUTPUT_ROOT_ENV = "OUTPUT_ROOT"

#: The path segment that denotes a parent directory. Rejected in the *raw* path
#: string — before resolution — so a config cannot express an escape at all, even
#: when the escape happens to land back inside the root.
_PARENT_SEGMENT = ".."

#: Fallback noun for error messages when a caller supplies no ``description``.
#: Lower-case; sentence-initial uses call ``.capitalize()``.
_DEFAULT_DESCRIPTION = "path"


def _has_traversal_segment(raw: str) -> bool:
    """True when *raw* contains a literal ``..`` segment under either separator.

    Both ``os.sep`` and ``/`` are split on so a POSIX-style config path is still
    checked on Windows (where ``os.sep`` is ``\\``) and vice versa.
    """
    return _PARENT_SEGMENT in raw.split(os.sep) or _PARENT_SEGMENT in raw.split("/")


def confinement_root(root_env_var: str) -> Path | None:
    """Return the resolved confinement root named by *root_env_var*, or ``None``.

    ``None`` means the variable is unset or blank — i.e. confinement is not
    configured. A blank value is treated as unset rather than as "confine to the
    current working directory", which is what ``Path("").resolve()`` would mean.
    """
    raw_root = os.environ.get(root_env_var, "").strip()
    return Path(raw_root).resolve() if raw_root else None


def resolve_confined_path(
    path: str | Path,
    *,
    root_env_var: str,
    description: str = _DEFAULT_DESCRIPTION,
    must_exist: bool = False,
    warn_unconfined_absolute: bool = True,
) -> Path:
    """Resolve *path* and require it to sit inside the root named by *root_env_var*.

    Parameters
    ----------
    path:
        The config-supplied path to validate.
    root_env_var:
        Name of the environment variable holding the confinement root —
        :data:`DATA_ROOT_ENV` for reads, :data:`OUTPUT_ROOT_ENV` for writes. When
        that variable is unset the path is resolved and returned unrestricted,
        preserving the harness's historical behaviour.
    description:
        Lower-case noun phrase for this kind of path (``"dataset path"``), used in
        error and log messages so a caller's message stays recognisable.
    must_exist:
        The read/write split. ``True`` (a read) requires the target to exist
        already and rejects it otherwise. ``False`` (a write) accepts a
        not-yet-existing file whose parent directory the caller will create —
        resolution stays purely lexical for the missing tail, so containment is
        still decided on the fully resolved path.
    warn_unconfined_absolute:
        Whether to warn when an absolute path is used with no root configured.
        Callers that legitimately expect absolute paths pass ``False``.

    Returns
    -------
    Path
        The resolved, contained path.

    Raises
    ------
    ValueError
        If the raw path contains a ``..`` segment, if ``must_exist`` is set and the
        target does not exist, or if the resolved path escapes the configured root.
    """
    raw = str(path)
    if _has_traversal_segment(raw):
        raise ValueError(
            f"Path traversal ('..') detected in {description}: {raw}. "
            f"Supply a path with no '..' segments, inside {root_env_var} when it is set."
        )

    try:
        resolved = Path(path).resolve(strict=must_exist)
    except OSError as exc:
        raise ValueError(f"{description.capitalize()} does not exist: {raw}") from exc

    root = confinement_root(root_env_var)
    if root is None:
        if warn_unconfined_absolute and Path(path).is_absolute():
            logger.warning(
                "Absolute %s %s used without %s. Consider setting %s for path confinement.",
                description,
                raw,
                root_env_var,
                root_env_var,
            )
        return resolved

    if not resolved.is_relative_to(root):
        raise ValueError(f"{description.capitalize()} {resolved} is outside {root_env_var} {root}")
    logger.debug("%s %s confined to %s=%s", description.capitalize(), resolved, root_env_var, root)
    return resolved
