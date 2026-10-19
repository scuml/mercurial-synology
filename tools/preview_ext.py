#!/usr/bin/env python3
"""Run the real ExtJS admin window locally with Synology shims and mock data."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import threading
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = PROJECT_ROOT / "src" / "ui"
BUILD_UI_IMAGES = PROJECT_ROOT / "build" / "work" / "payload" / "ui" / "images"
PREVIEW_DIR = PROJECT_ROOT / "preview" / "ext"
VENDOR_DIR = PREVIEW_DIR / "vendor"
DEFAULT_OVERRIDES = PREVIEW_DIR / "overrides.css"


def package_release() -> tuple[str, int]:
    try:
        for line in (PROJECT_ROOT / "package" / "INFO").read_text(encoding="utf-8").splitlines():
            if line.startswith('version="') and line.endswith('"'):
                version, build = line[9:-1].rsplit("-", 1)
                return version, int(build)
    except (OSError, ValueError):
        pass
    return "unknown", 0


class ExtPreviewState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = True
        self.repo_path = "/volume1/mercurial"
        self.repositories = [
            {
                "name": "infrastructure",
                "size_bytes": 866304,
                "modified_at": "2026-09-27T13:18:00+00:00",
            },
            {
                "name": "personal/notes",
                "size_bytes": 13002342,
                "modified_at": "2026-09-20T08:05:00+00:00",
            },
            {
                "name": "team/website",
                "size_bytes": 40579891,
                "modified_at": "2026-09-30T19:42:00+00:00",
            },
        ]
        self.users = [
            {"username": "admin", "admin": True, "created_at": "2026-08-14T12:00:00+00:00"},
            {"username": "developer", "admin": False, "created_at": "2026-09-03T12:00:00+00:00"},
        ]

    def status(self) -> dict[str, object]:
        with self.lock:
            version, build = package_release()
            return {
                "running": self.running,
                "repo_path": self.repo_path,
                "repo_writable": True,
                "python_version": "3.12.11",
                "python_executable": "/var/packages/Python3.12/target/usr/local/bin/python3",
                "package_version": version,
                "package_build": build,
                "https_configured": True,
                "https_base_url": "https://nas.example.com:5001/hg/",
                "repositories": list(self.repositories),
                "users": list(self.users),
            }


class ExtPreviewServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        overrides: Path = DEFAULT_OVERRIDES,
    ) -> None:
        self.overrides = overrides.resolve()
        self.state = ExtPreviewState()
        super().__init__(address, ExtPreviewHandler)

    @staticmethod
    def _fingerprint(paths: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in sorted(paths):
            digest.update(str(path).encode("utf-8"))
            try:
                stat = path.stat()
            except OSError:
                digest.update(b"missing")
            else:
                digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode("ascii"))
        return digest.hexdigest()[:16]

    def revision(self) -> dict[str, str]:
        watched = [UI_DIR / "style.css", self.overrides]
        images = [
            path
            for root in (UI_DIR / "images", BUILD_UI_IMAGES)
            for path in root.rglob("*")
            if path.is_file()
        ]
        return {
            "styles": self._fingerprint(watched),
            "images": self._fingerprint(images),
        }


class ExtPreviewHandler(BaseHTTPRequestHandler):
    server: ExtPreviewServer

    def log_message(self, format: str, *args: object) -> None:
        if self.path.startswith("/__preview_revision"):
            return
        print(f"[ext-preview] {format % args}")

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
            self._send(b"Not found.\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)
            return
        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(body, content_type or guessed)

    def _serve_below(self, root: Path, relative: str) -> None:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            self._send(b"Not found.\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)
            return
        self._serve_file(candidate)

    def _serve_first_below(self, roots: tuple[Path, ...], relative: str) -> None:
        for root in roots:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                self._send(b"Not found.\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)
                return
            if candidate.is_file():
                self._serve_file(candidate)
                return
        self._send(b"Not found.\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)

    def _api_path(self) -> str:
        return parse_qs(urlsplit(self.path).query).get("path", [""])[0]

    def _api_get(self, path: str) -> None:
        if path == "/api/bootstrap":
            self._json(
                {
                    "setup_required": False,
                    "authenticated": True,
                    "dsm_authenticated": True,
                    "csrf": "ext-preview",
                    "session": "ext-preview-session",
                }
            )
            return
        if path == "/api/status":
            self._json(self.server.state.status())
            return
        self._json({"error": "Unknown mock API route."}, HTTPStatus.NOT_FOUND)

    def _api_write(self, path: str, body: dict[str, object]) -> None:
        state = self.server.state
        with state.lock:
            if path == "/api/service/start":
                state.running = True
            elif path == "/api/service/stop":
                state.running = False
            elif path == "/api/settings/storage":
                state.repo_path = str(body.get("repo_path", state.repo_path))
            elif path == "/api/directories":
                current = str(body.get("path", state.repo_path))
                self._json(
                    {
                        "path": current,
                        "parent": "/volume1" if current != "/volume1" else "/",
                        "directories": [
                            {"name": "archives", "path": f"{current.rstrip('/')}/archives", "writable": True},
                            {"name": "projects", "path": f"{current.rstrip('/')}/projects", "writable": True},
                            {"name": "readonly", "path": f"{current.rstrip('/')}/readonly", "writable": False},
                        ],
                    }
                )
                return
            elif path == "/api/repositories":
                state.repositories.append(
                    {
                        "name": str(body.get("name", "new-repository")),
                        "size_bytes": 0,
                        "modified_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            elif path == "/api/users":
                state.users.append(
                    {
                        "username": str(body.get("username", "new-user")),
                        "admin": bool(body.get("admin", False)),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            elif path.endswith("/password") or path in {"/api/login", "/api/logout", "/api/setup"}:
                pass
            else:
                self._json({"error": "Unknown mock API route."}, HTTPStatus.NOT_FOUND)
                return
        self._json({"ok": True, "csrf": "ext-preview", "session": "ext-preview-session"})

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/admin", "/admin/"):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/ext/")
            self.end_headers()
            return
        if path in ("/ext", "/ext/"):
            self._serve_file(PREVIEW_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/ext/desktop.css":
            self._serve_file(PREVIEW_DIR / "base.css", "text/css; charset=utf-8")
            return
        if path == "/ext/style.css":
            self._serve_file(UI_DIR / "style.css", "text/css; charset=utf-8")
            return
        if path == "/ext/overrides.css":
            self._serve_file(self.server.overrides, "text/css; charset=utf-8")
            return
        if path == "/ext/synology-shim.js":
            self._serve_file(PREVIEW_DIR / "synology-shim.js", "text/javascript; charset=utf-8")
            return
        if path == "/ext/preview.js":
            self._serve_file(PREVIEW_DIR / "preview.js", "text/javascript; charset=utf-8")
            return
        if path == "/ext/MercurialServer28.js":
            self._serve_file(UI_DIR / "MercurialServer28.js", "text/javascript; charset=utf-8")
            return
        if path.startswith("/ext/images/"):
            self._serve_first_below(
                (UI_DIR / "images", BUILD_UI_IMAGES), path[len("/ext/images/") :]
            )
            return
        if path.startswith("/ext/vendor/"):
            self._serve_below(VENDOR_DIR, path[len("/ext/vendor/") :])
            return
        if path == "/__preview_revision":
            self._json(self.server.revision())
            return
        if path == "/webman/3rdparty/mercurialserver/api.cgi":
            self._api_get(self._api_path())
            return
        self._send(b"Not found.\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/webman/3rdparty/mercurialserver/api.cgi":
            self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        self._api_write(self._api_path(), self._read_json())

    def do_DELETE(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/webman/3rdparty/mercurialserver/api.cgi":
            self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        path = self._api_path()
        prefix = "/api/users/"
        if not path.startswith(prefix):
            self._json({"error": "Unknown mock API route."}, HTTPStatus.NOT_FOUND)
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
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    overrides = args.overrides.expanduser()
    if not overrides.is_absolute():
        overrides = (Path.cwd() / overrides).resolve()
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.touch(exist_ok=True)
    server = ExtPreviewServer((args.host, args.port), overrides=overrides)
    url = f"http://{args.host}:{server.server_address[1]}/ext/"
    print(f"Running {UI_DIR / 'MercurialServer28.js'} with Ext JS 3.4.1.1")
    print(f"Production CSS: {UI_DIR / 'style.css'}")
    print(f"Local overrides: {overrides}")
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
