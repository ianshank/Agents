"""Corpus version and the two-way version pins.

The spec's airgap couples the corpus and harness only through ``flow_protocol``,
on independent release cadences. To stop a silent version skew from corrupting the
keyed population stats, each side pins what it was built against:

* ``PROTOCOL_VERSION_PIN`` — the ``flow_protocol`` contract this corpus targets.
* ``HARNESS_VERSION_PIN`` — the ``agent_core`` (harness) version this corpus targets.

In a single repository both sides always sit at one checkout, so this pin cannot
represent a *real* cross-repo skew. Its value here is as a **tripwire**: if someone
bumps ``flow_protocol`` (or ``agent_core``) without updating the corpus, ``verify_pins``
fails the build, forcing a deliberate, reviewed bump rather than an accidental one.
"""

from __future__ import annotations

__version__ = "0.1.0"  # corpus distribution version

# What this corpus build was authored against. Bump deliberately, with a passing
# verify_pins(), when intentionally adopting a new contract/harness version.
PROTOCOL_VERSION_PIN = "1.0.0"
HARNESS_VERSION_PIN = "1.2.0"
