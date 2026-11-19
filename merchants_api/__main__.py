"""Servidor local para probar merchants-api sin AWS (solo biblioteca estándar).

Uso (desde services/merchants_api):  python -m merchants_api [--port 8081]
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .handler import MAX_BODY_BYTES, lambda_handler


class _Handler(BaseHTTPRequestHandler):
    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY_BYTES + 1)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        result = lambda_handler({"httpMethod": method, "path": url.path, "body": raw,
                                 "queryStringParameters": query or None})
        body = result["body"].encode("utf-8")
        self.send_response(result["statusCode"])
        for key, value in result["headers"].items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")


def main() -> None:
    parser = argparse.ArgumentParser(description="merchants-api local")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"merchants-api escuchando en http://127.0.0.1:{args.port}/merchants")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
