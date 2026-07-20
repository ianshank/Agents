"""UrllibRest exercised against a real loopback HTTP server (no proxy, no fakes)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend_validation.clients._rest import RestResult, UrllibRest


class _Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/missing":
            self._reply(404, {"error": "nope"})
        else:
            self._reply(200, {"ok": True, "auth": self.headers.get("Authorization", "")})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        received = json.loads(self.rfile.read(length) or b"{}")
        self._reply(201, {"received": received})

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        return None


@pytest.fixture()
def http_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_get_ok_carries_headers_and_body(http_server: str) -> None:
    result = UrllibRest().call("GET", http_server + "/thing", headers={"Authorization": "Bearer t"})
    assert result.ok and result.status_code == 200
    assert "Bearer t" in result.body_excerpt


def test_post_json_round_trip(http_server: str) -> None:
    result = UrllibRest().call("POST", http_server + "/create", json_body={"a": 1})
    assert result.status_code == 201 and '"a": 1' in result.body_excerpt


def test_http_error_becomes_a_result_not_an_exception(http_server: str) -> None:
    result = UrllibRest().call("GET", http_server + "/missing")
    assert not result.ok and result.status_code == 404
    assert "nope" in result.body_excerpt


def test_connection_refused_propagates_for_dispatch_capture() -> None:
    import urllib.error

    with pytest.raises(urllib.error.URLError):
        UrllibRest().call("GET", "http://127.0.0.1:1/", timeout=2)


def test_rest_result_ok_boundary() -> None:
    assert RestResult(status_code=299).ok and not RestResult(status_code=300).ok
