#!/usr/bin/env python3
"""DSM-authenticated, same-origin bridge to the package's local admin API."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
from http import HTTPStatus
from urllib.parse import parse_qs


AUTHENTICATE = "/usr/syno/synoman/webman/modules/authenticate.cgi"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
ALLOWED_METHODS = {"GET", "POST", "DELETE"}
MAX_BODY_SIZE = 1_048_576
FORWARDED_REQUEST_HEADERS = {
    "HTTP_COOKIE": "Cookie",
    "HTTP_X_CSRF_TOKEN": "X-CSRF-Token",
    "HTTP_X_MERCURIAL_SESSION": "X-Mercurial-Session",
}
FORWARDED_RESPONSE_HEADERS = {
    "content-type",
    "set-cookie",
    "cache-control",
    "x-content-type-options",
}


def emit(status: int, body: bytes, headers: list[tuple[str, str]] | None = None) -> None:
    reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Error"
    output = sys.stdout.buffer
    output.write(f"Status: {status} {reason}\r\n".encode("ascii"))
    sent_type = False
    for name, value in headers or []:
        if name.lower() in FORWARDED_RESPONSE_HEADERS:
            if name.lower() == "content-type":
                sent_type = True
            output.write(f"{name}: {value}\r\n".encode("latin-1", "replace"))
    if not sent_type:
        output.write(b"Content-Type: application/json; charset=utf-8\r\n")
    output.write(b"Cache-Control: no-store\r\n")
    output.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    output.write(body)
    output.flush()


def error(status: int, message: str) -> None:
    emit(status, json.dumps({"ok": False, "error": message}).encode("utf-8"))


def authenticated_dsm_user() -> str | None:
    # Used only by the local test suite. A browser cannot create this CGI env key.
    test_user = os.environ.get("MERCURIAL_SERVER_CGI_TEST_USER", "")
    if test_user and USERNAME_RE.fullmatch(test_user):
        return test_user
    try:
        result = subprocess.run(
            [AUTHENTICATE],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    username = result.stdout.strip()
    return username if result.returncode == 0 and USERNAME_RE.fullmatch(username) else None


def dsm_user_is_administrator(username: str) -> bool:
    # Test-only authentication is isolated behind a CGI environment name that
    # browsers cannot set.
    if os.environ.get("MERCURIAL_SERVER_CGI_TEST_USER") == username:
        return os.environ.get("MERCURIAL_SERVER_CGI_TEST_ADMIN", "1") != "0"
    identity = shutil.which("id")
    if not identity:
        return False
    try:
        result = subprocess.run(
            [identity, "-Gn", username],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "administrators" in result.stdout.split()


def read_body() -> bytes:
    # DSM's synoscgi does not consistently populate CONTENT_LENGTH for
    # JavaScript JSON requests. Some releases expose no value (or a non-numeric
    # placeholder) even though the decoded request body is available on stdin.
    # In that case, read to CGI EOF with the same hard size limit.
    raw_length = (
        os.environ.get("CONTENT_LENGTH")
        or os.environ.get("HTTP_CONTENT_LENGTH")
        or ""
    ).strip()
    length = None
    if raw_length:
        try:
            length = int(raw_length)
        except ValueError:
            length = None
    if length is not None and length > MAX_BODY_SIZE:
        raise ValueError("Request body is too large.")
    if length is not None and length > 0:
        body = sys.stdin.buffer.read(length)
    else:
        body = sys.stdin.buffer.read(MAX_BODY_SIZE + 1)
    if len(body) > MAX_BODY_SIZE:
        raise ValueError("Request body is too large.")
    return body


def main() -> None:
    dsm_user = authenticated_dsm_user()
    if not dsm_user:
        error(HTTPStatus.UNAUTHORIZED, "Sign in to DSM to use Mercurial Server.")
        return
    if not dsm_user_is_administrator(dsm_user):
        error(HTTPStatus.FORBIDDEN, "A DSM administrator account is required.")
        return

    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    if method not in ALLOWED_METHODS:
        error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")
        return

    query = parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)
    path = query.get("path", [""])[0]
    if not path.startswith("/api/") or "?" in path or "#" in path:
        error(HTTPStatus.BAD_REQUEST, "Invalid API path.")
        return

    if method == "GET":
        body = b""
    else:
        try:
            body = read_body()
        except ValueError as exc:
            error(HTTPStatus.BAD_REQUEST, str(exc))
            return

    headers: dict[str, str] = {}
    for env_name, header_name in FORWARDED_REQUEST_HEADERS.items():
        value = os.environ.get(env_name)
        if value:
            headers[header_name] = value
    # Tell the local manager how DSM received the request. Repository traffic
    # uses the same headers in the DSM nginx route; the API values are useful
    # for reporting the HTTPS endpoint in the native application.
    host = os.environ.get("HTTP_HOST", "").strip()
    if host:
        headers["X-Forwarded-Host"] = host
    request_scheme = os.environ.get("REQUEST_SCHEME", "").lower()
    if not request_scheme:
        request_scheme = "https" if os.environ.get("HTTPS", "").lower() in {
            "1",
            "on",
            "yes",
        } else "http"
    headers["X-Forwarded-Proto"] = request_scheme
    headers["X-DSM-User"] = dsm_user
    content_type = os.environ.get("CONTENT_TYPE")
    if content_type:
        headers["Content-Type"] = content_type
    elif method in {"POST", "DELETE"}:
        headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(body))

    port = int(os.environ.get("MERCURIAL_SERVER_CGI_TEST_PORT", "8090"))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request(method, path, body=body or None, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        emit(response.status, response_body, response.getheaders())
    except (OSError, http.client.HTTPException):
        error(HTTPStatus.BAD_GATEWAY, "The Mercurial Server package is not running.")
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected bridge error.")
