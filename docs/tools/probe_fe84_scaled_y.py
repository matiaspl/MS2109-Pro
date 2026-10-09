#!/usr/bin/env python3
"""Compare scaled 720p YUY2 output at FE84=7A and 40 with guarded RAM writes."""
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
W, H, FRAMES = 1280, 720, 8


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture(path):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
           "-f", "avfoundation", "-framerate", "10", "-video_size", f"{W}x{H}",
           "-pixel_format", "yuyv422", "-i", "usb video:none", "-frames:v", str(FRAMES),
           "-fps_mode", "passthrough", "-pix_fmt", "yuyv422", "-f", "rawvideo", str(path)]
    subprocess.run(cmd, check=True, timeout=25)
    expected = FRAMES * W * H * 2
    if path.stat().st_size != expected:
        raise RuntimeError(f"Expected {expected} raw bytes, got {path.stat().st_size}")


def analyze(path):
    p = np.fromfile(path, dtype=np.uint8).reshape(FRAMES, H, W, 2)
    y = p[..., 0].astype(np.int16)
    # Large uniform source fields from the chart, inset to avoid scaled boundaries.
    # These map well inside the chart's large constant fields after 2:3 scaling:
    # top-right black/white bar and the gray gutter between chart columns.
    regions = {"black": (slice(84, 124), slice(700, 920)),
               "white": (slice(84, 124), slice(1010, 1200)),
               "gray": (slice(180, 360), slice(648, 668))}
    flat = {}
    for name, (ys, xs) in regions.items():
        block = y[:, ys, xs]
        flat[name] = {"min": int(block.min()), "max": int(block.max()),
                      "mean": round(float(block.mean()), 5),
                      "nonmodal_samples": int(np.count_nonzero(block != np.bincount(block.ravel(), minlength=256).argmax()))}
    return {"sha256": sha(path.read_bytes()), "shape": [FRAMES, H, W],
            "frame_means": [round(float(f.mean()), 5) for f in y],
            "frame_stddevs": [round(float(f.std()), 5) for f in y],
            "flat_regions": flat, "y": y}


def chart_similarity(y):
    reference = np.asarray(Image.open(CHART).convert("L").resize((W, H), Image.Resampling.LANCZOS), dtype=np.float32)
    captured = y[0].astype(np.float32)
    return float(np.corrcoef(reference.ravel(), captured.ravel())[0, 1])


def assert_flat_fields(analysis, baseline=None):
    fields = analysis["flat_regions"]
    for name, field in fields.items():
        if field["min"] != field["max"]:
            raise RuntimeError(f"Uniform chart field {name} varies across pixels/frames: {field}")
        if baseline is not None and field["min"] != baseline[name]["min"]:
            raise RuntimeError(f"Uniform chart field {name} changed code value: {field} vs {baseline[name]}")


