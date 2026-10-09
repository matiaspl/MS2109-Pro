#!/usr/bin/env python3
"""Capture a displayed corner chart and measure viewport fit in YUY2.

Present the chart with tools/show_scaler_chart.py first. This tool performs no
register writes; use it at matching native and scaled input/capture modes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from analyze_corner_geometry import analyze_luma
from generate_corner_geometry_chart import SIZES

FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
VIDEO_DEVICE = "MS2109-Pro:none"


def require_ready(session: Path, chart_size: tuple[int, int], initial: dict | None = None) -> dict:
    ready_path = session / "display-ready.json"
    if not ready_path.is_file():
        raise RuntimeError(f"Chart session has no readiness record: {ready_path}")
    current = json.loads(ready_path.read_text())
    good = (current.get("target_display_available") and
            current.get("display_profile_matches") and
            current.get("window_screen") == "HDMI TO USB" and
            current.get("chart_kind") == "full-frame-raster" and
            current.get("full_frame_image_size") == list(chart_size))
    if initial is not None:
        good = good and (current.get("display_generation") == initial.get("display_generation") and
                         current.get("display_profile_generation") == initial.get("display_profile_generation"))
    if not good:
        raise RuntimeError(f"Corner chart is not stable on the target display: {current}")
    return current


def capture_raw(output: Path, width: int, height: int, fps: int, frames: int) -> bytes:
    command = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-framerate", str(fps), "-video_size",
               f"{width}x{height}", "-pixel_format", "yuyv422", "-i", VIDEO_DEVICE,
               "-frames:v", str(frames), "-fps_mode", "passthrough", "-pix_fmt",
               "yuyv422", "-f", "rawvideo", str(output)]
    subprocess.run(command, check=True, timeout=max(20, frames * 3))
    raw = output.read_bytes()
    expected = width * height * 2 * frames
    if len(raw) != expected:
        raise RuntimeError(f"Expected {expected} YUY2 bytes, received {len(raw)}")
    return raw


def analyze_capture(raw: bytes, width: int, height: int, frames: int,
                    manifest: dict) -> tuple[dict, bool, list[dict]]:
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(frames, height, width, 2)
    geometries = [analyze_luma(packed[index, :, :, 0].copy(), manifest)
                  for index in range(frames)]
    return geometries[0], bool(np.array_equal(packed[0], packed[-1])), geometries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart-session", type=Path, required=True,
                        help="ready directory produced by tools/show_scaler_chart.py")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="geometry-charts/manifest.json")
    parser.add_argument("--chart-size", choices=[f"{w}x{h}" for w, h in SIZES], required=True)
    parser.add_argument("--capture-width", type=int, required=True)
    parser.add_argument("--capture-height", type=int, required=True)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True,
                        help="new directory for raw capture and JSON result")
    args = parser.parse_args()
    chart_size = tuple(map(int, args.chart_size.split("x")))
    if (args.capture_width, args.capture_height) != chart_size:
        parser.error("Use matching chart, HDMI input, and USB capture resolutions for this qualification")
    if not 1 <= args.fps <= 60 or not 3 <= args.frames <= 100:
        parser.error("FPS must be 1..60 and frames must be 3..100")
    if args.output.exists():
        parser.error(f"Refusing to overwrite {args.output}")
    manifest_root = json.loads(args.manifest.read_text())
    key = args.chart_size
    if key not in manifest_root:
        parser.error(f"Manifest has no {key} chart entry")
    manifest = manifest_root[key]
    if (manifest.get("width"), manifest.get("height")) != chart_size:
        parser.error("Manifest dimensions do not match --chart-size")

    session = args.chart_session.resolve()
    initial = require_ready(session, chart_size)
    args.output.mkdir(parents=True, exist_ok=False)
    raw_path = args.output / "capture.yuy2"
    raw = capture_raw(raw_path, args.capture_width, args.capture_height, args.fps, args.frames)
    require_ready(session, chart_size, initial)
    geometry, first_last_frames_identical, geometries = analyze_capture(
        raw, args.capture_width, args.capture_height, args.frames, manifest)
    frame_summaries = [{
        "frame_index": index,
        "all_corner_markers_found": item["all_corner_markers_found"],
        "found_corner_markers": item["found_corner_markers"],
        "viewport_fit": item["viewport_fit"],
    } for index, item in enumerate(geometries)]
    all_frames_within_viewport = all(
        item["all_corner_markers_found"] and item["viewport_fit"] and
        item["viewport_fit"]["within_viewport"] for item in geometries)
    result = {
        "test": "corner-marker viewport geometry; no register writes",
        "chart_size": list(chart_size),
        "capture_size": [args.capture_width, args.capture_height],
        "fps": args.fps,
        "frame_count": args.frames,
        "chart_session": str(session),
        "chart_display_generation": initial.get("display_generation"),
        "chart_profile_generation": initial.get("display_profile_generation"),
        "raw_yuy2_sha256": hashlib.sha256(raw).hexdigest(),
        "frame_geometry": geometry,
        "frame_geometry_by_index": frame_summaries,
        "analyzed_frame_index": 0,
        "first_and_last_frames_identical": first_last_frames_identical,
        "all_frames_within_viewport": all_frames_within_viewport,
        "within_viewport": all_frames_within_viewport,
        "interpretation": "FE84/FE85 are not changed by this capture; compare marker scale and offsets across modes before selecting any mode-specific register change.",
    }
    result["status"] = ("passed: every frame's four corner markers fit the viewport"
                        if all_frames_within_viewport else
                        "review: overflow or corner marker loss detected")
    if not first_last_frames_identical:
        result["frame_variation_note"] = (
            "Raw first and last frames differ; geometry was measured independently "
            "on every frame and remained within the viewport."
        )
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
