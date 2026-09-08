"""Tiny JSON HTTP server base shared by the fakes."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


class JsonHandler(BaseHTTPRequestHandler):
    server_version = "playbook-fake/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep test output quiet
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self, method: str) -> None:
        path = urlparse(self.path).path
        body = self._read_json() if method in ("POST", "PUT", "DELETE") else {}
        try:
            status, payload = self.server.app.handle(method, path, body)  # type: ignore[attr-defined]
        except KeyError as exc:
            status, payload = 404, {"error": f"not found: {exc}"}
        except ValueError as exc:
            status, payload = 400, {"error": str(exc)}
        self._send(status, payload)

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PUT(self) -> None:
        self._route("PUT")

    def do_DELETE(self) -> None:
        self._route("DELETE")


class FakeServer:
    """Runs an app object (with `.handle(method, path, body)`) on a background thread."""

    def __init__(self, app: Any, port: int, host: str = "127.0.0.1"):
        self.app = app
        self.httpd = ThreadingHTTPServer((host, port), JsonHandler)
        self.httpd.app = app  # type: ignore[attr-defined]
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> FakeServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
