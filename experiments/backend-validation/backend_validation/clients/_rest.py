"""Minimal injectable REST transport for endpoint-existence probes.

Several matrix cells (guardrails, alerting, red-teaming, annotation queues) are probed by
asking the platform's HTTP API directly — the honest way to test "does this capability
exist as an API" without an SDK in the way. The transport is a Protocol so offline tests
inject a fake; the real one uses urllib with an EMPTY proxy map (targets are loopback
stacks; the session's HTTPS proxy must not intercept them).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_EXCERPT_LIMIT = 200


@dataclass(frozen=True)
class RestResult:
    status_code: int
    body_excerpt: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class RestTransport(Protocol):
    def call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        timeout: float = 30.0,
    ) -> RestResult: ...


def basic_auth_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def bearer_auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class UrllibRest:
    """Real transport. Proxy-free on purpose: probe targets are local containers."""

    def call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        timeout: float = 30.0,
    ) -> RestResult:
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(_EXCERPT_LIMIT).decode("utf-8", errors="replace")
                return RestResult(status_code=int(response.status), body_excerpt=body)
        except urllib.error.HTTPError as exc:
            body = exc.read(_EXCERPT_LIMIT).decode("utf-8", errors="replace") if exc.fp else ""
            return RestResult(status_code=int(exc.code), body_excerpt=body)
        # URLError/timeout/socket errors propagate: DispatchProbeClient.execute converts
        # them into `error` observables with the exception text preserved.