def check_session(session, reference):
    current = json.loads((session / "display-ready.json").read_text())
    required = (current.get("target_display_available") and
                current.get("display_profile_matches") and
                current.get("window_screen") == "HDMI TO USB" and
                current.get("chart_kind") == "full-frame-raster" and
                current.get("full_frame_image_size") == [1920, 1080] and
                current.get("display_generation") == reference.get("display_generation") and
                current.get("display_profile_generation") == reference.get("display_profile_generation"))
    if not required:
        raise RuntimeError(f"Chart/display changed or is no longer ready: {current}")
    return current


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chart-session", type=Path, required=True,
                    help="fresh successful output directory from show_scaler_chart.py")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    session = args.chart_session.resolve()
    ready = json.loads((session / "display-ready.json").read_text())
    if not (ready.get("target_display_available") and ready.get("display_profile_matches") and
            ready.get("window_screen") == "HDMI TO USB" and ready.get("chart_kind") == "full-frame-raster" and
            ready.get("full_frame_image_size") == [1920, 1080] and
            (session / "source-render.png").is_file()):
        raise RuntimeError("Verified 1920x1080 chart is not ready on HDMI TO USB")
    d = Device()
    before = None
    write_attempted = False
    result = {"test": "RAM-only FE84 scaled-output Y comparison", "capture_mode": [W, H],
              "frames_per_state": FRAMES, "chart_session": str(session), "firmware_written": False}
    try:
        d.identify_eeprom()
        eb = d.read("eeprom", 0, d.eeprom_size)
        result["eeprom_before_sha256"] = sha(eb)
        if result["eeprom_before_sha256"] != EXPECTED_EEPROM:
            raise RuntimeError("EEPROM image differs from expected; refusing to test")
        before = {"FE80": d.read("ram", 0xFE80, 1)[0], "FE84": d.read("ram", 0xFE84, 1)[0],
                  "FE85": d.read("ram", 0xFE85, 1)[0], "F9A0": d.read("ram", 0xF9A0, 1)[0],
                  "F92C": d.read("ram", 0xF92C, 1)[0], "FEBA": d.read("ram", 0xFEBA, 1)[0]}
        result["registers_before"] = {k: f"{v:02x}" for k, v in before.items()}
        expected = {"FE80": 1, "FE84": 0x7A, "FE85": 0, "F9A0": 0, "F92C": 0x20, "FEBA": 0}
        if before != expected:
            raise RuntimeError("Unexpected live register baseline; refusing RAM write")
        args.output.mkdir(parents=True)
        base_path = args.output / "fe84-7a-1280x720.yuy2"
        check_session(session, ready)
        capture(base_path)
        base = analyze(base_path)
        similarity = chart_similarity(base["y"])
        result["baseline_chart_similarity"] = round(similarity, 6)
        if similarity < 0.85:
            raise RuntimeError("Captured 1280x720 image does not match the chart; refusing FE84 write")
        assert_flat_fields(base)
        result["baseline_flat_fields_pass"] = True
        check_session(session, ready)
        result["baseline_7a"] = {k: v for k, v in base.items() if k != "y"}
        write_attempted = True
        d.exchange(0xB6, 0xFE84, 0x40)
        if d.read("ram", 0xFE84, 1)[0] != 0x40:
            raise RuntimeError("FE84=40 readback failed")
        time.sleep(1)
        cand_path = args.output / "fe84-40-1280x720.yuy2"
        check_session(session, ready)
        capture(cand_path)
        cand = analyze(cand_path)
        similarity_candidate = chart_similarity(cand["y"])
        result["candidate_chart_similarity"] = round(similarity_candidate, 6)
        if similarity_candidate < 0.85:
            raise RuntimeError("Candidate capture no longer matches the chart")
        assert_flat_fields(cand, base["flat_regions"])
        result["candidate_flat_fields_pass"] = True
        delta = cand["y"] - base["y"]
        result["candidate_40"] = {k: v for k, v in cand.items() if k != "y"}
        result["candidate_minus_baseline_y"] = {
            "mean_absolute_code_delta": round(float(np.abs(delta).mean()), 6),
            "max_absolute_code_delta": int(np.abs(delta).max()),
            "changed_sample_fraction": round(float(np.mean(delta != 0)), 8),
            "fraction_within_1_code": round(float(np.mean(np.abs(delta) <= 1)), 8),
            "per_frame_mean_absolute_delta": [round(float(np.abs(f).mean()), 6) for f in delta],
            "mean_absolute_delta_by_region": {name: round(float(np.abs(delta[:, sl[0], sl[1]]).mean()), 6)
                                               for name, sl in {"center": (slice(100, 620), slice(100, 1180)),
                                                                "fine_chart": (slice(160, 285), slice(680, 1200)),
                                                                "lower_gray": (slice(680, 705), slice(70, 330))}.items()}}
        d.exchange(0xB6, 0xFE84, before["FE84"])
        if d.read("ram", 0xFE84, 1)[0] != before["FE84"]:
            raise RuntimeError("FE84 restoration readback failed")
        write_attempted = False
        result["restored_fe84"] = f"{before['FE84']:02x}"
        ea = d.read("eeprom", 0, d.eeprom_size)
        result["eeprom_after_sha256"] = sha(ea)
        result["eeprom_unchanged"] = eb == ea
        if not result["eeprom_unchanged"]:
            raise RuntimeError("EEPROM changed during RAM-only test")
    finally:
        if write_attempted and before is not None:
            d.exchange(0xB6, 0xFE84, before["FE84"])
            result["restored_fe84_finally"] = d.read("ram", 0xFE84, 1).hex()
        d.close()
        if args.output.exists():
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
