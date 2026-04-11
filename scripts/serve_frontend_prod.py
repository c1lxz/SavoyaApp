from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

PROXIED_PREFIXES = (
    "/api",
    "/auth",
    "/user",
    "/passes",
    "/gates",
    "/access",
    "/requests",
)


class FrontendRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, proxy_target: str | None = None, **kwargs):
        self._frontend_root = Path(directory).resolve()
        self._proxy_target = proxy_target.rstrip("/") if proxy_target else ""
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _should_proxy(self) -> bool:
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/health":
            return True

        return any(
            request_path == prefix or request_path.startswith(f"{prefix}/")
            for prefix in PROXIED_PREFIXES
        )

    def _read_request_body(self) -> bytes:
        content_length = self.headers.get("Content-Length")
        if not content_length:
            return b""
        return self.rfile.read(int(content_length))

    def _proxy_request(self) -> bool:
        if not self._should_proxy():
            return False

        if not self._proxy_target:
            self.send_error(502, "Backend proxy target is not configured.")
            return True

        target_url = f"{self._proxy_target}{self.path}"
        request_body = self._read_request_body()
        request = urllib.request.Request(
            target_url,
            data=request_body if request_body else None,
            method=self.command,
        )

        target_parts = urllib.parse.urlsplit(self._proxy_target)
        client_host = self.client_address[0] if self.client_address else ""
        request.add_header("Host", target_parts.netloc)
        request.add_header("X-Forwarded-For", client_host)
        request.add_header("X-Forwarded-Host", self.headers.get("Host", ""))
        request.add_header("X-Forwarded-Proto", "http")

        for header_name, header_value in self.headers.items():
            header_key = header_name.lower()
            if header_key in HOP_BY_HOP_HEADERS or header_key == "host":
                continue
            request.add_header(header_name, header_value)

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                self.send_response(response.status, response.reason)
                for header_name, header_value in response.getheaders():
                    if header_name.lower() in HOP_BY_HOP_HEADERS:
                        continue
                    self.send_header(header_name, header_value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response.read())
        except urllib.error.HTTPError as error:
            self.send_response(error.code, error.reason)
            for header_name, header_value in error.headers.items():
                if header_name.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(header_name, header_value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(error.read())
        except urllib.error.URLError as error:
            self.send_error(502, f"Proxy request failed: {error.reason}")

        return True

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path)).resolve()
        try:
            translated.relative_to(self._frontend_root)
        except ValueError:
            return str(self._frontend_root)
        return str(translated)

    def do_GET(self) -> None:
        if self._proxy_request():
            return
        resolved_path = Path(self.translate_path(self.path))
        if not resolved_path.exists():
            self.path = "/index.html"
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._proxy_request():
            return
        resolved_path = Path(self.translate_path(self.path))
        if not resolved_path.exists():
            self.path = "/index.html"
        super().do_HEAD()

    def do_POST(self) -> None:
        if not self._proxy_request():
            self.send_error(405, "Only /api and /health accept POST requests.")

    def do_PUT(self) -> None:
        if not self._proxy_request():
            self.send_error(405, "Only /api and /health accept PUT requests.")

    def do_PATCH(self) -> None:
        if not self._proxy_request():
            self.send_error(405, "Only /api and /health accept PATCH requests.")

    def do_DELETE(self) -> None:
        if not self._proxy_request():
            self.send_error(405, "Only /api and /health accept DELETE requests.")

    def do_OPTIONS(self) -> None:
        if not self._proxy_request():
            self.send_error(405, "Only /api and /health accept OPTIONS requests.")


class ThreadingTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve frontend/dist with SPA fallback and disabled cache.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--root", required=True)
    parser.add_argument("--proxy-target", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frontend_root = Path(args.root).resolve()
    if not frontend_root.is_dir():
        raise SystemExit(f"Frontend root does not exist: {frontend_root}")

    handler = functools.partial(
        FrontendRequestHandler,
        directory=str(frontend_root),
        proxy_target=args.proxy_target,
    )
    with ThreadingTcpServer((args.host, args.port), handler) as httpd:
        print(f"Serving {frontend_root} at http://{args.host}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
