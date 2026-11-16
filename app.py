import os
from http.server import BaseHTTPRequestHandler, HTTPServer

MESSAGE = "Hello from ShipIt Weekend!"


def home_page():
    return f"<h1>{MESSAGE}</h1><p>Now with a health check, an SLO and a rollback plan.</p>"


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.send(200, '{"status": "ok"}', "application/json")
        try:
            self.send(200, home_page())
        except Exception as error:
            print(f"ERROR serving {self.path}: {error!r}", flush=True)
            self.send(500, "<h1>Something went wrong</h1>")


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
