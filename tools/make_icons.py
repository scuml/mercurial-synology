#!/usr/bin/env python3
"""Generate dependency-free PNG package icons."""

import binascii
import shutil
import struct
import sys
import zlib
from pathlib import Path


def chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def icon(size: int) -> bytes:
    rows = []
    radius = size * 0.20
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx = max(radius - x, 0, x - (size - 1 - radius))
            dy = max(radius - y, 0, y - (size - 1 - radius))
            inside = dx * dx + dy * dy <= radius * radius
            if not inside:
                row.extend((0, 0, 0, 0))
                continue
            shade = int(28 + 20 * (1 - y / max(size - 1, 1)))
            color = (shade, shade + 24, shade + 11, 255)
            # Draw a compact geometric H and g without font dependencies.
            sx, sy = x / size, y / size
            mark = (
                (0.22 < sx < 0.29 and 0.27 < sy < 0.69)
                or (0.43 < sx < 0.50 and 0.27 < sy < 0.69)
                or (0.27 < sx < 0.45 and 0.45 < sy < 0.52)
                or (0.57 < sx < 0.78 and 0.40 < sy < 0.47)
                or (0.57 < sx < 0.64 and 0.40 < sy < 0.72)
                or (0.62 < sx < 0.78 and 0.65 < sy < 0.72)
                or (0.71 < sx < 0.78 and 0.43 < sy < 0.79)
            )
            row.extend((103, 211, 145, 255) if mark else color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 2:
        application_icons = Path(sys.argv[2])
        application_icons.mkdir(parents=True, exist_ok=True)
        package_icon = application_icons / "mercurialserver-neon-64.png"
        package_icon_256 = application_icons / "mercurialserver-neon-256.png"
        if package_icon.is_file() and package_icon_256.is_file():
            shutil.copyfile(package_icon, output / "PACKAGE_ICON.PNG")
            shutil.copyfile(package_icon_256, output / "PACKAGE_ICON_256.PNG")
            return

    (output / "PACKAGE_ICON.PNG").write_bytes(icon(64))
    (output / "PACKAGE_ICON_256.PNG").write_bytes(icon(256))
    if len(sys.argv) > 2:
        for size in (16, 24, 32, 48, 64, 72, 256):
            (application_icons / f"mercurialserver-neon-{size}.png").write_bytes(
                icon(size)
            )


if __name__ == "__main__":
    main()
