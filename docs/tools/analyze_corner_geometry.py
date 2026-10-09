#!/usr/bin/env python3
"""Measure corner-marker position and inferred image bounds in packed YUY2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from generate_corner_geometry_chart import MARKER_IDS, marker_bits


SCALES = (0.5, 0.65, 0.75, 0.85, 0.925, 1.0, 1.075, 1.15,
          1.25, 1.4, 1.5, 1.75, 2.0, 2.5)


def find_marker(frame: np.ndarray, marker_id: int, expected_xy: tuple[int, int],
                base_cell: int, threshold: int = 128, margin: int = 96) -> dict:
    height, width = frame.shape
    bits = np.asarray(marker_bits(marker_id), dtype=bool)
    expected_x, expected_y = expected_xy
    best = None
    for scale_x in SCALES:
        cell_x = max(2, round(base_cell * scale_x))
        marker_width = 8 * cell_x
        for scale_y in SCALES:
            cell_y = max(2, round(base_cell * scale_y))
            marker_height = 8 * cell_y
            if marker_width > width or marker_height > height:
                continue
            x0 = max(0, expected_x - margin)
            x1 = min(width - marker_width, expected_x + margin)
            y0 = max(0, expected_y - margin)
            y1 = min(height - marker_height, expected_y + margin)
            if x0 > x1 or y0 > y1:
                continue
            xs = np.arange(x0, x1 + 1, 2, dtype=np.int32)
            ys = np.arange(y0, y1 + 1, 2, dtype=np.int32)
            if not xs.size or not ys.size:
                continue
            scores = np.zeros((len(ys), len(xs)), dtype=np.uint8)
            x_offsets = np.arange(8, dtype=np.int32) * cell_x + cell_x // 2
            y_offsets = np.arange(8, dtype=np.int32) * cell_y + cell_y // 2
            for row in range(8):
                sample_y = ys + y_offsets[row]
                for col in range(8):
                    observed = frame[sample_y[:, None], xs[None, :] + x_offsets[col]] >= threshold
                    scores += np.not_equal(observed, bits[row, col])
            index = int(np.argmin(scores))
            iy, ix = np.unravel_index(index, scores.shape)
            candidate = {
                "top_left_xy": [int(xs[ix]), int(ys[iy])],
                "center_xy": [float(xs[ix] + marker_width / 2),
                              float(ys[iy] + marker_height / 2)],
                "cell_pixels": [cell_x, cell_y],
                "horizontal_scale": round(cell_x / base_cell, 4),
                "vertical_scale": round(cell_y / base_cell, 4),
                "mismatched_cells": int(scores[iy, ix]),
            }
            rank = (candidate["mismatched_cells"],
                    abs(candidate["horizontal_scale"] - 1.0) +
                    abs(candidate["vertical_scale"] - 1.0))
            if best is None or rank < best[0]:
                best = (rank, candidate)
    if best is None:
        return {"found": False, "reason": "no marker-sized search window fits capture"}
    record = best[1]
    # Cell-center matching gives a fast coarse location but cannot distinguish
    # shifts inside a module. Refine around that location with cell corners.
    cell_x, cell_y = record["cell_pixels"]
    coarse_x, coarse_y = record["top_left_xy"]
    refine = []
    radius_x, radius_y = max(1, cell_x // 2 + 1), max(1, cell_y // 2 + 1)
    sample_points = ((0, 0), (0, cell_x - 1), (cell_y - 1, 0),
                     (cell_y - 1, cell_x - 1), (cell_y // 2, cell_x // 2))
    for y in range(max(0, coarse_y - radius_y),
                   min(height - 8 * cell_y, coarse_y + radius_y) + 1):
        for x in range(max(0, coarse_x - radius_x),
                       min(width - 8 * cell_x, coarse_x + radius_x) + 1):
            errors = 0
            for row in range(8):
                for col in range(8):
                    expected = bits[row, col]
                    for dy, dx in sample_points:
                        observed = frame[y + row * cell_y + dy,
                                         x + col * cell_x + dx] >= threshold
                        errors += observed != expected
            refine.append((errors, abs(x - expected_x) + abs(y - expected_y), x, y))
    if refine:
        errors, _, refined_x, refined_y = min(refine)
        marker_width, marker_height = 8 * cell_x, 8 * cell_y
        record["top_left_xy"] = [int(refined_x), int(refined_y)]
        record["center_xy"] = [float(refined_x + marker_width / 2),
                               float(refined_y + marker_height / 2)]
        record["mismatched_samples"] = int(errors)
    record["found"] = record["mismatched_cells"] <= 10
    if not record["found"]:
        record["reason"] = "best marker match has more than 10 mismatched cells"
    return record


def analyze_luma(frame: np.ndarray, manifest: dict) -> dict:
    height, width = frame.shape
    source_width, source_height = int(manifest["width"]), int(manifest["height"])
    marker_results = {}
    for corner, marker_id in MARKER_IDS.items():
        spec = manifest["markers"][corner]
        marker_results[corner] = find_marker(
            frame, marker_id, tuple(spec["top_left_xy"]), int(spec["cell_pixels"]))

    found = all(item.get("found") for item in marker_results.values())
    found_corners = [corner for corner, item in marker_results.items()
                     if item.get("found")]
    result = {
        "capture_size": [width, height],
        "chart_size": [source_width, source_height],
        "markers": marker_results,
        "all_corner_markers_found": found,
        "found_corner_markers": found_corners,
        "viewport_fit": None,
    }
    if not found_corners:
        return result

    x_scale = float(np.mean([marker_results[corner]["horizontal_scale"]
                             for corner in found_corners]))
    y_scale = float(np.mean([marker_results[corner]["vertical_scale"]
                             for corner in found_corners]))
    source_tl = np.asarray([manifest["markers"][corner]["top_left_xy"]
                            for corner in found_corners], dtype=np.float64)
    measured_tl = np.asarray([marker_results[corner]["top_left_xy"]
                              for corner in found_corners], dtype=np.float64)
    x_offset = float(np.mean(measured_tl[:, 0] - x_scale * source_tl[:, 0]))
    y_offset = float(np.mean(measured_tl[:, 1] - y_scale * source_tl[:, 1]))
    source_x = np.asarray([manifest["markers"][corner]["center_xy"][0]
                           for corner in found_corners], dtype=np.float64)
    source_y = np.asarray([manifest["markers"][corner]["center_xy"][1]
                           for corner in found_corners], dtype=np.float64)
    measured_x = np.asarray([marker_results[corner]["center_xy"][0]
                             for corner in found_corners], dtype=np.float64)
    measured_y = np.asarray([marker_results[corner]["center_xy"][1]
                             for corner in found_corners], dtype=np.float64)
    residual = np.sqrt(np.mean((measured_x - (x_scale * source_x + x_offset)) ** 2 +
                               (measured_y - (y_scale * source_y + y_offset)) ** 2))
    predicted = {
        "left": float(x_offset),
        "right": float(x_scale * (source_width - 1) + x_offset),
        "top": float(y_offset),
        "bottom": float(y_scale * (source_height - 1) + y_offset),
    }
    overflows = {
        "left_px": max(0.0, -predicted["left"]),
        "right_px": max(0.0, predicted["right"] - (width - 1)),
        "top_px": max(0.0, -predicted["top"]),
        "bottom_px": max(0.0, predicted["bottom"] - (height - 1)),
    }
    result["viewport_fit"] = {
        "horizontal_scale": round(float(x_scale), 6),
        "horizontal_offset_px": round(float(x_offset), 3),
        "vertical_scale": round(float(y_scale), 6),
        "vertical_offset_px": round(float(y_offset), 3),
        "predicted_image_edges_px": {key: round(value, 3) for key, value in predicted.items()},
        "overflow_px": {key: round(value, 3) for key, value in overflows.items()},
        "fit_residual_px_rms": round(float(residual), 4),
        "fit_basis_corner_count": len(found_corners),
        "within_viewport": bool(found and max(overflows.values()) <= 2.0 and residual <= 2.0),
    }
    return result


def read_yuy2(path: Path, width: int, height: int, frame_index: int) -> np.ndarray:
    frame_bytes = width * height * 2
    raw = path.read_bytes()
    if len(raw) % frame_bytes:
        raise ValueError("YUY2 file size is not a whole number of frames")
    count = len(raw) // frame_bytes
    if not 0 <= frame_index < count:
        raise ValueError(f"Frame index {frame_index} is outside 0..{count - 1}")
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(count, height, width, 2)
    return packed[frame_index, :, :, 0].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="packed YUY2 rawvideo capture")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest_root = json.loads(args.manifest.read_text())
    key = f"{args.width}x{args.height}"
    manifest = manifest_root[key] if key in manifest_root else manifest_root
    result = analyze_luma(read_yuy2(args.capture, args.width, args.height, args.frame), manifest)
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
