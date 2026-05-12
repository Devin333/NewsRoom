import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request

import pytest

from sources.connectors.fetch_policy import (
    SourceFetchPolicy,
    TooManyRedirectsError,
    open_request_with_fetch_policy,
)


def test_open_request_with_fetch_policy_enforces_redirect_limit() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/one")
                self.end_headers()
                return
            if self.path == "/one":
                self.send_response(302)
                self.send_header("Location", "/done")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"done")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f"http://127.0.0.1:{server.server_port}/start")

        with pytest.raises(TooManyRedirectsError) as exc_info:
            open_request_with_fetch_policy(request, SourceFetchPolicy(max_redirects=1))

        assert exc_info.value.max_redirects == 1
        assert exc_info.value.url.endswith("/done")

        with open_request_with_fetch_policy(
            Request(f"http://127.0.0.1:{server.server_port}/start"),
            SourceFetchPolicy(max_redirects=2),
        ) as response:
            assert response.read() == b"done"
    finally:
        server.shutdown()
        server.server_close()
