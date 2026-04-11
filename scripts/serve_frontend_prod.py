from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path


class FrontendRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        self._frontend_root = Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path)).resolve()
        try:
            translated.relative_to(self._frontend_root)
        except ValueError:
            return str(self._frontend_root)
        return str(translated)

    def do_GET(self) -> None:
        resolved_path = Path(self.translate_path(self.path))
        if not resolved_path.exists():
            self.path = "/index.html"
        super().do_GET()

    def do_HEAD(self) -> None:
        resolved_path = Path(self.translate_path(self.path))
        if not resolved_path.exists():
            self.path = "/index.html"
        super().do_HEAD()


class ThreadingTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve frontend/dist with SPA fallback and disabled cache.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--root", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frontend_root = Path(args.root).resolve()
    if not frontend_root.is_dir():
        raise SystemExit(f"Frontend root does not exist: {frontend_root}")

    handler = functools.partial(FrontendRequestHandler, directory=str(frontend_root))
    with ThreadingTcpServer((args.host, args.port), handler) as httpd:
        print(f"Serving {frontend_root} at http://{args.host}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
