#!/usr/bin/env python3
"""Compare the native corner geometry at live FE84 baseline and one RAM value."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from analyze_corner_geometry import analyze_luma
from capture_corner_geometry import FFMPEG, require_ready
from ms2109_hid import Device
from ms2109_register_console import RegisterSession, stable_eeprom_hash


EXPECTED_EEPROM = "b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8"
EXPECTED_REGISTERS = {
    "FE80": 0x01,
    "FE85": 0x00,
    "F9A0": 0x00,
    "FEBA": 0x00,
}
REGISTER_NAMES = ("FE80", "FE84", "FE85", "F9A0", "F92C", "FEBA")
WIDTH, HEIGHT, FPS, FRAMES = 1920, 1080, 10, 8
VIDEO_DEVICE = "MS2109-Pro:none"


def capture_raw(path: Path) -> bytes:
    command = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-framerate", str(FPS), "-video_size",
               f"{WIDTH}x{HEIGHT}", "-pixel_format", "yuyv422", "-i", VIDEO_DEVICE,
               "-frames:v", str(FRAMES), "-fps_mode", "passthrough", "-pix_fmt",
               "yuyv422", "-f", "rawvideo", str(path)]
    subprocess.run(command, check=True, timeout=30)
    raw = path.read_bytes()
    expected = WIDTH * HEIGHT * 2 * FRAMES
    if len(raw) != expected:
        raise RuntimeError(f"Expected {expected} YUY2 bytes, received {len(raw)}")
    return raw


def analyze(raw: bytes, manifest: dict) -> tuple[dict, bool]:
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(FRAMES, HEIGHT, WIDTH, 2)
    geometry = analyze_luma(packed[0, :, :, 0].copy(), manifest)
    return geometry, bool(np.array_equal(packed[0], packed[-1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart-session", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-fe84", type=lambda value: int(value, 16),
                        default=0x40, help="candidate FE84 value in hex (default 40)")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite {args.output}")
    if not 0 <= args.candidate_fe84 <= 0xFF:
        parser.error("Candidate FE84 must be one byte")

    manifest_root = json.loads(args.manifest.read_text())
    manifest = manifest_root.get("1920x1080")
    if manifest is None or (manifest.get("width"), manifest.get("height")) != (WIDTH, HEIGHT):
        parser.error("Manifest must contain the 1920x1080 corner chart")
    session_dir = args.chart_session.resolve()
    chart_state = require_ready(session_dir, (WIDTH, HEIGHT))

    args.output.mkdir(parents=True, exist_ok=False)
    recovery_path = args.output / "register-session.recovery.json"
    result = {
        "test": "native corner geometry before and during a RAM-only FE84 probe",
        "chart_size": [WIDTH, HEIGHT],
        "capture_size": [WIDTH, HEIGHT],
        "frames_per_state": FRAMES,
        "chart_session": str(session_dir),
        "candidate_fe84": f"{args.candidate_fe84:02X}",
        "firmware_written": False,
        "eeprom_writes": 0,
    }
    device = None
    register_session = None
    write_attempted = False
    error = None
    try:
        device = Device()
        size = device.identify_eeprom()
        if size != 2048:
            raise RuntimeError(f"Expected 2 KiB EEPROM, found {size}")
        eeprom_before = stable_eeprom_hash(device)
        result["eeprom_sha256_before"] = eeprom_before
        if eeprom_before != EXPECTED_EEPROM:
            raise RuntimeError("EEPROM does not match the pinned live baseline; refusing RAM probe")
        before = {name: device.read("ram", int(name, 16), 1)[0]
                  for name in REGISTER_NAMES}
        result["registers_before"] = {name: f"{value:02X}" for name, value in before.items()}
        mismatches = {name: f"{before[name]:02X}" for name, value in EXPECTED_REGISTERS.items()
                      if before[name] != value}
        if mismatches or before["F92C"] not in (0x20, 0x30):
            raise RuntimeError(f"Unexpected guarded live registers; refusing RAM probe: {mismatches}")
        if before["FE84"] == args.candidate_fe84:
            raise RuntimeError("Candidate FE84 equals the live value; refusing a no-op probe")

        baseline_path = args.output / f"baseline-{before['FE84']:02X}.yuy2"
        require_ready(session_dir, (WIDTH, HEIGHT), chart_state)
        baseline_raw = capture_raw(baseline_path)
        baseline_geometry, baseline_stable = analyze(baseline_raw, manifest)
        result["baseline_capture_sha256"] = hashlib.sha256(baseline_raw).hexdigest()
        result["baseline_geometry"] = baseline_geometry
        result["baseline_first_last_frames_identical"] = baseline_stable

        register_session = RegisterSession(device, eeprom_before, recovery_path)
        write_attempted = True
        returned = register_session.write(0xFE84, bytes((args.candidate_fe84,)))
        result["candidate_readback"] = returned.hex().upper()
        time.sleep(1)
        candidate_path = args.output / f"candidate-{args.candidate_fe84:02X}.yuy2"
        require_ready(session_dir, (WIDTH, HEIGHT), chart_state)
        candidate_raw = capture_raw(candidate_path)
        candidate_geometry, candidate_stable = analyze(candidate_raw, manifest)
        result["candidate_capture_sha256"] = hashlib.sha256(candidate_raw).hexdigest()
        result["candidate_geometry"] = candidate_geometry
        result["candidate_first_last_frames_identical"] = candidate_stable
        result["candidate_within_viewport"] = bool(
            candidate_geometry.get("viewport_fit", {}).get("within_viewport"))
        result["interpretation"] = (
            "This comparison measures native 1920x1080 corner geometry only. It does not identify "
            "FE84's internal function or qualify the candidate for scaled modes."
        )
    except Exception as exc:  # retain the failure and still run recovery below
        error = f"{type(exc).__name__}: {exc}"
        result["error"] = error
    finally:
        if device is not None and register_session is not None and write_attempted:
            try:
                register_session.restore_addresses(set(register_session.original))
                result["ram_restore_verified"] = register_session.state == "restored"
                result["fe84_after_restore"] = device.read("ram", 0xFE84, 1).hex().upper()
            except Exception as exc:
                result["ram_restore_error"] = f"{type(exc).__name__}: {exc}"
            try:
                result["eeprom_sha256_after"] = stable_eeprom_hash(device)
                result["eeprom_unchanged"] = result["eeprom_sha256_after"] == result.get("eeprom_sha256_before")
            except Exception as exc:
                result["eeprom_after_error"] = f"{type(exc).__name__}: {exc}"
        if device is not None:
            device.close()
        result["status"] = (
            "passed: candidate keeps the full chart within the viewport"
            if not error and result.get("candidate_within_viewport") and
            result.get("ram_restore_verified") and result.get("eeprom_unchanged")
            else "probe completed; review geometry and restoration fields"
            if not error else "failed; see error and restoration fields"
        )
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    print(json.dumps(result, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
