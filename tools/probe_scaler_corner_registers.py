#!/usr/bin/env python3
"""Compare FE80-FE8F candidate states with a live corner-marker chart."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from analyze_corner_geometry import analyze_luma
from ms2109_hid import Device
from ms2109_register_console import RegisterSession, stable_eeprom_hash
from probe_scaler_register_block import (
    BASELINE_EEPROM, BLOCK_LENGTH, BLOCK_START, LiveCapture, stable_block,
)


CHART_SIZE = (1920, 1080)


def analyze_frames(frames: list[bytes], width: int, height: int, manifest: dict) -> list[dict]:
    output = []
    for raw in frames:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 2)
        output.append(analyze_luma(packed[..., 0].copy(), manifest))
    return output


def scale_manifest(manifest: dict, width: int, height: int) -> dict:
    scaled = deepcopy(manifest)
    sx, sy = width / manifest["width"], height / manifest["height"]
    scaled["width"], scaled["height"] = width, height
    for marker in scaled["markers"].values():
        marker["top_left_xy"] = [round(marker["top_left_xy"][0] * sx),
                                 round(marker["top_left_xy"][1] * sy)]
        marker["center_xy"] = [marker["center_xy"][0] * sx,
                               marker["center_xy"][1] * sy]
        marker["cell_pixels"] = max(2, round(marker["cell_pixels"] * sx))
        marker["marker_pixels"] = marker["cell_pixels"] * 8
    return scaled


def summarize_geometry(frames: list[dict]) -> dict:
    fits = [frame.get("viewport_fit") for frame in frames]
    positions = {}
    for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
        values = [frame["markers"][corner]["top_left_xy"]
                  for frame in frames if frame["markers"][corner].get("found")]
        positions[corner] = values
    return {
        "frame_count": len(frames),
        "all_frames_have_four_markers": all(frame.get("all_corner_markers_found") for frame in frames),
        "all_frames_within_viewport": all(
            fit is not None and fit.get("within_viewport") for fit in fits),
        "per_frame_viewport_fit": fits,
        "marker_top_left_xy_by_corner": positions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "scaled"), default="native",
                        help="native captures 1920x1080; scaled captures 1280x720 from the same 1080p input")
    parser.add_argument("--chart-session", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-eeprom-sha256", default=BASELINE_EEPROM)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--frames", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite output directory: {args.output}")
    if not (1 <= args.fps <= 60 and 1 <= args.frames <= 20):
        parser.error("FPS and frame count are out of range")

    session_dir = args.chart_session.resolve()
    ready_path = session_dir / "display-ready.json"
    source_path = session_dir / "source-render.png"
    if not ready_path.is_file() or not source_path.is_file():
        parser.error("Chart session is missing its readiness record or source render")
    initial_display = json.loads(ready_path.read_text())
    if not (initial_display.get("target_display_available") and
            initial_display.get("display_profile_matches") and
            initial_display.get("window_screen") == "HDMI TO USB" and
            initial_display.get("chart_kind") == "full-frame-raster" and
            initial_display.get("full_frame_image_size") == list(CHART_SIZE)):
        parser.error("A verified 1920x1080 corner chart must be active on HDMI TO USB")
    manifest = json.loads(args.manifest.read_text())["1920x1080"]
    if [manifest.get("width"), manifest.get("height")] != list(CHART_SIZE):
        parser.error("Manifest does not describe a 1920x1080 chart")
    width, height = CHART_SIZE if args.mode == "native" else (1280, 720)
    analysis_manifest = scale_manifest(manifest, width, height)

    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        "test": "RAM-only corner-marker geometry probe of FE80-FE8F candidates",
        "input_chart_size": list(CHART_SIZE),
        "capture_size": [width, height],
        "mode": args.mode,
        "frames_per_state": args.frames,
        "chart_session": str(session_dir),
        "display_generation": initial_display.get("display_generation"),
        "firmware_written": False,
        "eeprom_writes": 0,
        "candidates": [],
        "status": "running",
    }
    device = None
    capture = None
    register_session = None
    eeprom_before = None
    baseline = None
    error = None

    def save_result() -> None:
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    try:
        device = Device()
        eeprom_before = stable_eeprom_hash(device)
        result["eeprom_sha256_before"] = eeprom_before
        if eeprom_before != args.expected_eeprom_sha256.lower():
            raise RuntimeError(f"EEPROM fingerprint mismatch: {eeprom_before}")
        result["register_block_before_stream_start"] = stable_block(device).hex(" ").upper()

        capture = LiveCapture(width, height, args.fps, args.output / "ffmpeg.log")
        capture.read_frames(6)
        current_display = json.loads(ready_path.read_text())
        if (current_display.get("display_generation") != initial_display.get("display_generation") or
                current_display.get("display_profile_generation") != initial_display.get("display_profile_generation")):
            raise RuntimeError("HDMI chart or display profile changed while opening capture")

        baseline = stable_block(device)
        result["register_block_after_stream_start"] = baseline.hex(" ").upper()
        register_session = RegisterSession(device, eeprom_before,
                                           args.output / "register-session.recovery.json")
        baseline_frames = capture.read_frames(args.frames)
        (args.output / "baseline.yuy2").write_bytes(b"".join(baseline_frames))
        baseline_geometry = analyze_frames(baseline_frames, width, height, analysis_manifest)
        result["baseline_geometry"] = summarize_geometry(baseline_geometry)
        save_result()

        candidates = (
            ("FE80=00", 0xFE80, 0x00),
            ("FE84=40", 0xFE84, 0x40),
            ("FE85=02", 0xFE85, 0x02),
            ("FE8E=01", 0xFE8E, 0x01),
            ("FE8E=10", 0xFE8E, 0x10),
            ("FE8F=01", 0xFE8F, 0x01),
        )
        for index, (label, address, value) in enumerate(candidates):
            old = baseline[address - BLOCK_START]
            item = {"label": label, "address": f"{address:04X}",
                    "before": f"{old:02X}", "candidate": f"{value:02X}"}
            if old == value:
                item["status"] = "skipped: candidate equals mode baseline"
                result["candidates"].append(item)
                save_result()
                continue
            if stable_block(device) != baseline:
                raise RuntimeError(f"FE80-FE8F drifted before {label}")
            item["readback"] = register_session.write(address, bytes((value,))).hex().upper()
            capture.read_frames(3)
            frames = capture.read_frames(args.frames)
            after = stable_block(device)
            item["register_block_during_capture"] = after.hex(" ").upper()
            if after[address - BLOCK_START] != value:
                raise RuntimeError(f"{label} did not hold during capture")
            raw_path = args.output / f"candidate-{index:02d}-{label.replace('=', '-')}.yuy2"
            raw_path.write_bytes(b"".join(frames))
            geometry = analyze_frames(frames, width, height, analysis_manifest)
            item["capture"] = raw_path.name
            item["geometry"] = summarize_geometry(geometry)
            item["geometry_delta_vs_baseline"] = []
            for base_frame, candidate_frame in zip(baseline_geometry, geometry):
                base_fit = base_frame.get("viewport_fit") or {}
                candidate_fit = candidate_frame.get("viewport_fit") or {}
                item["geometry_delta_vs_baseline"].append({
                    key: round(candidate_fit[key] - base_fit[key], 3)
                    for key in ("horizontal_scale", "horizontal_offset_px",
                                "vertical_scale", "vertical_offset_px")
                    if key in candidate_fit and key in base_fit
                })

            mismatch = {BLOCK_START + offset for offset, (before, now) in
                        enumerate(zip(baseline, after)) if before != now}
            register_session.restore_addresses(mismatch)
            restored = stable_block(device)
            if restored != baseline:
                mismatch = {BLOCK_START + offset for offset, (before, now) in
                            enumerate(zip(baseline, restored)) if before != now}
                for other_address in mismatch:
                    register_session.original.setdefault(
                        other_address, baseline[other_address - BLOCK_START])
                    register_session.latest[other_address] = restored[other_address - BLOCK_START]
                register_session._save_journal()
                register_session.restore_addresses(mismatch)
                restored = stable_block(device)
            if restored != baseline:
                raise RuntimeError(f"FE80-FE8F did not restore after {label}")
            item["restored_block"] = restored.hex(" ").upper()
            item["status"] = "captured and restored"
            result["candidates"].append(item)
            save_result()

        capture.read_frames(3)
        restored_frames = capture.read_frames(args.frames)
        (args.output / "restored-final.yuy2").write_bytes(b"".join(restored_frames))
        result["restored_final_geometry"] = summarize_geometry(
            analyze_frames(restored_frames, width, height, analysis_manifest))
        if stable_block(device) != baseline:
            raise RuntimeError("Final FE80-FE8F block differs from stream-start baseline")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result["error"] = error
    finally:
        if device is not None and register_session is not None and register_session.original:
            try:
                current = device.read("ram", BLOCK_START, BLOCK_LENGTH)
                changed = {address for address, value in register_session.original.items()
                           if current[address - BLOCK_START] != value}
                if changed:
                    register_session.restore_addresses(changed)
                else:
                    register_session.state = "restored"
                    register_session._save_journal()
                result["ram_restore_verified_live"] = stable_block(device) == baseline
            except Exception as exc:
                result["ram_restore_error"] = f"{type(exc).__name__}: {exc}"
        if capture is not None:
            capture.close()
            capture = None
        if device is not None and eeprom_before is not None:
            try:
                result["register_block_after_stream_closed"] = stable_block(device).hex(" ").upper()
                result["eeprom_sha256_after"] = stable_eeprom_hash(device)
                result["eeprom_unchanged"] = result["eeprom_sha256_after"] == eeprom_before
            except Exception as exc:
                result["verification_error"] = f"{type(exc).__name__}: {exc}"
            device.close()
        result["recovery_journal"] = str(args.output / "register-session.recovery.json")
        result["status"] = (
            "completed: geometry captured; RAM block restored and EEPROM unchanged"
            if not error and result.get("ram_restore_verified_live") and result.get("eeprom_unchanged")
            else "failed or incomplete; inspect readback and recovery journal"
        )
        save_result()
    print(json.dumps(result, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
