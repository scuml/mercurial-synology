#!/usr/bin/env python3
"""Draw the native 18px toolbar icons without scaling or antialiasing."""

import binascii
import struct
import sys
import zlib
from pathlib import Path


SIZE = 18
T = (0, 0, 0, 0)
INK = (35, 35, 35, 255)
WHITE = (255, 255, 255, 255)
GRAY = (155, 155, 155, 255)
LIGHT_GRAY = (222, 222, 222, 255)
DARK_GRAY = (88, 88, 88, 255)
YELLOW = (248, 217, 85, 255)
PALE_YELLOW = (255, 241, 151, 255)
DARK_YELLOW = (184, 142, 32, 255)
BLUE = (55, 104, 210, 255)
LIGHT_BLUE = (109, 159, 244, 255)
DARK_BLUE = (24, 57, 137, 255)
GREEN = (43, 175, 54, 255)
LIGHT_GREEN = (105, 220, 87, 255)
DARK_GREEN = (20, 103, 29, 255)
RED = (220, 43, 43, 255)
LIGHT_RED = (255, 105, 96, 255)
DARK_RED = (139, 24, 24, 255)
SKIN = (235, 177, 108, 255)
LIGHT_SKIN = (255, 211, 151, 255)
DARK_SKIN = (173, 111, 62, 255)
HAIR = (89, 58, 42, 255)


