#!/usr/bin/env python3
"""Admin UI, authentication gateway, and process manager for Mercurial."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
import platform
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


LOGGER = logging.getLogger("mercurial-server")
PACKAGE_VERSION = "1.0.0"
PACKAGE_BUILD = 31
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DSM_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
REPO_PART_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SESSION_LIFETIME = 8 * 60 * 60
PASSWORD_ITERATIONS = 310_000
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
}


class UserError(Exception):
    """An error that is safe to display in the UI."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_password(password: str, salt: bytes | None = None) -> dict[str, Any]:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PASSWORD_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }


def password_matches(password: str, record: dict[str, Any]) -> bool:
    try:
        salt = base64.b64decode(record["salt"], validate=True)
        expected = base64.b64decode(record["hash"], validate=True)
        iterations = int(record["iterations"])
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
    except (KeyError, ValueError, TypeError, binascii.Error):
        return False


class ConfigStore:
    def __init__(self, var_dir: Path):
        self.var_dir = var_dir.resolve()
        self.path = self.var_dir / "settings.json"
        self._lock = threading.RLock()
        self.var_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(
                {
                    "schema": 1,
                    "repo_path": str(self.var_dir / "repositories"),
                    "https_base_url": "",
                    "hg_enabled": True,
                    "users": {},
                }
            )
        self.ensure_repo_path()

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def setup_required(self) -> bool:
        return not bool(self.snapshot().get("users"))

    def ensure_repo_path(self) -> Path:
        repo_path = Path(self.snapshot()["repo_path"])
        repo_path.mkdir(parents=True, exist_ok=True)
        return repo_path

    def repo_path(self) -> Path:
        return Path(self.snapshot()["repo_path"])

    def hg_enabled(self) -> bool:
        return bool(self.snapshot().get("hg_enabled", True))

    def set_hg_enabled(self, enabled: bool) -> None:
        with self._lock:
            data = self._read()
            data["hg_enabled"] = bool(enabled)
            self._write(data)

    def set_repo_path(self, raw_path: str) -> Path:
        if not raw_path or any(ord(char) < 32 for char in raw_path):
            raise UserError("Enter a valid repository path.")
        path = Path(raw_path)
        if not path.is_absolute():
            raise UserError("Repository storage must be an absolute path.")
        try:
            path.mkdir(parents=True, exist_ok=True)
            path = path.resolve(strict=True)
        except OSError as exc:
            raise UserError(f"Cannot create or access that path: {exc}") from exc
        if not path.is_dir():
            raise UserError("Repository storage must be a directory.")
        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise UserError(
                "The mercurialserver package user needs read/write permission on that folder."
            )
        with self._lock:
            data = self._read()
            data["repo_path"] = str(path)
            self._write(data)
        return path

    def https_base_url(self) -> str:
        return str(self.snapshot().get("https_base_url", "")).strip()

    def set_https_base_url(self, raw_url: str) -> str:
        raw_url = raw_url.strip()
        if not raw_url:
            value = ""
        else:
            parsed = urlsplit(raw_url)
            try:
                hostname = parsed.hostname
                parsed.port
            except ValueError as exc:
                raise UserError("The public HTTPS address has an invalid port.") from exc
            if (
                parsed.scheme.lower() != "https"
                or not hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or any(char.isspace() or ord(char) < 32 for char in raw_url)
            ):
                raise UserError(
                    "Enter an HTTPS address without credentials, a query, or a fragment."
                )
            path = parsed.path.rstrip("/")
            if path != "/hg":
                raise UserError("The public HTTPS address must end with /hg/.")
            value = f"https://{parsed.netloc}/hg/"
        with self._lock:
            data = self._read()
            data["https_base_url"] = value
            self._write(data)
        return value

    @staticmethod
    def _validate_username(username: str) -> str:
        username = username.strip()
        if not USERNAME_RE.fullmatch(username):
            raise UserError(
                "Username must be 1-64 characters using letters, numbers, dot, dash, or underscore."
            )
        return username

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 12:
            raise UserError("Password must be at least 12 characters.")
        if len(password) > 1024:
            raise UserError("Password is too long.")

    def add_user(self, username: str, password: str, admin: bool = False) -> None:
        username = self._validate_username(username)
        self._validate_password(password)
        with self._lock:
            data = self._read()
            users = data.setdefault("users", {})
            if username in users:
                raise UserError("That username already exists.")
            users[username] = {
                **hash_password(password),
                "admin": bool(admin),
                "created_at": utc_now(),
            }
            self._write(data)

    def bootstrap_admin(self, username: str, password: str) -> None:
        with self._lock:
            if self._read().get("users"):
                raise UserError("Initial setup has already been completed.")
            self.add_user(username, password, admin=True)

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.snapshot().get("users", {}).get(username)
        if user and password_matches(password, user):
            return {"username": username, "admin": bool(user.get("admin"))}
        # Make missing-user checks take approximately the same amount of work.
        if not user:
            password_matches(password, hash_password("timing-only"))
        return None

    def list_users(self) -> list[dict[str, Any]]:
        users = self.snapshot().get("users", {})
        return [
            {
                "username": username,
                "admin": bool(record.get("admin")),
                "created_at": record.get("created_at", ""),
            }
            for username, record in sorted(users.items(), key=lambda item: item[0].lower())
        ]

    def delete_user(self, username: str) -> None:
        with self._lock:
            data = self._read()
            users = data.get("users", {})
            if username not in users:
                raise UserError("User not found.")
            if users[username].get("admin"):
                admin_count = sum(bool(item.get("admin")) for item in users.values())
                if admin_count <= 1:
                    raise UserError("The last administrator cannot be deleted.")
            del users[username]
            self._write(data)

    def change_password(self, username: str, password: str) -> None:
        self._validate_password(password)
        with self._lock:
            data = self._read()
            user = data.get("users", {}).get(username)
            if user is None:
                raise UserError("User not found.")
            preserved = {
                "admin": bool(user.get("admin")),
                "created_at": user.get("created_at", utc_now()),
            }
            data["users"][username] = {**hash_password(password), **preserved}
            self._write(data)


