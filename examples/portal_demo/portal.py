"""A fake job portal on localhost: real HTTP, in-memory state, no idempotency.

Like many real application forms, submitting twice creates two applications. The
portal's own state is the evaluation oracle: it is read directly by the demo and the
tests, never through the code under test.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Portal:
    def __init__(self) -> None:
        self.applications: list[dict] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    # -- oracle -----------------------------------------------------------------
    def count(self, candidate: str, job: str) -> int:
        with self._lock:
            return sum(1 for a in self.applications if (a["candidate"], a["job"]) == (candidate, job))

    # -- server -----------------------------------------------------------------
    @property
    def url(self) -> str:
        assert self._server is not None, "portal not started"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "Portal":
        portal = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep demo output clean
                pass

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if urlparse(self.path).path != "/applications":
                    return self._send(404, {"error": "not found"})
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with portal._lock:
                    app = {"id": len(portal.applications) + 1, "candidate": payload["candidate"],
                           "job": payload["job"], "request_id": payload.get("request_id")}
                    portal.applications.append(app)
                self._send(201, {"id": app["id"]})

            def do_GET(self):
                url = urlparse(self.path)
                if url.path != "/applications":
                    return self._send(404, {"error": "not found"})
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                with portal._lock:
                    found = [{"id": a["id"]} for a in portal.applications
                             if a["candidate"] == q.get("candidate") and a["job"] == q.get("job")]
                self._send(200, {"applications": found})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "Portal":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
