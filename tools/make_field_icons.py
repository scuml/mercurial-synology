#!/usr/bin/env python3
"""Draw crisp, full-size 18px Mac OS 8-style field and folder icons."""

import sys
from pathlib import Path

from make_action_icons import (
    BLUE,
    DARK_BLUE,
    DARK_YELLOW,
    INK,
    LIGHT_BLUE,
    PALE_YELLOW,
    WHITE,
    YELLOW,
    Canvas,
    write_png,
)


def copy_icon() -> Canvas:
    canvas = Canvas()
    # Rear page.
    canvas.rect(5, 0, 14, 1, INK)
    canvas.rect(4, 1, 15, 12, INK)
    canvas.rect(5, 2, 14, 11, WHITE)
    canvas.hline(7, 12, 4, LIGHT_BLUE)
    canvas.hline(7, 13, 6, BLUE)
    canvas.hline(7, 12, 8, LIGHT_BLUE)
    # Front page, offset down and left so both sheets remain legible at 18px.
    canvas.rect(2, 4, 11, 5, INK)
    canvas.rect(1, 5, 12, 16, INK)
    canvas.rect(2, 6, 11, 15, WHITE)
    canvas.vline(2, 6, 14, LIGHT_BLUE)
    canvas.hline(4, 9, 8, BLUE)
    canvas.hline(4, 10, 10, LIGHT_BLUE)
    canvas.hline(4, 9, 12, BLUE)
    canvas.hline(3, 10, 15, DARK_BLUE)
    canvas.pixel(11, 6, PALE_YELLOW)
    return canvas


def folder_icon() -> Canvas:
    canvas = Canvas()
    canvas.rect(2, 2, 8, 4, INK)
    canvas.rect(3, 3, 7, 4, PALE_YELLOW)
    canvas.rect(1, 4, 16, 15, INK)
    canvas.rect(2, 5, 15, 14, YELLOW)
    canvas.hline(3, 14, 5, WHITE)
    canvas.vline(2, 6, 13, PALE_YELLOW)
    canvas.hline(2, 15, 14, DARK_YELLOW)
    canvas.hline(3, 14, 15, INK)
    return canvas


def folder_up_icon() -> Canvas:
    canvas = folder_icon()
    # Blue upward arrow drawn last, with a one-pixel black silhouette.
    canvas.rect(7, 6, 10, 14, INK)
    canvas.hline(5, 12, 8, INK)
    canvas.hline(6, 11, 7, INK)
    canvas.hline(7, 10, 6, INK)
    canvas.rect(8, 7, 9, 13, BLUE)
    canvas.hline(6, 11, 8, BLUE)
    canvas.hline(7, 10, 7, LIGHT_BLUE)
    canvas.hline(8, 9, 6, LIGHT_BLUE)
    canvas.hline(8, 9, 14, DARK_BLUE)
    return canvas


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "src/ui/images")
    output.mkdir(parents=True, exist_ok=True)
    icons = {
        "action-mac8-full-copy.png": copy_icon(),
        "action-mac8-full-folder.png": folder_icon(),
        "action-mac8-full-folder-up.png": folder_up_icon(),
    }
    for filename, canvas in icons.items():
        write_png(output / filename, canvas)


if __name__ == "__main__":
    main()
