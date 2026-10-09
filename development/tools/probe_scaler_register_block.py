#!/usr/bin/env python3
"""Probe FE80-FE8F one field at a time during a live chart capture.

The input chart stays on the HDMI target while FFmpeg holds one output mode
open. Each RAM candidate is written through HID, read back, captured, then
restored before the next candidate. EEPROM is only read and hashed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import time

import numpy as np
from PIL import Image

from ms2109_hid import Device
from ms2109_register_console import RegisterSession, stable_eeprom_hash


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
VIDEO_DEVICE = "MS2109-Pro:none"
BLOCK_START = 0xFE80
BLOCK_LENGTH = 16
BASELINE_EEPROM = "2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5"
CHART_SIZE = (1920, 1080)


def stable_block(device: Device) -> bytes:
    first = device.read("ram", BLOCK_START, BLOCK_LENGTH)
    second = device.read("ram", BLOCK_START, BLOCK_LENGTH)
    if first != second:
        raise RuntimeError(f"FE80-FE8F changed between reads: {first.hex()} / {second.hex()}")
    return first


class LiveCapture:
    def __init__(self, width: int, height: int, fps: int, log_path: Path):
        self.width, self.height = width, height
        self.frame_bytes = width * height * 2
        self._log = log_path.open("wb")
        command = [
            FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "avfoundation", "-framerate", str(fps), "-video_size",
            f"{width}x{height}", "-pixel_format", "yuyv422", "-i", VIDEO_DEVICE,
            "-fps_mode", "passthrough", "-pix_fmt", "yuyv422", "-f", "rawvideo", "pipe:1",
        ]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                        stderr=self._log, bufsize=0)
        if self.process.stdout is None:
            raise RuntimeError("FFmpeg did not provide a raw capture stream")
        self.fd = self.process.stdout.fileno()

    def read_frame(self, timeout: float = 15.0) -> bytes:
        data = bytearray()
        deadline = time.monotonic() + timeout
        while len(data) < self.frame_bytes:
            if self.process.poll() is not None:
                raise RuntimeError(f"FFmpeg stopped with exit code {self.process.returncode}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out after receiving {len(data)} of {self.frame_bytes} frame bytes")
            readable, _, _ = select.select([self.fd], [], [], remaining)
            if not readable:
                continue
            chunk = os.read(self.fd, min(1 << 20, self.frame_bytes - len(data)))
            if not chunk:
                raise RuntimeError("FFmpeg raw capture stream closed")
            data.extend(chunk)
        return bytes(data)

    def read_frames(self, count: int) -> list[bytes]:
        return [self.read_frame() for _ in range(count)]

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process.stdout is not None:
            self.process.stdout.close()
        self._log.close()


def y_frames(raw_frames: list[bytes], width: int, height: int) -> np.ndarray:
    packed = np.stack([
        np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 2)[..., 0]
        for frame in raw_frames
    ])
    return packed.astype(np.float32)


def spatial_response(y: np.ndarray, width: int, height: int) -> dict:
    """Measure B1/B2 line pairs and flat fields in chart source coordinates."""
    sx, sy = width / CHART_SIZE[0], height / CHART_SIZE[1]
    image = y.mean(axis=0)
    periods = (32, 16, 8, 4, 2)
    b1, b2 = [], []
    for index, period in enumerate(periods):
        x = 1040 + index * 158
        x0, x1 = int(np.ceil((x + 8) * sx)), int(np.floor((x + 132) * sx))
        y0, y1 = int(np.ceil(228 * sy)), int(np.floor(392 * sy))
        roi = image[y0:y1, x0:x1]
        source_x = (np.arange(x0, x1) + 0.5) / sx
        mask = (((source_x - x) // max(1, period // 2)) % 2) == 0
        bright = float(roi[:, mask].mean())
        dark = float(roi[:, ~mask].mean())
        b1.append({"period_source_px": period, "bright_y": round(bright, 4),
                   "dark_y": round(dark, 4),
                   "michelson_contrast": round((bright - dark) / (bright + dark), 6)})

        y0, y1 = int(np.ceil(466 * sy)), int(np.floor(546 * sy))
        roi = image[y0:y1, x0:x1]
        source_y = (np.arange(y0, y1) + 0.5) / sy
        mask = (((source_y - 458) // max(1, period // 2)) % 2) == 0
        bright = float(roi[mask, :].mean())
        dark = float(roi[~mask, :].mean())
        b2.append({"period_source_px": period, "bright_y": round(bright, 4),
                   "dark_y": round(dark, 4),
                   "michelson_contrast": round((bright - dark) / (bright + dark), 6)})

    flat_fields = {}
    for name, (sx0, sy0, sx1, sy1) in {
        "black": (1100, 1020, 1245, 1048),
        "gray": (1400, 1020, 1545, 1048),
        "white": (1700, 1020, 1845, 1048),
    }.items():
        x0, x1 = int(np.ceil(sx0 * sx)), int(np.floor(sx1 * sx))
        y0, y1 = int(np.ceil(sy0 * sy)), int(np.floor(sy1 * sy))
        block = image[y0:y1, x0:x1]
        flat_fields[name] = {"min_y": round(float(block.min()), 4),
                            "max_y": round(float(block.max()), 4),
                            "mean_y": round(float(block.mean()), 4)}
    return {"B1_vertical_lines_vary_x": b1,
            "B2_horizontal_lines_vary_y": b2,
            "flat_fields": flat_fields}


def frame_metrics(raw_frames: list[bytes], width: int, height: int,
                  source_reference: np.ndarray, baseline_y: np.ndarray | None) -> tuple[np.ndarray, dict]:
    y = y_frames(raw_frames, width, height)
    average = y.mean(axis=0)
    correlations = []
    for frame in y:
        if float(frame.std()) == 0.0 or float(source_reference.std()) == 0.0:
            correlations.append(None)
        else:
            value = float(np.corrcoef(source_reference.ravel(), frame.ravel())[0, 1])
            correlations.append(round(value, 6) if np.isfinite(value) else None)
    metrics = {
        "frame_count": len(raw_frames),
        "source_render_correlation_by_frame": correlations,
        "spatial_response": spatial_response(y, width, height),
    }
    if baseline_y is not None:
        difference = np.abs(average - baseline_y)
        metrics["difference_from_mode_baseline"] = {
            "mean_abs_y": round(float(difference.mean()), 6),
            "p95_abs_y": round(float(np.percentile(difference, 95)), 4),
            "max_abs_y": round(float(difference.max()), 4),
            "pixels_changed_by_at_least_2_codes": int(np.count_nonzero(difference >= 2.0)),
        }
    return average, metrics


def save_frames(path: Path, frames: list[bytes]) -> str:
    raw = b"".join(frames)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def probe_plan(baseline: bytes) -> list[dict]:
    probes = [
        {"label": "FE80.0", "address": 0xFE80, "value": baseline[0] ^ 0x01,
         "basis": "ROM updates bit 0 during mode setup"},
    ]
    for address in (0xFE81, 0xFE82, 0xFE83, 0xFE86, 0xFE87, 0xFE88,
                    0xFE89, 0xFE8A, 0xFE8B, 0xFE8C, 0xFE8D):
        probes.append({"label": f"FE{address & 0xFF:02X}.0", "address": address,
                       "value": baseline[address - BLOCK_START] ^ 0x01,
                       "basis": "ROM audit found no direct access; one-bit exploratory probe"})
    probes.extend([
        {"label": "FE84=40", "address": 0xFE84, "value": 0x40,
         "basis": "previous chart tests found an X-detail response"},
        {"label": "FE85.1", "address": 0xFE85,
         "value": baseline[0xFE85 - BLOCK_START] ^ 0x02,
         "basis": "ROM clears bit 1; previous chart tests found horizontal phase response"},
    ])
    for address in (0xFE8E, 0xFE8F):
        for mask in (0x01, 0x10):
            probes.append({"label": f"FE{address & 0xFF:02X}.{mask.bit_length() - 1}",
                           "address": address,
                           "value": baseline[address - BLOCK_START] ^ mask,
                           "basis": "ROM updates bits 0 and 4 in mode setup"})
    return probes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "scaled"), required=True,
                        help="native is 1920x1080 capture; scaled is 1280x720 capture")
    parser.add_argument("--chart-session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-eeprom-sha256", default=BASELINE_EEPROM)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--settle-frames", type=int, default=3)
    parser.add_argument("--only", nargs="+",
                        help="optional probe labels to run, such as FE80.0 FE81.0 FE84=40")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite output directory: {args.output}")
    if len(args.expected_eeprom_sha256) != 64:
        parser.error("Expected EEPROM SHA-256 must contain 64 hexadecimal characters")
    if not (1 <= args.fps <= 60 and 1 <= args.frames <= 20 and 0 <= args.settle_frames <= 30):
        parser.error("Invalid FPS, frame count, or settling frame count")

    width, height = (1920, 1080) if args.mode == "native" else (1280, 720)
    session_dir = args.chart_session.resolve()
    ready_path = session_dir / "display-ready.json"
    source_path = session_dir / "source-render.png"
    if not ready_path.is_file() or not source_path.is_file():
        parser.error("Chart session must contain display-ready.json and source-render.png")
    initial_display = json.loads(ready_path.read_text())
    if not (initial_display.get("target_display_available") and
            initial_display.get("display_profile_matches") and
            initial_display.get("window_screen") == "HDMI TO USB" and
            initial_display.get("chart_kind") == "full-frame-raster" and
            initial_display.get("full_frame_image_size") == list(CHART_SIZE)):
        parser.error("A verified 1920x1080 chart must be active on HDMI TO USB")

    args.output.mkdir(parents=True, exist_ok=False)
    result_path = args.output / "result.json"
    result = {
        "test": "live RAM-only FE80-FE8F one-field probe with bidirectional scaler chart",
        "mode": args.mode,
        "capture_size": [width, height],
        "input_chart_size": list(CHART_SIZE),
        "fps": args.fps,
        "frames_per_state": args.frames,
        "settle_frames_discarded_after_write": args.settle_frames,
        "chart_session": str(session_dir),
        "display_generation": initial_display.get("display_generation"),
        "firmware_written": False,
        "eeprom_writes": 0,
        "probe_results": [],
        "status": "running",
    }
    device = None
    capture = None
    register_session = None
    eeprom_before = None
    idle_baseline = None
    mode_baseline = None
    block_drift = []
    error = None

    def save_result() -> None:
        result_path.write_text(json.dumps(result, indent=2) + "\n")

    try:
        device = Device()
        if device.read("ram", 0xF800, 3) != bytes.fromhex("a7109a"):
            raise RuntimeError("Target identity changed; refusing probe")
        eeprom_before = stable_eeprom_hash(device)
        result["eeprom_sha256_before"] = eeprom_before
        if eeprom_before != args.expected_eeprom_sha256.lower():
            raise RuntimeError(f"EEPROM fingerprint mismatch: {eeprom_before}")
        idle_baseline = stable_block(device)
        result["FE80_FE8F_before_stream_start"] = idle_baseline.hex(" ").upper()

        capture = LiveCapture(width, height, args.fps, args.output / "ffmpeg.log")
        capture.read_frames(max(args.settle_frames, 6))
        current_display = json.loads(ready_path.read_text())
        if (current_display.get("display_generation") != initial_display.get("display_generation") or
                current_display.get("display_profile_generation") != initial_display.get("display_profile_generation") or
                current_display.get("window_screen") != "HDMI TO USB"):
            raise RuntimeError("HDMI chart or display profile changed while opening capture")

        mode_baseline = stable_block(device)
        result["FE80_FE8F_after_stream_start"] = mode_baseline.hex(" ").upper()
        result["stream_start_register_changes"] = [
            {"address": f"{BLOCK_START + offset:04X}", "before": f"{before:02X}", "after": f"{after:02X}"}
            for offset, (before, after) in enumerate(zip(idle_baseline, mode_baseline))
            if before != after
        ]
        register_session = RegisterSession(device, eeprom_before,
                                           args.output / "register-session.recovery.json")
        source = Image.open(source_path).convert("L")
        if source.size != (width, height):
            source = source.resize((width, height), Image.Resampling.LANCZOS)
        source_reference = np.asarray(source, dtype=np.float32)

        baseline_frames = capture.read_frames(args.frames)
        baseline_path = args.output / "baseline.yuy2"
        result["baseline_sha256"] = save_frames(baseline_path, baseline_frames)
        baseline_y, baseline_metrics = frame_metrics(baseline_frames, width, height,
                                                     source_reference, None)
        result["baseline_metrics"] = baseline_metrics
        result["mode_baseline_registers"] = mode_baseline.hex(" ").upper()
        result["probe_results"].append({"state": "baseline", "capture": baseline_path.name,
                                        "metrics": baseline_metrics})
        save_result()

        plan = probe_plan(mode_baseline)
        if args.only:
            available = {probe["label"] for probe in plan}
            unknown = set(args.only) - available
            if unknown:
                raise RuntimeError(f"Unknown probe labels: {sorted(unknown)}")
            plan = [probe for probe in plan if probe["label"] in set(args.only)]
        for index, probe in enumerate(plan):
            address = probe["address"]
            old_value = mode_baseline[address - BLOCK_START]
            value = probe["value"]
            item = {**probe, "index": index, "old_value": f"{old_value:02X}",
                    "candidate_value": f"{value:02X}"}
            if value == old_value:
                item["status"] = "skipped: candidate equals mode baseline"
                result["probe_results"].append(item)
                save_result()
                continue

            current_block = stable_block(device)
            if current_block != mode_baseline:
                raise RuntimeError(f"FE80-FE8F drifted before {probe['label']}: {current_block.hex()}")
            changed_display = json.loads(ready_path.read_text())
            if (changed_display.get("display_generation") != initial_display.get("display_generation") or
                    changed_display.get("display_profile_generation") != initial_display.get("display_profile_generation")):
                raise RuntimeError("HDMI display profile changed during the live probe")

            item["write_readback"] = register_session.write(
                address, bytes((value,))).hex().upper()
            if args.settle_frames:
                capture.read_frames(args.settle_frames)
            frames = capture.read_frames(args.frames)
            after_block = stable_block(device)
            item["register_block_during_capture"] = after_block.hex(" ").upper()
            if after_block[address - BLOCK_START] != value:
                raise RuntimeError(f"{probe['label']} did not retain candidate value during capture")

            raw_name = f"probe-{index:02d}-{probe['label'].replace('.', '').replace('=', '-')}.yuy2"
            raw_path = args.output / raw_name
            item["capture"] = raw_name
            item["capture_sha256"] = save_frames(raw_path, frames)
            _, item["metrics"] = frame_metrics(frames, width, height,
                                               source_reference, baseline_y)
            item["metrics"]["spatial_response_delta_vs_baseline"] = {
                "B1_vertical": [
                    round(candidate["michelson_contrast"] - base["michelson_contrast"], 6)
                    for candidate, base in zip(
                        item["metrics"]["spatial_response"]["B1_vertical_lines_vary_x"],
                        baseline_metrics["spatial_response"]["B1_vertical_lines_vary_x"])
                ],
                "B2_horizontal": [
                    round(candidate["michelson_contrast"] - base["michelson_contrast"], 6)
                    for candidate, base in zip(
                        item["metrics"]["spatial_response"]["B2_horizontal_lines_vary_y"],
                        baseline_metrics["spatial_response"]["B2_horizontal_lines_vary_y"])
                ],
            }

            collateral = {BLOCK_START + offset for offset, (old, new) in
                          enumerate(zip(mode_baseline, after_block))
                          if offset != address - BLOCK_START and old != new}
            if collateral:
                block_drift.append({"during": probe["label"],
                                    "changed_other_addresses": [f"{a:04X}" for a in sorted(collateral)]})
                for other_address in collateral:
                    offset = other_address - BLOCK_START
                    register_session.original.setdefault(other_address, mode_baseline[offset])
                    register_session.latest[other_address] = after_block[offset]
                register_session._save_journal()
            register_session.restore_addresses({address} | collateral)
            restored_block = stable_block(device)
            if restored_block != mode_baseline:
                mismatch = {BLOCK_START + i for i, (old, new) in
                            enumerate(zip(mode_baseline, restored_block)) if old != new}
                register_session.restore_addresses(mismatch)
                restored_block = stable_block(device)
            if restored_block != mode_baseline:
                raise RuntimeError(f"FE80-FE8F did not restore after {probe['label']}: {restored_block.hex()}")
            item["restored_block"] = restored_block.hex(" ").upper()
            item["status"] = "captured and restored"
            result["probe_results"].append(item)
            result["collateral_block_changes"] = block_drift
            save_result()

        capture.read_frames(args.settle_frames)
        final_frames = capture.read_frames(args.frames)
        final_path = args.output / "restored-final.yuy2"
        result["restored_final_sha256"] = save_frames(final_path, final_frames)
        _, result["restored_final_metrics"] = frame_metrics(final_frames, width, height,
                                                            source_reference, baseline_y)
        result["register_block_after_all_probes"] = stable_block(device).hex(" ").upper()
        if stable_block(device) != mode_baseline:
            raise RuntimeError("Final FE80-FE8F block differs from the stream-start baseline")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result["error"] = error
    finally:
        if device is not None and eeprom_before is not None:
            try:
                if register_session is not None and register_session.original:
                    current = device.read("ram", BLOCK_START, BLOCK_LENGTH)
                    changed = {address for address, original in register_session.original.items()
                               if current[address - BLOCK_START] != original}
                    if changed:
                        register_session.restore_addresses(changed)
                    else:
                        register_session.state = "restored"
                        register_session._save_journal()
                if mode_baseline is not None:
                    restored_live = stable_block(device)
                    result["ram_restore_verified"] = restored_live == mode_baseline
                    result["register_block_after_restore_live"] = restored_live.hex(" ").upper()
            except Exception as exc:
                result["ram_restore_error"] = f"{type(exc).__name__}: {exc}"
        if capture is not None:
            capture.close()
            capture = None
        if device is not None and eeprom_before is not None:
            try:
                after_close = stable_block(device)
                result["register_block_after_stream_closed"] = after_close.hex(" ").upper()
                result["stream_close_register_changes"] = [
                    {"address": f"{BLOCK_START + offset:04X}", "before": f"{before:02X}", "after": f"{after:02X}"}
                    for offset, (before, after) in enumerate(zip(idle_baseline or b"", after_close))
                    if before != after
                ]
            except Exception as exc:
                result["register_block_after_stream_close_error"] = f"{type(exc).__name__}: {exc}"
            try:
                result["eeprom_sha256_after"] = stable_eeprom_hash(device)
                result["eeprom_unchanged"] = result["eeprom_sha256_after"] == eeprom_before
            except Exception as exc:
                result["eeprom_after_error"] = f"{type(exc).__name__}: {exc}"
            device.close()
        result["collateral_block_changes"] = block_drift
        result["recovery_journal"] = str(args.output / "register-session.recovery.json")
        result["status"] = (
            "completed: all candidates restored and EEPROM unchanged"
            if not error and result.get("ram_restore_verified") and result.get("eeprom_unchanged")
            else "failed or incomplete; inspect error, readback, and recovery journal"
        )
        save_result()
    print(json.dumps(result, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
