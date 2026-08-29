"""Bounded local Alertmanager demonstration receiver."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/alerts":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "-1"))
        if length < 0 or length > 64 * 1024:
            self.send_error(413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            count = len(payload.get("alerts", [])) if isinstance(payload, dict) else 0
        except (ValueError, TypeError):
            self.send_error(400)
            return
        print(
            json.dumps({"event": "alert_notification", "alert_count": count}),
            flush=True,
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
