"""RFC-9562 UUIDv7 generation for client-supplied entity ids.

Opik's fern create endpoints answer 201 with an empty body, so REST-fallback creates must
mint their own ids — and the server validates them as time-ordered UUIDv7, which the
stdlib cannot produce (`uuid.uuid4` is version 4). The clock and randomness sources are
injectable so tests can pin exact bit layouts instead of sampling.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable


def _unix_ms() -> int:
    return time.time_ns() // 1_000_000


def uuid7(
    *,
    now_ms: Callable[[], int] = _unix_ms,
    rand_bytes: Callable[[int], bytes] = os.urandom,
) -> uuid.UUID:
    """A UUIDv7 per RFC 9562: 48-bit unix-ms timestamp, then version/variant/random bits."""
    timestamp = now_ms() & ((1 << 48) - 1)
    rand = rand_bytes(10)  # 12 bits rand_a + 62 bits rand_b, masked below
    value = timestamp << 80
    value |= 0x7 << 76  # version 7
    value |= (int.from_bytes(rand[:2], "big") & 0x0FFF) << 64
    value |= 0x2 << 62  # RFC 9562 variant '10'
    value |= int.from_bytes(rand[2:], "big") & ((1 << 62) - 1)
    return uuid.UUID(int=value)
