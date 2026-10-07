#!/usr/bin/env python3
"""Characterize FE85 at matched 1920x1080 input/capture resolution.

The probe is deliberately RAM-only. It holds FE84 at 0x40, sets the same
neutral brightness/contrast profile used by the saved native-size comparison,
captures raw YUY2, then restores all touched registers and UVC shadows.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image

from analyze_scaler_roi import edge_profile, roi_slice
from ms2109_hid import Device


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/scaler-f9a0"
CHART = ART / "test-chart-1920x1080.png"
CHART_MANIFEST = ART / "test-chart-1920x1080.json"
SIZE = (1920, 1080)
FRAME_BYTES = SIZE[0] * SIZE[1] * 2
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
DEFAULT_VALUES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xFF)
ROI_PITCHES = {
    "B1 vertical bars": (32, 16, 8, 4, 2),
    "C1 grids": (16, 8, 4, 2, 1),
}
MONITORED = {
    "FE80": 0xFE80,
    "FE84": 0xFE84,
    "FE85": 0xFE85,
    "F9A0": 0xF9A0,
    "F92C": 0xF92C,
    "FEBA": 0xFEBA,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_hex_byte(text):
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hexadecimal byte: {text}") from exc
    if not 0 <= value <= 0xFF:
        raise argparse.ArgumentTypeError(f"value is not a byte: {text}")
    return value


def gray(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    if not (np.array_equal(rgb[..., 0], rgb[..., 1]) and
            np.array_equal(rgb[..., 1], rgb[..., 2])):
        raise ValueError(f"Expected a neutral grayscale chart: {path}")
    return rgb[..., 0]


def full_rgb_to_limited_y(rgb_gray):
    wide = rgb_gray.astype(np.uint16)
    return (16 + (219 * wide // 255)).astype(np.uint8)


def verify_chart_session(session):
    ready_path = session / "display-ready.json"
    ready = json.loads(ready_path.read_text())
    good = (ready.get("target_display_available") and
            ready.get("display_profile_matches") and
            ready.get("window_screen") == "HDMI TO USB" and
            ready.get("chart_kind") == "full-frame-raster" and
            ready.get("full_frame_image_size") == list(SIZE))
    if not good:
        raise RuntimeError(f"Verified full-frame 1080p chart is not ready: {ready}")
    return ready


def write_bytes(device, address, data):
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)
    if device.read("ram", address, len(data)) != data:
        raise RuntimeError(f"RAM readback mismatch at {address:04X}")


def capture(path, frames, rate):
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "avfoundation", "-framerate", str(rate), "-video_size",
        f"{SIZE[0]}x{SIZE[1]}", "-pixel_format", "yuyv422", "-i",
        "usb video:none", "-frames:v", str(frames), "-fps_mode", "passthrough",
        "-pix_fmt", "yuyv422", "-f", "rawvideo", str(path),
    ]
    subprocess.run(command, check=True, timeout=60)
    expected = frames * FRAME_BYTES
    raw = path.read_bytes()
    if len(raw) != expected:
        raise RuntimeError(f"Expected {expected} raw YUY2 bytes, received {len(raw)}")
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(frames, SIZE[1], SIZE[0], 2)
    return raw, packed[..., 0].copy()


def histogram_summary(samples):
    counts = np.bincount(samples.ravel(), minlength=256)
    hot = np.argsort(counts)[-6:][::-1]
    return {
        "mean_y": round(float(samples.mean()), 5),
        "std_y": round(float(samples.std()), 5),
        "min_y": int(samples.min()),
        "max_y": int(samples.max()),
        "dominant_bins_y_fraction": [
            [int(code), round(float(counts[code] / max(samples.size, 1)), 6)]
            for code in hot if counts[code]
        ],
    }


def error_summary(measured, expected):
    delta = np.abs(measured.astype(np.int16) - expected.astype(np.int16))
    return {
        "mae_y_codes": round(float(delta.mean()), 6),
        "rmse_y_codes": round(float(np.sqrt(np.mean(delta.astype(np.float64) ** 2))), 6),
        "exact_fraction": round(float(np.mean(delta == 0)), 8),
        "within_1_fraction": round(float(np.mean(delta <= 1)), 8),
        "within_2_fraction": round(float(np.mean(delta <= 2)), 8),
        "max_abs_error_y_codes": int(delta.max()),
    }


def find_uniform_roi(source, level, size=32):
    mask = (source == level).astype(np.int32)
    integral = np.pad(mask.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
    sums = (integral[size:, size:] - integral[:-size, size:] -
            integral[size:, :-size] + integral[:-size, :-size])
    positions = np.argwhere(sums == size * size)
    if not positions.size:
        return None
    for y0, x0 in positions:
        if not (y0 < 20 and x0 > 1900):
            return int(x0), int(y0), int(x0 + size), int(y0 + size)
    return None


def measure(raw, frames, direct_expected, limited_expected, source, edge_meta,
            reference_edge_direct, reference_edge_limited):
    averaged = frames.mean(axis=0)
    outside_overlay = np.ones(SIZE[::-1], dtype=bool)
    outside_overlay[:20, 1900:] = False
    result = {
        "raw_sha256": sha(raw),
        "frame_count": int(frames.shape[0]),
        "frames_identical": bool(np.all(frames == frames[0])),
        "reference_model_scores": {},
        "frame_correlation_vs_reference_models": {},
        "flat_fields": {},
        "rois": {},
    }
    for model_name, expected in (("direct_full_range_codes", direct_expected),
                                 ("full_to_limited_y", limited_expected)):
        result["reference_model_scores"][model_name] = {
            "full_frame": error_summary(frames, expected[None, ...]),
            "outside_top_right_20x20_overlay": error_summary(
                frames[:, outside_overlay], expected[None, outside_overlay]),
        }
        ref_flat = expected.ravel().astype(np.float64)
        result["frame_correlation_vs_reference_models"][model_name] = []
        for frame in frames:
            frame_flat = frame.ravel().astype(np.float64)
            corr = float(np.corrcoef(ref_flat, frame_flat)[0, 1])
            result["frame_correlation_vs_reference_models"][model_name].append(round(corr, 8))

    level_counts = np.bincount(direct_expected.ravel(), minlength=256)
    flat_levels = []
    for level in np.argsort(level_counts)[::-1]:
        bounds = find_uniform_roi(direct_expected, int(level))
        if bounds is None:
            continue
        x0, y0, x1, y1 = bounds
        block = frames[:, y0:y1, x0:x1]
        result["flat_fields"][str(level)] = {
            "xyxy": list(bounds),
            "expected_direct_y": int(level),
            "expected_limited_y": int(limited_expected[y0, x0]),
            "measured": histogram_summary(block),
        }
        flat_levels.append(int(level))
        if len(flat_levels) == 3:
            break
    result["flat_fields_ranked_by_source_area"] = flat_levels

    for roi_name, pitches in ROI_PITCHES.items():
        result["rois"][roi_name] = {}
        for index, pitch in enumerate(pitches):
            ys, xs = roi_slice(roi_name, index, SIZE)
            roi_frames = frames[:, ys, xs]
            direct_ref = direct_expected[ys, xs]
            limited_ref = limited_expected[ys, xs]
            result["rois"][roi_name][str(pitch)] = {
                **histogram_summary(roi_frames),
                "vs_reference_models": {
                    "direct_full_range_codes": error_summary(roi_frames, direct_ref[None, ...]),
                    "full_to_limited_y": error_summary(roi_frames, limited_ref[None, ...]),
                },
            }

    edge = edge_profile(frames, source, edge_meta, SIZE)
    measured_y = [
        round(float(edge["low_plateau_y"] + value *
                    (edge["high_plateau_y"] - edge["low_plateau_y"])), 4)
        if math.isfinite(value) else None for value in edge["normalized_y"]
    ]
    result["edge_A"] = {
        "measured": measured_y,
        "reference_direct_full_range": reference_edge_direct["y_codes"],
        "reference_full_to_limited": reference_edge_limited["y_codes"],
        "overshoot_codes": edge["overshoot_codes"],
        "undershoot_codes": edge["undershoot_codes"],
        "low_plateau_y": round(float(edge["low_plateau_y"]), 4),
        "high_plateau_y": round(float(edge["high_plateau_y"]), 4),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chart-session", type=Path, required=True)
    parser.add_argument("--values", nargs="+", type=parse_hex_byte,
                        default=list(DEFAULT_VALUES), help="FE85 bytes in hexadecimal")
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--rate", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite {args.output}")
    if args.frames < 3 or args.rate < 1:
        parser.error("--frames must be >=3 and --rate must be >=1")
    if len(set(args.values)) != len(args.values) or 0x00 not in args.values:
        parser.error("--values must be unique and include FE85=00 baseline")

    session = args.chart_session.resolve()
    ready = verify_chart_session(session)
    if not CHART.is_file() or not CHART_MANIFEST.is_file():
        raise FileNotFoundError("Native 1920x1080 chart PNG or manifest is missing")
    chart = gray(CHART)
    source = gray(session / "source-render.png")
    if chart.shape != SIZE[::-1] or source.shape != SIZE[::-1]:
        raise ValueError("Expected 1920x1080 chart and AppKit source-render images")
    source_direct_y = source.copy()
    source_limited_y = full_rgb_to_limited_y(source)
    manifest = json.loads(CHART_MANIFEST.read_text())
    edge_meta = next(edge for edge in manifest["edge_rois"]
                     if edge["label"].startswith("A "))
    def to_code_profile(profile):
        profile["y_codes"] = [
            round(float(profile["low_plateau_y"] + v *
                        (profile["high_plateau_y"] - profile["low_plateau_y"])), 4)
            if math.isfinite(v) else None for v in profile["normalized_y"]
        ]
        return profile

    reference_edge_direct = to_code_profile(
        edge_profile(source_direct_y[None, ...], source_direct_y, edge_meta, SIZE))
    reference_edge_limited = to_code_profile(
        edge_profile(source_limited_y[None, ...], source_limited_y, edge_meta, SIZE))

    args.output.mkdir(parents=True)
    result = {
        "test": "RAM-only FE85 native 1080p-to-1080p sweep with FE84 fixed at 0x40",
        "chart_session": str(session),
        "display_ready": ready,
        "chart": str(CHART.relative_to(ROOT)),
        "source_render_sha256": sha((session / "source-render.png").read_bytes()),
        "capture_mode": [*SIZE, "YUY2"],
        "frames_per_value": args.frames,
        "rate_fps": args.rate,
        "tested_FE85": [f"{v:02x}" for v in args.values],
        "FE84_target": "40",
        "reference_models": {
            "direct_full_range_codes": "Interpret the AppKit-rendered 8-bit gray code directly as captured Y.",
            "full_to_limited_y": "Y = 16 + floor(219 * AppKit source-render gray RGB / 255).",
            "limit": "The AppKit source-render is not a measured HDMI framebuffer. Both candidate code mappings are retained so level range is not confused with FE85 spatial response.",
        },
        "firmware_written": False,
        "eeprom_unchanged": None,
        "states": [],
    }
    device = None
    before = None
    mutation_started = False
    try:
        device = Device()
        device.identify_eeprom()
        eeprom_before = device.read("eeprom", 0, device.eeprom_size)
        result["eeprom_before_sha256"] = sha(eeprom_before)
        if result["eeprom_before_sha256"] != EXPECTED_EEPROM:
            raise RuntimeError("EEPROM hash differs from the characterized device; refusing to probe")
        before = {
            "registers": {name: device.read("ram", addr, 1)[0]
                          for name, addr in MONITORED.items()},
            "controls": device.read("ram", 0xFE90, 4),
            "uvc_shadows": device.read("ram", 0xC6A0, 8),
        }
        result["before"] = {
            "registers": {k: f"{v:02x}" for k, v in before["registers"].items()},
            "controls": before["controls"].hex(),
            "uvc_shadows": before["uvc_shadows"].hex(),
        }
        expected_fixed = {"FE80": 0x01, "F9A0": 0x00, "F92C": 0x20, "FEBA": 0x00}
        unexpected = {k: f"{before['registers'][k]:02x}" for k, v in expected_fixed.items()
                      if before["registers"][k] != v}
        if unexpected:
            raise RuntimeError(f"Unexpected non-target scaler state: {unexpected}")

        # Keep the image path comparable to the saved FE84=40 native run.
        neutral_controls = bytes((0x00, 0x80, before["controls"][2], before["controls"][3]))
        neutral_shadows = bytes((0x00, 0x00, 0x80, 0x00)) + before["uvc_shadows"][4:]
        mutation_started = True
        write_bytes(device, 0xC6A0, neutral_shadows)
        write_bytes(device, 0xFE90, neutral_controls)
        device.exchange(0xB6, 0xFE84, 0x40)
        if device.read("ram", 0xFE84, 1)[0] != 0x40:
            raise RuntimeError("FE84=40 readback failed")
        result["test_controls"] = neutral_controls.hex()
        result["test_uvc_shadows"] = neutral_shadows.hex()

        for value in args.values:
            verify_chart_session(session)
            device.exchange(0xB6, 0xFE85, value)
            readback = device.read("ram", 0xFE85, 1)[0]
            if readback != value:
                raise RuntimeError(f"FE85={value:02X} readback failed")
            if device.read("ram", 0xFE84, 1)[0] != 0x40:
                raise RuntimeError("FE84 changed during the FE85 sweep")
            time.sleep(0.45)
            path = args.output / f"fe85-{value:02x}-1920x1080.yuy2"
            raw, frames = capture(path, args.frames, args.rate)
            measured = measure(raw, frames, source_direct_y, source_limited_y,
                               source, edge_meta, reference_edge_direct,
                               reference_edge_limited)
            corr = measured["frame_correlation_vs_reference_models"]["direct_full_range_codes"]
            if min(corr) < 0.80:
                raise RuntimeError(f"Capture at FE85={value:02X} did not correlate with the chart: {corr}")
            measured["FE85"] = f"{value:02x}"
            measured["FE85_readback"] = f"{readback:02x}"
            result["states"].append(measured)
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({
                "FE85": measured["FE85"],
                "direct_mae": measured["reference_model_scores"]["direct_full_range_codes"]["outside_top_right_20x20_overlay"]["mae_y_codes"],
                "limited_mae": measured["reference_model_scores"]["full_to_limited_y"]["outside_top_right_20x20_overlay"]["mae_y_codes"],
                "B1_2px_direct_mae": measured["rois"]["B1 vertical bars"]["2"]["vs_reference_models"]["direct_full_range_codes"]["mae_y_codes"],
                "C1_1px_direct_mae": measured["rois"]["C1 grids"]["1"]["vs_reference_models"]["direct_full_range_codes"]["mae_y_codes"],
                "edge_over_under": [measured["edge_A"]["overshoot_codes"],
                                     measured["edge_A"]["undershoot_codes"]],
            }, separators=(",", ":")), flush=True)

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if device is not None:
            try:
                if before is not None and mutation_started:
                    for name, address in MONITORED.items():
                        device.exchange(0xB6, address, before["registers"][name])
                    write_bytes(device, 0xFE90, before["controls"])
                    write_bytes(device, 0xC6A0, before["uvc_shadows"])
                    result["restored"] = {
                        "registers": {k: f"{device.read('ram', addr, 1)[0]:02x}"
                                      for k, addr in MONITORED.items()},
                        "controls": device.read("ram", 0xFE90, 4).hex(),
                        "uvc_shadows": device.read("ram", 0xC6A0, 8).hex(),
                    }
                    expected_registers = {k: f"{v:02x}" for k, v in before["registers"].items()}
                    if (result["restored"]["registers"] != expected_registers or
                            result["restored"]["controls"] != before["controls"].hex() or
                            result["restored"]["uvc_shadows"] != before["uvc_shadows"].hex()):
                        raise RuntimeError("RAM restoration readback mismatch")
                if before is not None:
                    eeprom_after = device.read("eeprom", 0, device.eeprom_size)
                    result["eeprom_after_sha256"] = sha(eeprom_after)
                    result["eeprom_unchanged"] = eeprom_after == eeprom_before
                    if not result["eeprom_unchanged"]:
                        raise RuntimeError("EEPROM changed during this RAM-only probe")
            except Exception as restore_exc:
                result["restore_error"] = f"{type(restore_exc).__name__}: {restore_exc}"
                raise
            finally:
                device.close()
        if result["states"]:
            result["rankings_by_level_model"] = {}
            for model in ("direct_full_range_codes", "full_to_limited_y"):
                ranked = sorted(result["states"], key=lambda item: (
                    item["reference_model_scores"][model]["outside_top_right_20x20_overlay"]["mae_y_codes"],
                    item["rois"]["B1 vertical bars"]["2"]["vs_reference_models"][model]["mae_y_codes"],
                    item["rois"]["C1 grids"]["1"]["vs_reference_models"][model]["mae_y_codes"],
                    item["edge_A"]["overshoot_codes"] + item["edge_A"]["undershoot_codes"],
                ))
                result["rankings_by_level_model"][model] = [
                    {"rank": index + 1, "FE85": item["FE85"],
                     "full_frame_mae": item["reference_model_scores"][model]["outside_top_right_20x20_overlay"]["mae_y_codes"],
                     "B1_2px_mae": item["rois"]["B1 vertical bars"]["2"]["vs_reference_models"][model]["mae_y_codes"],
                     "C1_1px_mae": item["rois"]["C1 grids"]["1"]["vs_reference_models"][model]["mae_y_codes"],
                     "edge_total_over_under": round(item["edge_A"]["overshoot_codes"] +
                                                     item["edge_A"]["undershoot_codes"], 4)}
                    for index, item in enumerate(ranked)
                ]
        if result.get("restored") or result.get("error"):
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    print(f"Saved native FE85 characterization: {args.output / 'result.json'}")


if __name__ == "__main__":
    main()
