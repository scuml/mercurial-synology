#!/bin/sh
set -eu

# Build and deploy Mercurial Server to a DSM NAS over SSH.
#
# Usage:
#   ./deploy.sh [DSM_ADMIN@NAS]
#
# Optional environment variables:
#   DEPLOY_NAS=192.168.1.8
#   DEPLOY_SSH_PORT=22
#   DEPLOY_HTTPS_PORT=5001

DEPLOY_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
DEPLOY_NAS="${DEPLOY_NAS:-192.168.1.8}"
if [ "$#" -gt 0 ]; then
    DEPLOY_TARGET="$1"
else
    printf 'DSM administrator username: '
    IFS= read -r DEPLOY_USERNAME
    DEPLOY_TARGET="$DEPLOY_USERNAME@$DEPLOY_NAS"
fi
DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22}"
DEPLOY_HTTPS_PORT="${DEPLOY_HTTPS_PORT:-5001}"

case "$DEPLOY_TARGET" in
    ""|@*|*@|*[!A-Za-z0-9._:@%+-]*)
        echo "Invalid deploy target: $DEPLOY_TARGET" >&2
        exit 2
        ;;
esac
case "$DEPLOY_SSH_PORT" in
    ""|*[!0-9]*)
        echo "DEPLOY_SSH_PORT must be a port number." >&2
        exit 2
        ;;
esac
case "$DEPLOY_HTTPS_PORT" in
    ""|*[!0-9]*)
        echo "DEPLOY_HTTPS_PORT must be a port number." >&2
        exit 2
        ;;
esac

echo "Building Mercurial Server..."
"$DEPLOY_ROOT/build.sh"
PACKAGE_RELEASE="$(sed -n 's/^version="\([^"]*\)"$/\1/p' "$DEPLOY_ROOT/package/INFO")"
DEPLOY_PACKAGE="$DEPLOY_ROOT/build/mercurialserver-${PACKAGE_RELEASE}-noarch.spk"
DEPLOY_REMOTE_PACKAGE="/tmp/mercurialserver-${PACKAGE_RELEASE}-noarch.spk"

echo "Uploading $(basename "$DEPLOY_PACKAGE") to $DEPLOY_TARGET..."
# OpenSSH 9 uses SFTP for scp by default. DSM installations without the SFTP
# subsystem return "subsystem request failed"; -O selects the compatible
# legacy SCP protocol while retaining SSH encryption and authentication.
scp -O -P "$DEPLOY_SSH_PORT" "$DEPLOY_PACKAGE" \
    "$DEPLOY_TARGET:$DEPLOY_REMOTE_PACKAGE"

echo "Installing package on DSM..."
# A TTY lets DSM prompt for the administrator's sudo password. All interpolated
# values below are validated or fixed paths.
# shellcheck disable=SC2029
ssh -tt -p "$DEPLOY_SSH_PORT" "$DEPLOY_TARGET" "
set -eu
trap 'rm -f $DEPLOY_REMOTE_PACKAGE' EXIT HUP INT TERM
DEPLOY_SYNOPKG=\"\$(command -v synopkg 2>/dev/null || true)\"
if [ -z \"\$DEPLOY_SYNOPKG\" ]; then
    DEPLOY_SYNOPKG=/usr/syno/bin/synopkg
fi
if [ ! -x \"\$DEPLOY_SYNOPKG\" ]; then
    echo 'DSM synopkg command was not found.' >&2
    exit 1
fi
sudo -v
if ! sudo \"\$DEPLOY_SYNOPKG\" install $DEPLOY_REMOTE_PACKAGE; then
    echo 'Package installation failed. Recent DSM package log:' >&2
    sudo tail -n 80 /var/log/synopkg.log 2>/dev/null || true
    exit 1
fi
sudo \"\$DEPLOY_SYNOPKG\" start mercurialserver >/dev/null 2>&1 || true
sudo \"\$DEPLOY_SYNOPKG\" status mercurialserver
"

DEPLOY_HOST="${DEPLOY_TARGET#*@}"
case "$DEPLOY_HOST" in
    *:*) DEPLOY_HTTPS_HOST="[$DEPLOY_HOST]" ;;
    *) DEPLOY_HTTPS_HOST="$DEPLOY_HOST" ;;
esac
DEPLOY_URL="https://$DEPLOY_HTTPS_HOST:$DEPLOY_HTTPS_PORT/hg/"

if command -v curl >/dev/null 2>&1; then
    echo "Checking the DSM-integrated HTTPS route..."
    # Certificate verification is deliberately skipped only for this readiness
    # probe because a LAN address commonly differs from the certificate name.
    DEPLOY_HTTP_STATUS="$(curl --insecure --silent --show-error \
        --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 10 "$DEPLOY_URL" || true)"
    case "$DEPLOY_HTTP_STATUS" in
        401)
            echo "HTTPS gateway is ready (authentication required as expected)."
            ;;
        503)
            echo "HTTPS gateway is ready; finish first-time setup in the DSM app."
            ;;
        *)
            echo "Package is installed, but HTTPS verification returned HTTP ${DEPLOY_HTTP_STATUS:-no-response}." >&2
            echo "Check $DEPLOY_URL after DSM finishes reloading nginx." >&2
            exit 1
            ;;
    esac
fi

echo "Deployed successfully: $DEPLOY_URL"
