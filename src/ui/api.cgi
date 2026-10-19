#!/bin/sh
# DSM CGI entry point. Prefer Synology's newest supported Python package and
# execute the Python bridge without hard-coding a single package version.

find_python() {
    for candidate in \
        "${MERCURIAL_SERVER_PYTHON:-}" \
        /var/packages/Python3.12/target/usr/local/bin/python3.12 \
        /var/packages/Python3.12/target/usr/bin/python3.12 \
        /var/packages/Python3.12/target/bin/python3.12 \
        /var/packages/python312/target/bin/python3.12 \
        /var/packages/Python3.11/target/usr/local/bin/python3.11 \
        /var/packages/Python3.11/target/usr/bin/python3.11 \
        /var/packages/python311/target/bin/python3.11 \
        /var/packages/Python3.10/target/usr/local/bin/python3.10 \
        /var/packages/Python3.10/target/usr/bin/python3.10 \
        /var/packages/python310/target/bin/python3.10 \
        /var/packages/Python3.9/target/usr/local/bin/python3.9 \
        /var/packages/Python3.9/target/usr/bin/python3.9 \
        /var/packages/python39/target/bin/python3.9 \
        /var/packages/Python3*/target/usr/local/bin/python3* \
        /var/packages/Python3*/target/usr/bin/python3* \
        /var/packages/Python3*/target/bin/python3* \
        /var/packages/python3*/target/bin/python3* \
        /usr/local/bin/python3.12 \
        /usr/local/bin/python3.11 \
        /usr/local/bin/python3.10 \
        /usr/local/bin/python3.9 \
        /usr/local/bin/python3* \
        /usr/bin/python3
    do
        [ -n "$candidate" ] || continue
        if [ -x "$candidate" ] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

python_bin="$(find_python)" || {
    body='{"ok":false,"error":"Install Synology Python 3.12 or Python 3.9, then restart Mercurial Server."}'
    printf 'Status: 503 Service Unavailable\r\n'
    printf 'Content-Type: application/json; charset=utf-8\r\n'
    printf 'Cache-Control: no-store\r\n'
    printf 'Content-Length: %s\r\n\r\n%s' "${#body}" "$body"
    exit 0
}

script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
exec "$python_bin" "$script_dir/api_bridge.py"
