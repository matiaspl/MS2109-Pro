#!/usr/bin/env python3
"""Measure a guarded RAM-only FE84 response sweep at scaled 720p."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image

from ms2109_hid import Device

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
CHART = ROOT / "artifacts/scaler-f9a0/test-chart-1920x1080.png"
W, H, FRAMES = 1280, 720, 3
SCALE = W / 1920
FLAT_REGIONS = {
    "black": (slice(84, 124), slice(700, 920)),
    "white": (slice(84, 124), slice(1010, 1200)),
    "gray": (slice(180, 360), slice(648, 668)),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


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
    y = np.frombuffer(raw, dtype=np.uint8).reshape(FRAMES, H, W, 2)[..., 0].astype(np.int16)
    return raw, y


def chart_correlation(y):
    ref = np.asarray(Image.open(CHART).convert("L").resize((W, H), Image.Resampling.LANCZOS),
                     dtype=np.float32)
    return [float(np.corrcoef(ref.ravel(), frame.astype(np.float32).ravel())[0, 1])
            for frame in y]


def flat_fields(y):
    result = {}
    for name, (ys, xs) in FLAT_REGIONS.items():
        block = y[:, ys, xs]
        result[name] = {"min": int(block.min()), "max": int(block.max()),
                        "mean": round(float(block.mean()), 5)}
    return result


def stripe_response(y):
    avg = y.astype(np.float64).mean(axis=0)
    out = []
    for i, period in enumerate((32, 16, 8, 4, 2)):
        start = 1040 + i * 158
        x0 = int(np.ceil((start + 3) * SCALE))
        x1 = int(np.floor((start + 137) * SCALE))
        x = np.arange(x0, x1)
        source_x = (x + 0.5) / SCALE
        bright = (((source_x - start) // max(1, period // 2)) % 2) == 0
        roi = avg[173:266, x0:x1]
        hi, lo = float(roi[:, bright].mean()), float(roi[:, ~bright].mean())
        out.append({"source_period_px": period, "bright_Y_mean": round(hi, 4),
                    "dark_Y_mean": round(lo, 4),
                    "michelson_contrast": round((hi - lo) / (hi + lo), 6)})
    return out


def check_session(session, reference):
    current = json.loads((session / "display-ready.json").read_text())
    good = (current.get("target_display_available") and current.get("display_profile_matches") and
            current.get("window_screen") == "HDMI TO USB" and
            current.get("chart_kind") == "full-frame-raster" and
            current.get("full_frame_image_size") == [1920, 1080] and
            current.get("display_generation") == reference.get("display_generation") and
            current.get("display_profile_generation") == reference.get("display_profile_generation"))
    if not good:
        raise RuntimeError(f"Chart/display changed or is no longer ready: {current}")
    return current


def values_for_sweep():
    # Stay inside the previously observed, reversible operating band.
    return sorted(set(range(0x40, 0x81, 4)) | {0x7A, 0x7B})


def parse_hex_byte(text):
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hexadecimal byte: {text}") from exc
    if not 0 <= value <= 0xFF:
        raise argparse.ArgumentTypeError(f"value is not a byte: {text}")
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chart-session", type=Path, required=True,
                    help="fresh output directory from show_scaler_chart.py")
    ap.add_argument("--values", nargs="+", type=parse_hex_byte,
                    help="optional ordered hexadecimal FE84 values; must include 7A for the live-default comparison")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    session = args.chart_session.resolve()
    ready = json.loads((session / "display-ready.json").read_text())
    if not (ready.get("target_display_available") and ready.get("display_profile_matches") and
            ready.get("window_screen") == "HDMI TO USB" and
            ready.get("chart_kind") == "full-frame-raster" and
            ready.get("full_frame_image_size") == [1920, 1080] and
            (session / "source-render.png").is_file()):
        raise RuntimeError("Verified 1920x1080 chart is not ready on HDMI TO USB")

    sweep_values = args.values if args.values is not None else values_for_sweep()
    if len(set(sweep_values)) != len(sweep_values):
        ap.error("--values must not contain duplicates")
    if 0x7A not in sweep_values:
        ap.error("--values must include 7A so the default can be measured in the same session")
    result = {"test": "RAM-only FE84 scaled-output range sweep", "capture_mode": [W, H],
              "frames_per_value": FRAMES, "sweep_values": [f"{v:02x}" for v in sweep_values],
              "chart_session": str(session), "firmware_written": False,
              "interpretation_limit": "Selected FE84 values at 1280x720; it does not qualify other modes or FE84 semantics."}
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
            d.exchange(0xB6, 0xFE84, value)
            if d.read("ram", 0xFE84, 1)[0] != value:
                raise RuntimeError(f"FE84={value:02X} readback failed")
            time.sleep(0.35)
            path = args.output / f"fe84-{value:02x}-1280x720.yuy2"
            raw, y = capture(path)
            corr = chart_correlation(y)
            if min(corr) < 0.85:
                raise RuntimeError(f"Capture at FE84={value:02X} no longer matches chart: {corr}")
            flat = flat_fields(y)
            for name, field in flat.items():
                if field["min"] != field["max"]:
                    raise RuntimeError(f"Uniform {name} field varies at FE84={value:02X}: {field}")
            if baseline_flat is None:
                baseline_flat = flat
            elif any(flat[name]["min"] != baseline_flat[name]["min"] for name in flat):
                raise RuntimeError(f"Flat-field Y changed at FE84={value:02X}: {flat} vs {baseline_flat}")
            state = {"FE84": f"{value:02x}", "raw_sha256": sha(raw),
                     "chart_correlation_per_frame": [round(c, 6) for c in corr],
                     "flat_fields": flat, "stripe_response": stripe_response(y)}
            states.append(state)
            result["states"] = states
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"FE84": state["FE84"], "stripes": state["stripe_response"],
                              "chart_min_correlation": round(min(corr), 6)}, separators=(",", ":")),
                  flush=True)

        d.exchange(0xB6, 0xFE84, before["FE84"])
        if d.read("ram", 0xFE84, 1)[0] != before["FE84"]:
            raise RuntimeError("FE84 restoration readback failed")
        write_attempted = False
        result["restored_FE84"] = f"{before['FE84']:02x}"
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
            d.exchange(0xB6, 0xFE84, before["FE84"])
            result["finally_restored_FE84"] = d.read("ram", 0xFE84, 1).hex()
        d.close()
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
