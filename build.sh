#!/bin/sh
set -eu
LC_ALL=C
export LC_ALL

ROOT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
WORK_DIR="$BUILD_DIR/work"
CACHE_DIR="$BUILD_DIR/cache"
PAYLOAD_DIR="$WORK_DIR/payload"
SPK_DIR="$WORK_DIR/spk"
MERCURIAL_VERSION="7.2.4"
MERCURIAL_ARCHIVE="mercurial-${MERCURIAL_VERSION}.tar.gz"
MERCURIAL_URL="https://www.mercurial-scm.org/release/${MERCURIAL_ARCHIVE}"
MERCURIAL_SHA256="85839e0f39e6cb893a88932aa36ef661759f3c5c5de4551ad26bd9df53cb71a2"
PACKAGE_INFO="$ROOT_DIR/package/INFO"
CURRENT_RELEASE="$(sed -n 's/^version="\([^"]*\)"$/\1/p' "$PACKAGE_INFO")"
PACKAGE_VERSION="${CURRENT_RELEASE%-*}"
CURRENT_BUILD="${CURRENT_RELEASE##*-}"
[ -n "$CURRENT_RELEASE" ] && [ "$PACKAGE_VERSION" != "$CURRENT_RELEASE" ] || {
    echo "package/INFO version must end in a numeric build suffix (for example 1.0.0-28)." >&2
    exit 1
}
case "$CURRENT_BUILD" in
    ''|*[!0-9]*)
        echo "package/INFO version must end in a numeric build suffix (for example 1.0.0-28)." >&2
        exit 1
        ;;
esac
BUILD_NUMBER=$((CURRENT_BUILD + 1))
PACKAGE_RELEASE="${PACKAGE_VERSION}-${BUILD_NUMBER}"
OUTPUT="$BUILD_DIR/mercurialserver-${PACKAGE_RELEASE}-noarch.spk"

find_build_python() {
    for candidate in \
        "${PYTHON:-}" \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /usr/bin/python3 \
        python3
    do
        [ -n "$candidate" ] || continue
        if "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

verify_sha256() {
    archive="$1"
    expected="$2"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$archive" | awk '{print $1}')"
    else
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    fi
    [ "$actual" = "$expected" ] || {
        echo "Checksum mismatch for $archive" >&2
        echo "Expected: $expected" >&2
        echo "Actual:   $actual" >&2
        return 1
    }
}

set_info_release() {
    file="$1"
    temporary="${file}.tmp.$$"
    sed "s/^version=\"[^\"]*\"$/version=\"${PACKAGE_RELEASE}\"/" "$file" > "$temporary"
    grep -q "^version=\"${PACKAGE_RELEASE}\"$" "$temporary" || {
        rm -f "$temporary"
        echo "Could not update version in $file" >&2
        return 1
    }
    mv "$temporary" "$file"
}

set_server_release() {
    file="$1"
    temporary="${file}.tmp.$$"
    sed \
        -e "s/^PACKAGE_VERSION = \"[^\"]*\"$/PACKAGE_VERSION = \"${PACKAGE_VERSION}\"/" \
        -e "s/^PACKAGE_BUILD = [0-9][0-9]*$/PACKAGE_BUILD = ${BUILD_NUMBER}/" \
        "$file" > "$temporary"
    grep -q "^PACKAGE_BUILD = ${BUILD_NUMBER}$" "$temporary" || {
        rm -f "$temporary"
        echo "Could not update build number in $file" >&2
        return 1
    }
    mv "$temporary" "$file"
}

set_ui_release() {
    file="$1"
    temporary="${file}.tmp.$$"
    sed \
        -e "s/Version [0-9][0-9.]* \(&middot; Build \)[0-9][0-9]*/Version ${PACKAGE_VERSION} \1${BUILD_NUMBER}/g" \
        "$file" > "$temporary"
    grep -q "Version ${PACKAGE_VERSION} &middot; Build ${BUILD_NUMBER}" "$temporary" || {
        rm -f "$temporary"
        echo "Could not update displayed build number in $file" >&2
        return 1
    }
    mv "$temporary" "$file"
}

mkdir -p "$BUILD_DIR" "$CACHE_DIR"
rm -rf "$WORK_DIR"
mkdir -p "$PAYLOAD_DIR/app" "$PAYLOAD_DIR/vendor" "$SPK_DIR"
BUILD_PYTHON="$(find_build_python)" || {
    echo "A working Python 3.9 or newer is required to build package icons." >&2
    exit 1
}

if [ ! -f "$CACHE_DIR/$MERCURIAL_ARCHIVE" ]; then
    echo "Downloading Mercurial ${MERCURIAL_VERSION}..."
    curl -fL --retry 3 --output "$CACHE_DIR/$MERCURIAL_ARCHIVE" "$MERCURIAL_URL"
fi
verify_sha256 "$CACHE_DIR/$MERCURIAL_ARCHIVE" "$MERCURIAL_SHA256"

echo "Assembling pure-Python package payload..."
mkdir -p "$WORK_DIR/mercurial-source"
tar -xzf "$CACHE_DIR/$MERCURIAL_ARCHIVE" -C "$WORK_DIR/mercurial-source"
cp -R "$WORK_DIR/mercurial-source/mercurial-${MERCURIAL_VERSION}" "$PAYLOAD_DIR/vendor/mercurial"
cp -R "$ROOT_DIR/src/mercurial_server" "$PAYLOAD_DIR/app/"
cp -R "$ROOT_DIR/src/www" "$PAYLOAD_DIR/"
cp -R "$ROOT_DIR/src/port_conf" "$PAYLOAD_DIR/"
cp -R "$ROOT_DIR/src/nginx" "$PAYLOAD_DIR/"
cp -R "$ROOT_DIR/src/ui" "$PAYLOAD_DIR/"
set_server_release "$PAYLOAD_DIR/app/mercurial_server/server.py"
for ui_script in "$PAYLOAD_DIR/ui"/MercurialServer*.js; do
    [ -f "$ui_script" ] && set_ui_release "$ui_script"
done
find "$PAYLOAD_DIR/ui" -type f -name '*.cgi' -exec chmod 755 {} +
find "$PAYLOAD_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +

cp "$ROOT_DIR/package/INFO" "$SPK_DIR/INFO"
set_info_release "$SPK_DIR/INFO"
cp -R "$ROOT_DIR/package/conf" "$SPK_DIR/conf"
cp -R "$ROOT_DIR/package/scripts" "$SPK_DIR/scripts"
cp "$ROOT_DIR/LICENSE" "$SPK_DIR/LICENSE"
# Every script in the package has to be executable, not just the one that
# happened to exist when this was written.
for script in "$SPK_DIR/scripts/"*; do
    [ -f "$script" ] && chmod 755 "$script"
done
"$BUILD_PYTHON" "$ROOT_DIR/tools/make_icons.py" \
    "$SPK_DIR" "$PAYLOAD_DIR/ui/images"

COPYFILE_DISABLE=1 tar --format ustar -czf "$SPK_DIR/package.tgz" \
    -C "$PAYLOAD_DIR" app vendor www port_conf nginx ui
rm -f "$OUTPUT"
COPYFILE_DISABLE=1 tar --format ustar -cf "$OUTPUT" -C "$SPK_DIR" \
    INFO package.tgz scripts conf LICENSE PACKAGE_ICON.PNG PACKAGE_ICON_256.PNG

set_info_release "$PACKAGE_INFO"
set_server_release "$ROOT_DIR/src/mercurial_server/server.py"
for ui_script in "$ROOT_DIR/src/ui"/MercurialServer*.js; do
    [ -f "$ui_script" ] && set_ui_release "$ui_script"
done

echo "Built: $OUTPUT"
echo "Build number advanced: $CURRENT_BUILD -> $BUILD_NUMBER"
