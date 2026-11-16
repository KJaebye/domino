#!/usr/bin/env python3
"""Render the existing pixel wordmark as a looping domino chain (Pillow only).

Usage: .venv/bin/python scripts/render_logo.py
This is a documentation asset generator; it never reads a Domino installation.
"""
from __future__ import annotations

import argparse
import ast
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = (640, 188)
BACKGROUND = (255, 255, 255)
INK = (123, 201, 204)
SIDE = (87, 157, 163)
SHADOW = (223, 232, 233)
PIXEL = 16
BASE = 134
FPS = 25
CYCLE = 5.2
BOUNDS = ((0, 3), (4, 7), (8, 13), (14, 15), (16, 20), (21, 24))


def glyphs():
    # Parse the literal rather than importing application code or probing runtime.
    tree = ast.parse((ROOT / 'domino_tui.py').read_text())
    lines = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id == 'LOGO_LINES' for target in node.targets))
    assert all(len(line) == 24 for line in lines)
    result = []
    for left, right in BOUNDS:
        cells = []
        for row, line in enumerate(lines):
            for column, char in enumerate(line[left:right]):
                if char in '█▀': cells.append((column, row * 2))
                if char in '█▄': cells.append((column, row * 2 + 1))
        result.append((left, right, cells))
    return result


def ease(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def angle(time, index):
    start = 1.0 + index * .16
    if time < start: return 0.0
    if time < start + .62:
        progress = (time - start) / .62
        return math.pi / 2 * progress ** 1.6
    reset = 3.15 + (5 - index) * .055
    if time < reset: return math.pi / 2
    return math.pi / 2 * (1 - ease((time - reset) / .55))


def frame(time, letters):
    scale = 2
    canvas = Image.new('RGB', (SIZE[0] * scale, SIZE[1] * scale), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    origin = (SIZE[0] - 24 * PIXEL) / 2
    # Back-to-front painter order keeps the chain readable where letters overlap.
    for index in reversed(range(len(letters))):
        left, right, cells = letters[index]
        theta = angle(time, index)
        cosine, sine = math.cos(theta), math.sin(theta)
        pivot = origin + right * PIXEL

        def point(x, y, dx=0, dy=0):
            return ((pivot + x * cosine - y * sine + dx) * scale,
                    (BASE + x * sine + y * cosine + dy) * scale)

        for dx, dy, color in ((PIXEL * 5 / 24, PIXEL * 7 / 24, SHADOW), (PIXEL / 8, PIXEL / 8, SIDE), (0, 0, INK)):
            for column, row in cells:
                x = (column - (right - left)) * PIXEL
                y = (row - 5) * PIXEL
                draw.polygon([point(x, y, dx, dy), point(x + PIXEL, y, dx, dy),
                              point(x + PIXEL, y + PIXEL, dx, dy), point(x, y + PIXEL, dx, dy)], fill=color)
    return canvas.resize(SIZE, Image.Resampling.LANCZOS)


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    letters = glyphs()
    still = frame(0, letters)
    still.save(output / 'domino-logo.png', optimize=True)
    frames = [frame(index / FPS, letters) for index in range(round(CYCLE * FPS))]
    # A shared palette avoids color flicker between animation frames.
    samples = [BACKGROUND, INK, SIDE, SHADOW]
    for foreground in (INK, SIDE, SHADOW):
        for index in range(1, 63):
            alpha = index / 63
            samples.append(tuple(round(a * (1-alpha) + b * alpha) for a, b in zip(BACKGROUND, foreground)))
    palette = Image.new('P', (1, 1))
    palette.putpalette([channel for color in (samples + [BACKGROUND] * 256)[:256] for channel in color])
    indexed = []
    background = Image.new('RGB', SIZE, BACKGROUND)
    for item in frames:
        converted = item.quantize(palette=palette, dither=Image.Dither.NONE)
        # Quantizer color caching can otherwise turn pure white into near-white.
        mask = ImageChops.difference(item, background).convert('L').point(lambda value: 255 if value == 0 else 0)
        converted.paste(0, mask=mask)
        indexed.append(converted)
    indexed[0].save(output / 'domino-logo.gif', save_all=True, append_images=indexed[1:],
                    duration=1000 // FPS, loop=0, disposal=1, optimize=True)
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets')
    parser.add_argument('--contact-sheet', type=Path, help='Optional review artifact, outside the README')
    args = parser.parse_args()
    frames = render(args.output)
    if args.contact_sheet:
        times = (0, 1.25, 1.55, 1.9, 2.25, 2.7, 3.5, 4.4)
        sheet = Image.new('RGB', (SIZE[0], SIZE[1] * len(times)), BACKGROUND)
        for row, time in enumerate(times): sheet.paste(frames[round(time * FPS)], (0, row * SIZE[1]))
        args.contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.contact_sheet)
    print(f'Created {args.output / "domino-logo.gif"} and static PNG')


if __name__ == '__main__':
    main()