class SessionManager:
    def __init__(self):
        self.secret = secrets.token_bytes(32)

    def create(
        self, username: str, admin: bool, source: str = "mercurial"
    ) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(24)
        payload = {
            "username": username,
            "admin": bool(admin),
            "source": source,
            "csrf": csrf,
            "expires": int(time.time()) + SESSION_LIFETIME,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
        signature = hmac.new(self.secret, encoded, hashlib.sha256).hexdigest().encode()
        return (encoded + b"." + signature).decode("ascii"), csrf

    def verify(self, token: str) -> dict[str, Any] | None:
        try:
            encoded, supplied_signature = token.encode("ascii").split(b".", 1)
            expected = hmac.new(self.secret, encoded, hashlib.sha256).hexdigest().encode()
            if not hmac.compare_digest(supplied_signature, expected):
                return None
            padding = b"=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
            if int(payload["expires"]) < int(time.time()):
                return None
            return payload
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error):
            return None


class MercurialBackend:
    def __init__(self, store: ConfigStore, var_dir: Path, hg_script: Path, port: int):
        self.store = store
        self.var_dir = var_dir
        self.hg_script = hg_script
        self.preferred_port = port
        self.port = port
        self.config_path = var_dir / "hgweb.config"
        self.pid_path = var_dir / "hg.pid"
        self.log_path = var_dir / "mercurial.log"
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None
        self.last_error: str | None = None

    def _select_available_port(self) -> int:
        for candidate in range(self.preferred_port, self.preferred_port + 20):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
            finally:
                probe.close()
        raise UserError(
            f"No private backend port is available in the range "
            f"{self.preferred_port}-{self.preferred_port + 19}."
        )

    def _log_tail(self) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        useful = [line.strip() for line in lines[-20:] if line.strip()]
        return useful[-1][:500] if useful else ""

    def _write_hg_config(self) -> None:
        repo_path = str(self.store.repo_path())
        if "\n" in repo_path or "\r" in repo_path:
            raise UserError("Repository path cannot contain line breaks.")
        content = (
            "[paths]\n"
            f"/ = {repo_path}/**\n\n"
            "[web]\n"
            "allow-push = *\n"
            "push_ssl = false\n"
            "allow-archive = gz zip\n"
            "style = paper\n"
        )
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.config_path)

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            self.store.ensure_repo_path()
            self.port = self._select_available_port()
            self._write_hg_config()
            self._log_handle = self.log_path.open("ab", buffering=0)
            env = os.environ.copy()
            env["HGMODULEPOLICY"] = "py"
            env["PYTHONPATH"] = str(self.hg_script.parent)
            # DSM's internal package accounts may not have a usable home or
            # temporary directory. Mercurial and Python both expect them.
            runtime_dir = self.var_dir / "runtime"
            temporary_dir = runtime_dir / "tmp"
            pycache_dir = runtime_dir / "pycache"
            temporary_dir.mkdir(parents=True, exist_ok=True)
            pycache_dir.mkdir(parents=True, exist_ok=True)
            env["HOME"] = str(runtime_dir)
            env["TMPDIR"] = str(temporary_dir)
            env["PYTHONPYCACHEPREFIX"] = str(pycache_dir)
            env["PYTHONNOUSERSITE"] = "1"
            command = [
                sys.executable,
                str(self.hg_script),
                "serve",
                "--web-conf",
                str(self.config_path),
                "--address",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--prefix",
                "hg",
            ]
            LOGGER.info("Starting Mercurial backend on 127.0.0.1:%d", self.port)
            self.last_error = None
            self._process = subprocess.Popen(
                command,
                cwd=str(self.var_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.pid_path.write_text(f"{self._process.pid}\n", encoding="ascii")

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.stop()
                detail = self._log_tail()
                self.last_error = detail or "The Mercurial process exited during startup."
                raise UserError(f"Mercurial failed to start: {self.last_error}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.25):
                    return
            except OSError:
                time.sleep(0.1)
        self.stop()
        detail = self._log_tail()
        self.last_error = detail or "The Mercurial process did not open its private port."
        raise UserError(f"Mercurial failed to start: {self.last_error}")

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process and process.poll() is None:
                LOGGER.info("Stopping Mercurial backend")
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            self.pid_path.unlink(missing_ok=True)
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None

    def restart_if_running(self) -> None:
        was_running = self.is_running()
        if was_running:
            self.stop()
            self.start()


class Application:
    def __init__(self, var_dir: Path, static_dir: Path, hg_script: Path, backend_port: int):
        self.var_dir = var_dir.resolve()
        self.static_dir = static_dir.resolve()
        self.hg_script = hg_script.resolve()
        self.store = ConfigStore(self.var_dir)
        self.sessions = SessionManager()
        self.backend = MercurialBackend(
            self.store, self.var_dir, self.hg_script, backend_port
        )

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        for current, _directories, files in os.walk(path, followlinks=False):
            for filename in files:
                try:
                    total += (Path(current) / filename).lstat().st_size
                except OSError:
                    continue
        return total

    def list_repositories(self) -> list[dict[str, Any]]:
        root = self.store.repo_path()
        repositories: list[dict[str, Any]] = []
        if not root.is_dir():
            return repositories
        for current, directories, _files in os.walk(root):
            if ".hg" in directories:
                path = Path(current)
                try:
                    relative = path.relative_to(root).as_posix() or path.name
                    modified = datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc
                    ).replace(microsecond=0).isoformat()
                    repositories.append(
                        {
                            "name": relative,
                            "size_bytes": self._directory_size(path),
                            "modified_at": modified,
                        }
                    )
                except OSError:
                    pass
                directories[:] = []
            else:
                directories[:] = [
                    item for item in directories if not item.startswith(".")
                ]
        return sorted(repositories, key=lambda item: item["name"].lower())

    def list_directories(self, raw_path: str) -> dict[str, Any]:
        if not raw_path or any(ord(char) < 32 for char in raw_path):
            raise UserError("Choose a valid folder.")
        requested = Path(raw_path)
        if not requested.is_absolute():
            raise UserError("The folder path must be absolute.")
        try:
            current = requested.resolve(strict=True)
        except OSError as exc:
            raise UserError(f"Cannot access that folder: {exc}") from exc
        if not current.is_dir():
            raise UserError("The selected path is not a folder.")
        directories: list[dict[str, Any]] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if not entry.is_dir(follow_symlinks=True):
                            continue
                        path = Path(entry.path).resolve(strict=True)
                        directories.append(
                            {
                                "name": entry.name,
                                "path": str(path),
                                "writable": os.access(
                                    path, os.R_OK | os.W_OK | os.X_OK
                                ),
                            }
                        )
                    except OSError:
                        continue
        except OSError as exc:
            raise UserError(f"Cannot read that folder: {exc}") from exc
        parent = current.parent if current.parent != current else None
        return {
            "ok": True,
            "path": str(current),
            "parent": str(parent) if parent else None,
            "writable": os.access(current, os.R_OK | os.W_OK | os.X_OK),
            "directories": sorted(
                directories, key=lambda item: str(item["name"]).lower()
            ),
        }

    def create_repository(self, raw_name: str) -> str:
        raw_name = raw_name.strip().strip("/")
        parts = raw_name.split("/") if raw_name else []
        if not parts or any(not REPO_PART_RE.fullmatch(part) for part in parts):
            raise UserError(
                "Repository names may contain letters, numbers, dot, dash, underscore, and / separators."
            )
        root = self.store.repo_path().resolve(strict=True)
        destination = root.joinpath(*parts)
        try:
            resolved_parent = destination.parent.resolve(strict=False)
            resolved_parent.relative_to(root)
        except (OSError, ValueError) as exc:
            raise UserError("Repository must be inside the configured storage folder.") from exc
        if destination.exists():
            raise UserError("A file or repository with that name already exists.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HGMODULEPOLICY"] = "py"
        env["PYTHONPATH"] = str(self.hg_script.parent)
        result = subprocess.run(
            [sys.executable, str(self.hg_script), "init", str(destination)],
            env=env,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise UserError(result.stderr.strip() or "Mercurial could not create the repository.")
        # hgwebdir caches repository discovery. Refresh the private backend so a
        # repository created in the same filesystem timestamp tick is visible
        # immediately instead of briefly returning 404.
        self.backend.restart_if_running()
        return "/".join(parts)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "MercurialServer/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> Application:
        return self.server.application  # type: ignore[attr-defined]

    def log_message(self, message: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], message % args)

    def _json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise UserError("Invalid request length.") from exc
        if length < 0 or length > 1_048_576:
            raise UserError("Invalid request body.")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UserError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise UserError("Request body must be a JSON object.")
        return value

    def _session(self) -> dict[str, Any] | None:
        header_token = self.headers.get("X-Mercurial-Session", "").strip()
        if header_token:
            session = self.app.sessions.verify(header_token)
            if session:
                return session
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get("hg_session")
        return self.app.sessions.verify(morsel.value) if morsel else None

    def _trusted_dsm_admin(self) -> str | None:
        try:
            address = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return None
        username = self.headers.get("X-DSM-User", "").strip()
        if not address.is_loopback or not DSM_USERNAME_RE.fullmatch(username):
            return None
        return username

    def _require_admin(self, csrf: bool = False) -> dict[str, Any] | None:
        session = self._session()
        if not session:
            self._error(HTTPStatus.UNAUTHORIZED, "Sign in is required.")
            return None
        if session.get("source") == "dsm":
            dsm_user = self._trusted_dsm_admin()
            if not dsm_user or dsm_user != session.get("username"):
                self._error(HTTPStatus.UNAUTHORIZED, "DSM administrator session expired.")
                return None
        else:
            current_user = self.app.store.snapshot().get("users", {}).get(
                session.get("username")
            )
            if (
                not session.get("admin")
                or not current_user
                or not current_user.get("admin")
            ):
                self._error(HTTPStatus.FORBIDDEN, "Administrator access is required.")
                return None
        if csrf and not hmac.compare_digest(
            str(session.get("csrf", "")), self.headers.get("X-CSRF-Token", "")
        ):
            self._error(HTTPStatus.FORBIDDEN, "Security token is missing or expired.")
            return None
        return session

    def _serve_static(self, relative: str, content_type: str) -> None:
        candidate = (self.app.static_dir / relative).resolve()
        try:
            candidate.relative_to(self.app.static_dir)
            data = candidate.read_bytes()
        except (ValueError, OSError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "base-uri 'none'; frame-ancestors http: https:",
        )
        self.end_headers()
        self.wfile.write(data)

    def _basic_user(self) -> dict[str, Any] | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Basic "):
            return None
        try:
            raw = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            username, password = raw.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return None
        return self.app.store.authenticate(username, password)

    def _proxy_hg(self) -> None:
        forwarded_protocol = self.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_protocol and forwarded_protocol != "https":
            body = b"Mercurial Server requires HTTPS. Connect through DSM HTTPS.\n"
            self.send_response(HTTPStatus.UPGRADE_REQUIRED)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return
        if self.app.store.setup_required():
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "Complete initial setup first.")
            return
        user = self._basic_user()
        if not user:
            body = b"Mercurial credentials required\n"
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="Mercurial Server"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.app.backend.is_running():
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "Mercurial service is stopped.")
            return

        connection = http.client.HTTPConnection(
            "127.0.0.1", self.app.backend.port, timeout=300
        )
        response_started = False
        try:
            connection.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for name, value in self.headers.items():
                lowered = name.lower()
                if lowered not in HOP_HEADERS and lowered not in {
                    "authorization",
                    "x-authenticated-user",
                }:
                    connection.putheader(name, value)
            connection.putheader("X-Authenticated-User", user["username"])
            connection.putheader("Connection", "close")
            connection.endheaders()
            self._forward_request_body(connection)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_HEADERS and name.lower() != "transfer-encoding":
                    self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            response_started = True
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
            self.close_connection = True
        except (OSError, ValueError, http.client.HTTPException) as exc:
            LOGGER.warning("Mercurial proxy error: %s", exc)
            if not response_started and not self.wfile.closed:
                try:
                    self._error(HTTPStatus.BAD_GATEWAY, "Mercurial backend is unavailable.")
                except OSError:
                    pass
        finally:
            connection.close()

    def _forward_request_body(self, connection: http.client.HTTPConnection) -> None:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if transfer_encoding == "chunked":
            while True:
                line = self.rfile.readline(65538)
                if not line or len(line) > 65537:
                    raise OSError("Invalid chunked request")
                connection.send(line)
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size == 0:
                    while True:
                        trailer = self.rfile.readline(65538)
                        connection.send(trailer)
                        if trailer in (b"\r\n", b"\n", b""):
                            return
                remaining = size + 2
                while remaining:
                    data = self.rfile.read(min(64 * 1024, remaining))
                    if not data:
                        raise OSError("Incomplete request body")
                    connection.send(data)
                    remaining -= len(data)
        try:
            remaining = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise OSError("Invalid content length") from exc
        while remaining:
            data = self.rfile.read(min(64 * 1024, remaining))
            if not data:
                raise OSError("Incomplete request body")
            connection.send(data)
            remaining -= len(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/admin", "/admin/"):
            if path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/admin/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/admin/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/admin/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if path == "/api/bootstrap":
            session = self._session()
            dsm_user = self._trusted_dsm_admin()
            response_headers = None
            session_token = None
            if dsm_user:
                if not (
                    session
                    and session.get("source") == "dsm"
                    and session.get("username") == dsm_user
                ):
                    session_token, csrf = self.app.sessions.create(
                        dsm_user, True, source="dsm"
                    )
                    session = self.app.sessions.verify(session_token)
                    response_headers = {"Set-Cookie": self._session_cookie(session_token)}
                else:
                    csrf = session.get("csrf")
                authenticated = True
            else:
                csrf = session.get("csrf") if session else None
                authenticated = bool(session and session.get("admin"))
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "setup_required": self.app.store.setup_required(),
                    "authenticated": authenticated,
                    "dsm_authenticated": bool(dsm_user),
                    "username": session.get("username") if session else None,
                    "csrf": csrf,
                    "session": session_token,
                },
                response_headers,
            )
            return
        if path == "/api/status":
            if not self._require_admin():
                return
            # Recreate the configured directory if it was removed while the
            # package was stopped. This also guarantees the first-run default.
            repo_path = self.app.store.ensure_repo_path()
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "running": self.app.backend.is_running(),
                    "backend_port": self.app.backend.port,
                    "backend_error": self.app.backend.last_error,
                    "python_version": platform.python_version(),
                    "python_executable": sys.executable,
                    "package_version": PACKAGE_VERSION,
                    "package_build": PACKAGE_BUILD,
                    "repo_path": str(repo_path),
                    "repo_writable": os.access(repo_path, os.R_OK | os.W_OK | os.X_OK),
                    "repositories": self.app.list_repositories(),
                    "users": self.app.store.list_users(),
                    "hg_path": "/hg/",
                    "https_base_url": self.app.store.https_base_url(),
                    "https_configured": True,
                    "https_mode": "DSM integrated web-config",
                    "proxy_destination": "http://127.0.0.1:8090",
                },
            )
            return
        if path.startswith("/hg"):
            self._proxy_hg()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path.startswith("/hg"):
            self._proxy_hg()
            return
        try:
            body = self._read_json()
            if path == "/api/setup":
                address = ipaddress.ip_address(self.client_address[0])
                if not (address.is_private or address.is_loopback or address.is_link_local):
                    self._error(
                        HTTPStatus.FORBIDDEN,
                        "Initial setup is allowed only from the local network.",
                    )
                    return
                self.app.store.bootstrap_admin(
                    str(body.get("username", "")), str(body.get("password", ""))
                )
                token, csrf = self.app.sessions.create(
                    str(body.get("username", "")).strip(), True
                )
                self._json(
                    HTTPStatus.CREATED,
                    {"ok": True, "csrf": csrf, "session": token},
                    {"Set-Cookie": self._session_cookie(token)},
                )
                return
            if path == "/api/login":
                user = self.app.store.authenticate(
                    str(body.get("username", "")), str(body.get("password", ""))
                )
                if not user or not user["admin"]:
                    self._error(HTTPStatus.UNAUTHORIZED, "Invalid administrator credentials.")
                    return
                token, csrf = self.app.sessions.create(user["username"], True)
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "csrf": csrf, "session": token},
                    {"Set-Cookie": self._session_cookie(token)},
                )
                return
            if path == "/api/logout":
                self._json(
                    HTTPStatus.OK,
                    {"ok": True},
                    {"Set-Cookie": "hg_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"},
                )
                return
            if not self._require_admin(csrf=True):
                return
            if path == "/api/service/start":
                self.app.backend.start()
                self.app.store.set_hg_enabled(True)
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/service/stop":
                self.app.store.set_hg_enabled(False)
                self.app.backend.stop()
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/directories":
                self._json(
                    HTTPStatus.OK,
                    self.app.list_directories(str(body.get("path", "/"))),
                )
                return
            if path == "/api/settings/storage":
                was_running = self.app.backend.is_running()
                self.app.store.set_repo_path(str(body.get("repo_path", "")))
                if was_running:
                    self.app.backend.stop()
                    self.app.backend.start()
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/settings/https":
                value = self.app.store.set_https_base_url(
                    str(body.get("https_base_url", ""))
                )
                self._json(HTTPStatus.OK, {"ok": True, "https_base_url": value})
                return
            if path == "/api/users":
                self.app.store.add_user(
                    str(body.get("username", "")),
                    str(body.get("password", "")),
                    bool(body.get("admin", False)),
                )
                self._json(HTTPStatus.CREATED, {"ok": True})
                return
            if path.startswith("/api/users/") and path.endswith("/password"):
                username = unquote(path[len("/api/users/") : -len("/password")]).strip("/")
                self.app.store.change_password(username, str(body.get("password", "")))
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/repositories":
                name = self.app.create_repository(str(body.get("name", "")))
                self._json(HTTPStatus.CREATED, {"ok": True, "name": name})
                return
            self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except UserError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            LOGGER.exception("Unhandled request error")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected server error.")

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if not self._require_admin(csrf=True):
            return
        try:
            if path.startswith("/api/users/"):
                username = unquote(path[len("/api/users/") :]).strip("/")
                session = self._session()
                if session and username == session.get("username"):
                    raise UserError("You cannot delete the account you are signed in with.")
                self.app.store.delete_user(username)
                self._json(HTTPStatus.OK, {"ok": True})
                return
            self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except UserError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    @staticmethod
    def _session_cookie(token: str) -> str:
        return (
            f"hg_session={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={SESSION_LIFETIME}"
        )


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], application: Application):
        self.application = application
        super().__init__(address, RequestHandler)

    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            LOGGER.debug("Client %s disconnected", client_address[0])
            return
        super().handle_error(request, client_address)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--backend-port", type=int, default=8091)
    parser.add_argument("--var-dir", type=Path, required=True)
    parser.add_argument("--static-dir", type=Path, required=True)
    parser.add_argument("--hg-script", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.var_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.var_dir / "manager.log", encoding="utf-8"),
        ],
    )
    app = Application(args.var_dir, args.static_dir, args.hg_script, args.backend_port)
    server = Server((args.host, args.port), app)

    def stop_server(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    if app.store.hg_enabled():
        try:
            app.backend.start()
        except UserError as exc:
            LOGGER.error("Backend startup failed: %s", exc)
    LOGGER.info("Manager listening on %s:%d", args.host, args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        app.backend.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
