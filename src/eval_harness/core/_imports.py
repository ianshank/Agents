"""Operator-controlled gate on config-driven dynamic imports.

``CallableTarget`` resolves ``params.path`` ("module:attribute") by importing
the named module and calling the named attribute. That makes an eval config an
executable artefact: a config naming ``subprocess:call`` whose dataset item
supplies a dict of ``inputs`` reaches ``Popen``, which builds its argv by
iterating its argument — so the dict's keys become a command line. The command
runs, and because ``CallableTarget.run`` reports a callable's own return value,
the harness reports the run as clean.

The control therefore cannot live in the config, because the config is the
untrusted input. It lives in the environment, where the operator running the
harness sets it and a config author cannot reach it:

    EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=my_project,tests

Unset means *deny*. That is a deliberate breaking change: an unset allowlist
previously meant "import anything this interpreter can reach", which is not a
default a tool that loads YAML from disk can keep. The refusal names the
variable and the module, so recovering from it is a single export.

Matching is on dotted-component boundaries, never a raw string prefix. A prefix
test would let an entry of ``tests`` silently admit ``tests_evil`` — the same
class of bug that made ``DATA_ROOT`` containment bypassable via a sibling
directory sharing its prefix.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from importlib import import_module
from types import ModuleType

logger = logging.getLogger(__name__)

#: Environment variable naming the module prefixes a config may import.
#: Comma-separated; whitespace around entries is ignored.
CALLABLE_ALLOWLIST_ENV = "EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST"

#: Allowlist entry that disables the gate entirely. Intended for a trusted
#: local loop where the operator authored every config; never a deployment
#: default, and logged at WARNING each time it is honoured so it cannot be set
#: in CI and quietly forgotten.
ALLOW_ALL = "*"

_ENTRY_SEPARATOR = ","


class DisallowedImportError(ImportError):
    """A config named a module outside the operator's allowlist.

    Subclasses :class:`ImportError` because a denial *is* a refusal to import:
    a caller that already handles an unresolvable ``path`` keeps working
    unchanged, and ``except ImportError`` still catches it.
    """


def read_allowlist(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Parse the allowlist from *env* (defaults to the live environment).

    Returns a deduplicated, sorted tuple so the value is deterministic and safe
    to include verbatim in an error message.
    """
    source = os.environ if env is None else env
    raw = source.get(CALLABLE_ALLOWLIST_ENV, "")
    return tuple(sorted({entry.strip() for entry in raw.split(_ENTRY_SEPARATOR) if entry.strip()}))


def is_allowed(module_name: str, allowlist: tuple[str, ...]) -> bool:
    """Whether *module_name* falls under any allowlist entry.

    An entry admits the module itself and its submodules, and nothing else:
    ``tests`` admits ``tests`` and ``tests._sut`` but not ``tests_evil``.
    """
    if ALLOW_ALL in allowlist:
        return True
    return any(module_name == entry or module_name.startswith(f"{entry}.") for entry in allowlist)


def resolve_allowed_attribute(module: ModuleType, attr: str, *, env: Mapping[str, str] | None = None) -> object:
    """Fetch ``attr`` from *module*, refusing anything that only lives there by re-export.

    Allowlisting the *module* is not the same as allowlisting what is reachable
    through it. Any name bound in an allowlisted package's namespace is fetchable
    by ``getattr``, and a one-line re-export is utterly ordinary::

        # my_project/__init__.py
        from subprocess import call

    With ``…ALLOWLIST=my_project``, a config of ``my_project:call`` then reaches
    ``subprocess.call`` -- the exact sink the allowlist exists to deny, through a
    module the operator does trust. So the object's *defining* module has to clear
    the allowlist too: ``subprocess.call.__module__`` is ``"subprocess"``, which
    does not, while a legitimate internal re-export (``my_project.impl:run``
    surfaced as ``my_project:run``) resolves to ``my_project.impl`` and does.

    A callable without a ``__module__`` (a class instance implementing
    ``__call__``) is judged by its type's module instead. An object with neither
    is refused: unattributable is not the same as harmless.
    """
    obj = getattr(module, attr)

    origin = getattr(obj, "__module__", None)
    if origin is None:
        origin = getattr(type(obj), "__module__", None)
    if origin is None:
        raise DisallowedImportError(
            f"refusing to call {module.__name__}.{attr}: its defining module cannot be "
            "determined, so it cannot be checked against "
            f"{CALLABLE_ALLOWLIST_ENV}."
        )

    allowlist = read_allowlist(env)
    if not is_allowed(origin, allowlist):
        raise DisallowedImportError(
            f"refusing to call {module.__name__}.{attr}: it is defined in {origin!r}, which is "
            f"outside {CALLABLE_ALLOWLIST_ENV}={_ENTRY_SEPARATOR.join(allowlist)}. Allowlisting "
            f"{module.__name__!r} does not extend to names it merely re-exports from elsewhere."
        )

    logger.debug("Resolved %s.%s (defined in %r)", module.__name__, attr, origin)
    return obj


def import_allowed_module(module_name: str, *, env: Mapping[str, str] | None = None) -> ModuleType:
    """Import *module_name*, refusing anything outside the allowlist.

    Raises :class:`DisallowedImportError` before importing, so a denied
    module's import-time side effects never run — the check has to precede the
    import to be worth anything.
    """
    allowlist = read_allowlist(env)

    if not allowlist:
        raise DisallowedImportError(
            f"refusing to import {module_name!r}: dynamic imports from configuration are disabled "
            f"because {CALLABLE_ALLOWLIST_ENV} is unset. Set it to a comma-separated list of module "
            f"prefixes you trust (for example {CALLABLE_ALLOWLIST_ENV}=my_project), or to "
            f"{ALLOW_ALL!r} to allow any module when you authored every config yourself."
        )

    if not is_allowed(module_name, allowlist):
        raise DisallowedImportError(
            f"refusing to import {module_name!r}: it is outside {CALLABLE_ALLOWLIST_ENV}="
            f"{_ENTRY_SEPARATOR.join(allowlist)}. Add its module prefix to that variable if the "
            f"config is one you trust."
        )

    if ALLOW_ALL in allowlist:
        logger.warning(
            "%s is set to %r, so any module named by a configuration file will be imported and "
            "executed. Narrow it to the module prefixes you actually trust.",
            CALLABLE_ALLOWLIST_ENV,
            ALLOW_ALL,
        )
    logger.debug("Importing %r for a configuration-named callable (allowlist=%s)", module_name, allowlist)
    return import_module(module_name)
