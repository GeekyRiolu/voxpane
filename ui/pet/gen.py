#!/usr/bin/env python3
"""Generate voxpane's pixel-pet sprites (SVG) from ASCII grids.

Run:  python ui/pet/gen.py   ->  writes ui/eww/pet/<state>.svg

Each grid cell is one pixel; contiguous same-colour cells become one <rect> and
`shape-rendering=crispEdges` keeps it pixelated when eww scales it up. Edit the
grids below (or drop your own PNG/GIF/SVG sprites into ~/.config/voxpane/pet/) to
change the critter.
"""

import shutil
import subprocess
from pathlib import Path

SCALE = 11  # upscale factor for the PNGs (nearest-neighbour -> crisp pixels)

COLORS = {
    "G": "#6fe06f",  # body
    "D": "#2f9e44",  # outline / shadow
    "W": "#ffffff",  # eye white
    "K": "#14241a",  # pupil / mouth
    "Y": "#ffd43b",  # accent (antenna, thought)
    "B": "#4dabf7",  # accent (speaking)
}

# 16 wide x 14 tall. '.' = transparent.
PETS = {
    "idle": [
        "................",
        "................",
        ".....DDDDDD.....",
        "...DDGGGGGGDD...",
        "..DGGGGGGGGGGD..",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGKKGGGGKKGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        "..DGGGGGGGGGGD..",
        "...DDDDDDDDDD...",
        "................",
    ],
    "listening": [
        ".......Y........",
        ".......D........",
        ".....DDDDDD.....",
        "...DDGGGGGGDD...",
        "..DGGGGGGGGGGD..",
        ".DGGWWGGGGWWGGD.",
        ".DGGWKGGGGKWGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        "..DGGGGGGGGGGD..",
        "...DDDDDDDDDD...",
        "................",
    ],
    "thinking": [
        ".............YYY",
        "................",
        ".....DDDDDD.....",
        "...DDGGGGGGDD...",
        "..DGGGGGGGGGGD..",
        ".DGGWKGGGGWKGGD.",
        ".DGGWWGGGGWWGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGGGGGGGGGD.",
        "..DGGGGGGGGGGD..",
        "...DDDDDDDDDD...",
        "................",
    ],
    "speaking": [
        "................",
        "................",
        ".....DDDDDD.....",
        "...DDGGGGGGDD...",
        "..DGGGGGGGGGGD..",
        ".DGGWWGGGGWWGGD.",
        ".DGGWKGGGGKWGGD.",
        ".DGGGGGGGGGGGGD.",
        ".DGGGGKKKKGGGGD.",
        ".DGGGGKKKKGGGGD.",
        ".DGGGGGGGGGGGGD.",
        "..DGGGGGGGGGGD..",
        "...DDDDDDDDDD...",
        "................",
    ],
}


def to_svg(grid: list[str]) -> str:
    width = max(len(row) for row in grid)
    assert all(len(row) == width for row in grid), "all rows must be equal width"
    rects = []
    for y, row in enumerate(grid):
        x = 0
        while x < len(row):
            c = row[x]
            if c in ". ":
                x += 1
                continue
            run = 1
            while x + run < len(row) and row[x + run] == c:
                run += 1
            rects.append(f'  <rect x="{x}" y="{y}" width="{run}" height="1" fill="{COLORS[c]}"/>')
            x += run
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {len(grid)}" '
        f'shape-rendering="crispEdges">\n' + "\n".join(rects) + "\n</svg>\n"
    )


def _render_png(svg: Path, png: Path, w: int, h: int) -> bool:
    """Render a crisp (nearest-neighbour) PNG. Many GTK setups lack the SVG
    pixbuf loader, so eww needs PNGs. Uses rsvg-convert + magick if present."""
    if not (shutil.which("rsvg-convert") and shutil.which("magick")):
        return False
    tiny = png.with_suffix(".tiny.png")
    try:
        subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(h), str(svg), "-o", str(tiny)], check=True)
        subprocess.run(["magick", str(tiny), "-sample", f"{w * SCALE}x{h * SCALE}", str(png)], check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    finally:
        tiny.unlink(missing_ok=True)
    return True


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "eww" / "pet"
    out.mkdir(parents=True, exist_ok=True)
    for name, grid in PETS.items():
        svg = out / f"{name}.svg"
        svg.write_text(to_svg(grid))
        w = max(len(r) for r in grid)
        rendered = _render_png(svg, out / f"{name}.png", w, len(grid))
        print("wrote", svg, "+ png" if rendered else "(no PNG — install rsvg-convert + imagemagick)")


if __name__ == "__main__":
    main()
