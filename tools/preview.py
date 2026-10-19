#!/usr/bin/env python3
"""Serve the admin UI locally with mock data and a live CSS override."""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = PROJECT_ROOT / "src" / "www"
DEFAULT_STYLESHEET = PROJECT_ROOT / "preview" / "overrides.css"


class PreviewState:
    """Small in-memory API used to exercise the real browser application."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = True
        self.repo_path = "/volume1/mercurial"
        self.repositories = [
            {"name": "team/website", "modified_at": "2026-09-30T19:42:00+00:00"},
            {"name": "infrastructure", "modified_at": "2026-09-27T13:18:00+00:00"},
            {"name": "personal/notes", "modified_at": "2026-09-20T08:05:00+00:00"},
        ]
        self.users = [
            {"username": "admin", "admin": True, "created_at": "2026-08-14T12:00:00+00:00"},
            {"username": "developer", "admin": False, "created_at": "2026-09-03T12:00:00+00:00"},
        ]

    def status(self) -> dict[str, object]:
        with self.lock:
            return {
                "running": self.running,
                "repo_path": self.repo_path,
                "repo_writable": True,
                "hg_path": "/hg/",
                "repositories": list(self.repositories),
                "users": list(self.users),
            }


class PreviewServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        web_dir: Path = DEFAULT_WEB_DIR,
        stylesheet: Path = DEFAULT_STYLESHEET,
    ) -> None:
        self.web_dir = web_dir.resolve()
        self.stylesheet = stylesheet.resolve()
        self.state = PreviewState()
        super().__init__(address, PreviewHandler)


class PreviewHandler(BaseHTTPRequestHandler):
    server: PreviewServer

    def log_message(self, format: str, *args: object) -> None:
        if self.path.startswith("/__preview_revision"):
            return
        print(f"[preview] {format % args}")

    def _send(self, body: bytes, content_type: str, status: int = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: object, status: int = HTTPStatus.OK) -> None:
        self._send(
            json.dumps(value, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length) or b"{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    def _serve_file(self, path: Path, content_type: str | None = None) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"error": "Preview file not found."}, HTTPStatus.NOT_FOUND)
            return
        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(body, content_type or guessed)

    def _serve_index(self) -> None:
        try:
            html = (self.server.web_dir / "index.html").read_text(encoding="utf-8")
        except OSError:
            self._json({"error": "index.html not found."}, HTTPStatus.NOT_FOUND)
            return
        preview_tags = """  <!-- Injected only by tools/preview.py. -->
  <link rel="stylesheet" href="/preview-overrides.css" data-preview-overrides>
  <script>
    (() => {
      let revision;
      async function refreshPreviewStyles() {
        try {
          const next = await fetch("/__preview_revision", { cache: "no-store" }).then(r => r.text());
          if (revision && next !== revision) {
            document.querySelector("[data-preview-overrides]").href =
              `/preview-overrides.css?v=${next}`;
          }
          revision = next;
        } catch (_) { /* The preview server may be restarting. */ }
      }
      refreshPreviewStyles();
      window.setInterval(refreshPreviewStyles, 750);
    })();
  </script>
"""
        html = html.replace("</head>", f"{preview_tags}</head>", 1)
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/admin/")
            self.end_headers()
            return
        if path in ("/admin", "/admin/"):
            self._serve_index()
            return
        if path == "/admin/styles.css":
            self._serve_file(self.server.web_dir / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/admin/app.js":
            self._serve_file(self.server.web_dir / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/preview-overrides.css":
            self._serve_file(self.server.stylesheet, "text/css; charset=utf-8")
            return
        if path == "/__preview_revision":
            try:
                revision = str(self.server.stylesheet.stat().st_mtime_ns)
            except OSError:
                revision = "missing"
            self._send(revision.encode("ascii"), "text/plain; charset=utf-8")
            return
        if path == "/api/bootstrap":
            self._json({"setup_required": False, "authenticated": True, "csrf": "preview"})
            return
        if path == "/api/status":
            self._json(self.server.state.status())
            return
        self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        body = self._read_json()
        state = self.server.state
        with state.lock:
            if path == "/api/service/start":
                state.running = True
            elif path == "/api/service/stop":
                state.running = False
            elif path == "/api/settings/storage":
                state.repo_path = str(body.get("repo_path", state.repo_path))
            elif path == "/api/repositories":
                name = str(body.get("name", "New repository")).strip()
                state.repositories.append(
                    {"name": name, "modified_at": datetime.now(timezone.utc).isoformat()}
                )
            elif path == "/api/users":
                state.users.append(
                    {
                        "username": str(body.get("username", "new-user")),
                        "admin": bool(body.get("admin", False)),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            elif path.endswith("/password") or path in {
                "/api/login", "/api/logout", "/api/setup"
            }:
                pass
            else:
                self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
        self._json({"ok": True, "csrf": "preview"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        prefix = "/api/users/"
        if not path.startswith(prefix):
            self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        username = unquote(path[len(prefix) :])
        with self.server.state.lock:
            self.server.state.users = [
                user for user in self.server.state.users if user["username"] != username
            ]
        self._json({"ok": True})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    parser.add_argument("--stylesheet", type=Path, default=DEFAULT_STYLESHEET)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stylesheet = args.stylesheet.expanduser()
    if not stylesheet.is_absolute():
        stylesheet = (Path.cwd() / stylesheet).resolve()
    stylesheet.parent.mkdir(parents=True, exist_ok=True)
    stylesheet.touch(exist_ok=True)
    server = PreviewServer((args.host, args.port), stylesheet=stylesheet)
    url = f"http://{args.host}:{server.server_address[1]}/admin/"
    print(f"Previewing {DEFAULT_WEB_DIR / 'index.html'}")
    print(f"CSS overrides: {stylesheet}")
    print(f"Open {url} (Ctrl-C to stop)")
    if not args.no_open:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
