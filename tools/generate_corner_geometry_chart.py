#!/usr/bin/env python3
"""Generate 1:1 MS2109 geometry charts with uniquely coded corner fiducials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
MARKER_IDS = {"top_left": 0b0011, "top_right": 0b1100,
              "bottom_left": 0b0101, "bottom_right": 0b1010}
SIZES = ((1920, 1080), (1280, 720))


def marker_bits(marker_id: int) -> list[list[int]]:
    grid = [[0] * 8 for _ in range(8)]
    for i in range(8):
        grid[0][i] = grid[7][i] = grid[i][0] = grid[i][7] = 0
    # Orientation cells plus a four-bit corner ID in the inner 6x6 field.
    grid[1][1], grid[1][6], grid[6][1], grid[6][6] = 1, 0, 0, 1
    for index, (row, col) in enumerate(((2, 2), (2, 5), (5, 2), (5, 5))):
        grid[row][col] = (marker_id >> (3 - index)) & 1
    # Interior light cells make the code easy to distinguish from its black border.
    for row in range(2, 6):
        for col in range(2, 6):
            if (row, col) not in ((2, 2), (2, 5), (5, 2), (5, 5)):
                grid[row][col] = 1
    return grid


def make_chart(width: int, height: int) -> tuple[Image.Image, dict]:
    if width < 640 or height < 360 or width * 9 != height * 16:
        raise ValueError("Chart size must be 16:9 and at least 640x360")
    scale = width / 1920
    cell = max(4, round(12 * scale))
    margin = max(4, round(12 * scale))
    marker_size = cell * 8
    image = Image.new("RGB", (width, height), (128, 128, 128))
    draw = ImageDraw.Draw(image)
    edge = max(2, round(4 * scale))
    draw.rectangle((edge, edge, width - 1 - edge, height - 1 - edge),
                   outline=(235, 235, 235), width=max(1, round(2 * scale)))
    draw.line((width // 2, 0, width // 2, height - 1), fill=(96, 96, 96), width=1)
    draw.line((0, height // 2, width - 1, height // 2), fill=(96, 96, 96), width=1)
    positions = {
        "top_left": (margin, margin),
        "top_right": (width - margin - marker_size, margin),
        "bottom_left": (margin, height - margin - marker_size),
        "bottom_right": (width - margin - marker_size, height - margin - marker_size),
    }
    metadata = {}
    for corner, (x0, y0) in positions.items():
        bits = marker_bits(MARKER_IDS[corner])
        for row in range(8):
            for col in range(8):
                level = 235 if bits[row][col] else 16
                x, y = x0 + col * cell, y0 + row * cell
                draw.rectangle((x, y, x + cell - 1, y + cell - 1),
                               fill=(level, level, level))
        metadata[corner] = {
            "id": MARKER_IDS[corner],
            "top_left_xy": [x0, y0],
            "center_xy": [x0 + marker_size / 2, y0 + marker_size / 2],
            "cell_pixels": cell,
            "marker_pixels": marker_size,
        }
    return image, {"width": width, "height": height,
                   "marker_ids": MARKER_IDS, "markers": metadata}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "artifacts/ms2109-repair/20261007/geometry-charts")
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"Refusing to overwrite non-empty directory {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = {}
    for width, height in SIZES:
        image, record = make_chart(width, height)
        name = f"corner-geometry-{width}x{height}"
        path = args.output_dir / f"{name}.png"
        image.save(path, format="PNG", optimize=False)
        record["image"] = path.name
        records[f"{width}x{height}"] = record
    manifest = args.output_dir / "manifest.json"
    manifest.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"output_dir": str(args.output_dir), "manifest": str(manifest),
                      "charts": list(records)}, indent=2))


if __name__ == "__main__":
    main()