class Canvas:
    def __init__(self) -> None:
        self.pixels = [[T for _x in range(SIZE)] for _y in range(SIZE)]

    def pixel(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < SIZE and 0 <= y < SIZE:
            self.pixels[y][x] = color

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int]) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.pixel(x, y, color)

    def hline(self, x0: int, x1: int, y: int, color: tuple[int, int, int, int]) -> None:
        self.rect(x0, y, x1, y, color)

    def vline(self, x: int, y0: int, y1: int, color: tuple[int, int, int, int]) -> None:
        self.rect(x, y0, x, y1, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int], width: int = 1) -> None:
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        radius = width // 2
        while True:
            self.rect(x0 - radius, y0 - radius, x0 + radius, y0 + radius, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy


def repository_icon() -> Canvas:
    c = Canvas()
    c.rect(2, 3, 8, 5, INK)
    c.rect(3, 4, 7, 5, PALE_YELLOW)
    c.rect(1, 5, 16, 14, INK)
    c.rect(2, 6, 15, 13, YELLOW)
    c.hline(3, 14, 6, WHITE)
    c.vline(2, 7, 12, PALE_YELLOW)
    c.hline(2, 15, 13, DARK_YELLOW)
    c.hline(3, 14, 14, INK)
    # Green add badge, drawn last for a clean one-pixel outline.
    c.rect(12, 9, 15, 17, INK)
    c.rect(9, 12, 17, 15, INK)
    c.rect(13, 10, 14, 16, GREEN)
    c.rect(10, 13, 16, 14, GREEN)
    c.pixel(13, 10, LIGHT_GREEN)
    c.pixel(10, 13, LIGHT_GREEN)
    c.hline(13, 14, 16, DARK_GREEN)
    c.vline(16, 13, 14, DARK_GREEN)
    return c


def refresh_icon() -> Canvas:
    c = Canvas()
    # Upper clockwise arrow: black three-pixel stroke with a blue core.
    upper = [(3, 8, 4, 5), (4, 5, 7, 2), (7, 2, 12, 2), (12, 2, 15, 5)]
    lower = [(15, 10, 14, 13), (14, 13, 11, 16), (11, 16, 6, 16), (6, 16, 3, 13)]
    for segment in upper + lower:
        c.line(*segment, INK, width=3)
    for segment in upper:
        c.line(*segment, BLUE)
    for segment in lower:
        c.line(*segment, LIGHT_BLUE)
    # Arrow heads.
    c.hline(14, 17, 5, INK)
    c.hline(14, 17, 6, INK)
    c.hline(14, 17, 7, INK)
    c.hline(15, 17, 8, INK)
    c.hline(16, 17, 9, INK)
    c.hline(15, 16, 6, BLUE)
    c.hline(15, 16, 7, LIGHT_BLUE)
    c.pixel(16, 8, BLUE)
    c.hline(0, 3, 9, INK)
    c.hline(0, 3, 10, INK)
    c.hline(0, 3, 11, INK)
    c.hline(0, 2, 12, INK)
    c.hline(0, 1, 13, INK)
    c.hline(1, 2, 10, LIGHT_BLUE)
    c.hline(1, 2, 11, BLUE)
    c.pixel(1, 12, DARK_BLUE)
    c.pixel(5, 4, WHITE)
    c.pixel(12, 14, WHITE)
    return c


def user_icon() -> Canvas:
    c = Canvas()
    # Head and hair.
    c.hline(6, 11, 0, INK)
    c.hline(4, 13, 1, INK)
    c.rect(3, 2, 14, 7, INK)
    c.hline(4, 13, 8, INK)
    c.rect(5, 2, 12, 7, SKIN)
    c.hline(6, 11, 1, HAIR)
    c.hline(5, 12, 2, HAIR)
    c.vline(5, 3, 5, HAIR)
    c.pixel(6, 3, LIGHT_SKIN)
    c.pixel(6, 4, WHITE)
    c.hline(7, 11, 7, DARK_SKIN)
    # Blue shoulders and torso.
    c.hline(4, 13, 9, INK)
    c.hline(2, 15, 10, INK)
    c.rect(1, 11, 16, 17, INK)
    c.rect(3, 11, 14, 16, BLUE)
    c.hline(5, 12, 10, LIGHT_BLUE)
    c.vline(3, 12, 15, LIGHT_BLUE)
    c.hline(4, 13, 16, DARK_BLUE)
    # Add badge.
    c.rect(13, 9, 15, 17, INK)
    c.rect(10, 12, 17, 15, INK)
    c.vline(14, 10, 16, GREEN)
    c.vline(15, 10, 16, GREEN)
    c.rect(11, 13, 16, 14, GREEN)
    c.pixel(14, 10, LIGHT_GREEN)
    c.pixel(11, 13, LIGHT_GREEN)
    c.hline(14, 15, 16, DARK_GREEN)
    return c


def password_icon() -> Canvas:
    c = Canvas()
    # Gold key bow.
    c.hline(3, 8, 0, INK)
    c.hline(1, 10, 1, INK)
    c.rect(0, 2, 11, 9, INK)
    c.hline(1, 10, 10, INK)
    c.hline(3, 8, 11, INK)
    c.rect(2, 2, 9, 9, YELLOW)
    c.rect(4, 4, 8, 8, INK)
    c.rect(5, 5, 7, 7, T)
    c.hline(3, 8, 2, PALE_YELLOW)
    c.vline(2, 3, 6, WHITE)
    c.hline(3, 8, 9, DARK_YELLOW)
    # Shaft and teeth.
    c.line(9, 8, 17, 16, INK, width=3)
    c.line(9, 8, 16, 15, YELLOW)
    c.line(10, 8, 16, 14, PALE_YELLOW)
    c.rect(13, 13, 16, 17, INK)
    c.rect(14, 13, 15, 16, YELLOW)
    c.rect(9, 12, 13, 15, INK)
    c.rect(10, 12, 12, 14, DARK_YELLOW)
    c.pixel(10, 9, WHITE)
    return c


def delete_icon() -> Canvas:
    c = Canvas()
    # Classic ribbed trash can.
    c.rect(6, 0, 11, 1, INK)
    c.rect(5, 1, 12, 3, INK)
    c.rect(6, 2, 11, 2, LIGHT_GRAY)
    c.rect(2, 3, 15, 6, INK)
    c.hline(3, 14, 4, LIGHT_GRAY)
    c.hline(4, 13, 5, WHITE)
    c.rect(3, 6, 14, 17, INK)
    c.rect(4, 7, 13, 16, GRAY)
    c.vline(5, 8, 15, LIGHT_GRAY)
    c.vline(7, 8, 15, DARK_GRAY)
    c.vline(9, 8, 15, LIGHT_GRAY)
    c.vline(11, 8, 15, DARK_GRAY)
    c.hline(4, 13, 16, DARK_GRAY)
    # Red remove badge.
    c.hline(12, 15, 10, INK)
    c.hline(10, 17, 11, INK)
    c.rect(9, 12, 17, 16, INK)
    c.hline(11, 16, 17, INK)
    c.rect(10, 12, 16, 16, RED)
    c.hline(11, 15, 13, WHITE)
    c.hline(11, 15, 14, WHITE)
    c.pixel(11, 12, LIGHT_RED)
    c.hline(11, 15, 16, DARK_RED)
    return c


def png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def write_png(path: Path, canvas: Canvas) -> None:
    rows = []
    for row in canvas.pixels:
        packed = bytearray([0])
        for pixel in row:
            packed.extend(pixel)
        rows.append(bytes(packed))
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
    data += png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + png_chunk(b"IEND", b"")
    path.write_bytes(data)


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "src/ui/images")
    output.mkdir(parents=True, exist_ok=True)
    icons = {
        "action-mac8-native-repository-add.png": repository_icon(),
        "action-mac8-native-refresh.png": refresh_icon(),
        "action-mac8-native-user-add.png": user_icon(),
        "action-mac8-native-password.png": password_icon(),
        "action-mac8-native-delete.png": delete_icon(),
    }
    for filename, canvas in icons.items():
        write_png(output / filename, canvas)


if __name__ == "__main__":
    main()
