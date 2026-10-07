#!/usr/bin/env python3
"""Measure guarded RAM-only FE85 changes with horizontal and vertical line pairs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image

from ms2109_hid import Device

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
CHART_SIZE = (1920, 1080)
W, H, FRAMES = 1280, 720, 3
SCALE_X, SCALE_Y = W / CHART_SIZE[0], H / CHART_SIZE[1]
VALUES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xFF)
FLAT_SOURCE_RECTS = {
    "black": (1100, 1020, 1245, 1048),
    "gray": (1400, 1020, 1545, 1048),
    "white": (1700, 1020, 1845, 1048),
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


def capture(path):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-f", "avfoundation", "-framerate", "10", "-video_size", f"{W}x{H}",
           "-pixel_format", "yuyv422", "-i", "usb video:none", "-frames:v", str(FRAMES),
           "-fps_mode", "passthrough", "-pix_fmt", "yuyv422", "-f", "rawvideo", str(path)]
    subprocess.run(cmd, check=True, timeout=25)
    expected = FRAMES * W * H * 2
    if path.stat().st_size != expected:
        raise RuntimeError(f"Expected {expected} raw bytes, got {path.stat().st_size}")
    raw = path.read_bytes()
    y = np.frombuffer(raw, dtype=np.uint8).reshape(FRAMES, H, W, 2)[..., 0].astype(np.float64)
    return raw, y


def chart_correlation(y, reference_png):
    ref = np.asarray(Image.open(reference_png).convert("L").resize(
        (W, H), Image.Resampling.LANCZOS), dtype=np.float32)
    if float(ref.std()) < 1.0:
        raise RuntimeError("Rendered chart reference has no usable image contrast")
    correlations = []
    for frame in y:
        frame = frame.astype(np.float32)
        if float(frame.std()) < 1.0:
            correlations.append(None)
            continue
        value = float(np.corrcoef(ref.ravel(), frame.ravel())[0, 1])
        correlations.append(value if math.isfinite(value) else None)
    return correlations


def flat_fields(y):
    result = {}
    for name, (sx0, sy0, sx1, sy1) in FLAT_SOURCE_RECTS.items():
        x0, x1 = math.ceil(sx0 * SCALE_X), math.floor(sx1 * SCALE_X)
        y0, y1 = math.ceil(sy0 * SCALE_Y), math.floor(sy1 * SCALE_Y)
        block = y[:, y0:y1, x0:x1]
        result[name] = {"min": int(block.min()), "max": int(block.max()),
                        "mean": round(float(block.mean()), 5)}
    return result


def response(avg, varying_axis, period, x_bounds, y_bounds, pattern_start):
    """Return stripe Michelson contrast for one source-space line-pair patch."""
    x0 = math.ceil(x_bounds[0] * SCALE_X)
    x1 = math.floor(x_bounds[1] * SCALE_X)
    y0 = math.ceil(y_bounds[0] * SCALE_Y)
    y1 = math.floor(y_bounds[1] * SCALE_Y)
    roi = avg[y0:y1, x0:x1]
    if varying_axis == "x":
        coords = (np.arange(x0, x1) + 0.5) / SCALE_X
        mask = (((coords - pattern_start) // max(1, period // 2)) % 2) == 0
        hi, lo = float(roi[:, mask].mean()), float(roi[:, ~mask].mean())
    else:
        coords = (np.arange(y0, y1) + 0.5) / SCALE_Y
        mask = (((coords - pattern_start) // max(1, period // 2)) % 2) == 0
        hi, lo = float(roi[mask, :].mean()), float(roi[~mask, :].mean())
    return {"source_period_px": period, "bright_Y_mean": round(hi, 4),
            "dark_Y_mean": round(lo, 4),
            "michelson_contrast": round((hi - lo) / (hi + lo), 6)}


def stripe_response(y):
    avg = y.mean(axis=0)
    vertical, horizontal = [], []
    for i, period in enumerate((32, 16, 8, 4, 2)):
        x = 1040 + i * 158
        vertical.append(response(avg, "x", period, (x + 8, x + 132),
                                (228, 392), x))
        horizontal.append(response(avg, "y", period, (x + 8, x + 132),
                                  (458, 554), 458))
    return {"vertical_stripes_vary_x": vertical,
            "horizontal_stripes_vary_y": horizontal}


def check_session(session, reference):
    current = json.loads((session / "display-ready.json").read_text())
    good = (current.get("target_display_available") and current.get("display_profile_matches") and
            current.get("window_screen") == "HDMI TO USB" and
            current.get("chart_kind") == "full-frame-raster" and
            current.get("full_frame_image_size") == list(CHART_SIZE) and
            current.get("display_generation") == reference.get("display_generation") and
            current.get("display_profile_generation") == reference.get("display_profile_generation"))
    if not good:
        raise RuntimeError(f"Chart/display changed or is no longer ready: {current}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chart-session", type=Path, required=True)
    ap.add_argument("--values", nargs="+", type=parse_hex_byte,
                    help="ordered hexadecimal FE85 bytes; must include 00 baseline")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    session = args.chart_session.resolve()
    ready_path = session / "display-ready.json"
    ready = json.loads(ready_path.read_text())
    source_render = session / "source-render.png"
    if not (ready.get("target_display_available") and ready.get("display_profile_matches") and
            ready.get("window_screen") == "HDMI TO USB" and
            ready.get("chart_kind") == "full-frame-raster" and
            ready.get("full_frame_image_size") == list(CHART_SIZE) and source_render.is_file()):
        raise RuntimeError("Verified 1920x1080 chart is not ready on HDMI TO USB")

    sweep_values = list(args.values) if args.values is not None else list(VALUES)
    if len(set(sweep_values)) != len(sweep_values):
        ap.error("--values must not contain duplicates")
    if 0x00 not in sweep_values:
        ap.error("--values must include 00 so the FE85 startup baseline is measured")

    result = {"test": "RAM-only FE85 sweep with orthogonal line pairs",
              "input_chart_size": list(CHART_SIZE), "capture_mode": [W, H],
              "frames_per_value": FRAMES, "sweep_values": [f"{v:02x}" for v in sweep_values],
              "chart_session": str(session), "firmware_written": False,
              "interpretation_limit": "Selected FE85 bytes at 1080p input to 720p capture; not a full register decode."}
    d = Device()
    before = None
    write_attempted = False
    try:
        d.identify_eeprom()
        eeprom_before = d.read("eeprom", 0, d.eeprom_size)
        result["eeprom_before_sha256"] = sha(eeprom_before)
        if result["eeprom_before_sha256"] != EXPECTED_EEPROM:
            raise RuntimeError("EEPROM image differs from expected; refusing to test")
        before = {"FE80": d.read("ram", 0xFE80, 1)[0],
                  "FE84": d.read("ram", 0xFE84, 1)[0],
                  "FE85": d.read("ram", 0xFE85, 1)[0],
                  "F9A0": d.read("ram", 0xF9A0, 1)[0],
                  "F92C": d.read("ram", 0xF92C, 1)[0],
                  "FEBA": d.read("ram", 0xFEBA, 1)[0]}
        result["registers_before"] = {k: f"{v:02x}" for k, v in before.items()}
        expected = {"FE80": 1, "FE84": 0x7A, "FE85": 0, "F9A0": 0,
                    "F92C": 0x20, "FEBA": 0}
        if before != expected:
            raise RuntimeError(f"Unexpected live register baseline: {result['registers_before']}")

        args.output.mkdir(parents=True)
        states = []
        baseline_flat = None
        for value in sweep_values:
            check_session(session, ready)
            write_attempted = True
            d.exchange(0xB6, 0xFE85, value)
            if d.read("ram", 0xFE85, 1)[0] != value:
                raise RuntimeError(f"FE85={value:02X} readback failed")
            time.sleep(0.35)
            path = args.output / f"fe85-{value:02x}-1280x720.yuy2"
            raw, y = capture(path)
            corr = chart_correlation(y, source_render)
            if any(c is None or c < 0.80 for c in corr):
                raise RuntimeError(f"Capture at FE85={value:02X} no longer matches chart: {corr}")
            flat = flat_fields(y)
            for name, field in flat.items():
                if field["min"] != field["max"]:
                    raise RuntimeError(f"Uniform {name} field varies at FE85={value:02X}: {field}")
            if baseline_flat is None:
                baseline_flat = flat
            elif any(flat[name]["min"] != baseline_flat[name]["min"] for name in flat):
                raise RuntimeError(f"Flat-field Y changed at FE85={value:02X}: {flat} vs {baseline_flat}")
            state = {"FE85": f"{value:02x}", "raw_sha256": sha(raw),
                     "chart_correlation_per_frame": [round(c, 6) for c in corr],
                     "flat_fields": flat, "stripe_response": stripe_response(y)}
            states.append(state)
            result["states"] = states
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"FE85": state["FE85"], "stripe_response": state["stripe_response"],
                              "chart_min_correlation": round(min(corr), 6)}, separators=(",", ":")),
                  flush=True)

        d.exchange(0xB6, 0xFE85, before["FE85"])
        if d.read("ram", 0xFE85, 1)[0] != before["FE85"]:
            raise RuntimeError("FE85 restoration readback failed")
        write_attempted = False
        result["restored_FE85"] = f"{before['FE85']:02x}"
        eeprom_after = d.read("eeprom", 0, d.eeprom_size)
        result["eeprom_after_sha256"] = sha(eeprom_after)
        result["eeprom_unchanged"] = eeprom_before == eeprom_after
        result["registers_after"] = {k: f"{d.read('ram', addr, 1)[0]:02x}"
                                     for k, addr in (("FE80", 0xFE80), ("FE84", 0xFE84),
                                                     ("FE85", 0xFE85), ("F9A0", 0xF9A0),
                                                     ("F92C", 0xF92C), ("FEBA", 0xFEBA))}
        if not result["eeprom_unchanged"]:
            raise RuntimeError("EEPROM changed during RAM-only test")
        if result["registers_after"] != result["registers_before"]:
            raise RuntimeError("One or more monitored registers failed restoration")
    finally:
        if write_attempted and before is not None:
            d.exchange(0xB6, 0xFE85, before["FE85"])
            result["finally_restored_FE85"] = d.read("ram", 0xFE85, 1).hex()
        if before is not None:
            try:
                eeprom_after = d.read("eeprom", 0, d.eeprom_size)
                result["eeprom_after_sha256"] = sha(eeprom_after)
                result["eeprom_unchanged"] = result.get("eeprom_before_sha256") == result["eeprom_after_sha256"]
                result["registers_after"] = {
                    k: f"{d.read('ram', addr, 1)[0]:02x}"
                    for k, addr in (("FE80", 0xFE80), ("FE84", 0xFE84),
                                    ("FE85", 0xFE85), ("F9A0", 0xF9A0),
                                    ("F92C", 0xF92C), ("FEBA", 0xFEBA))
                }
            except Exception as exc:
                result["post_test_verification_error"] = str(exc)
        d.close()
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
