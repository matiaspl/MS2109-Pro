#!/usr/bin/env python3
"""Compare native 1080p YUY2 luma with a 1:1 gray/edge chart at current and neutral procamp."""
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
CHART_SESSION = ROOT / "artifacts/scaler-f9a0/chart-session-20261007-001220-51789"
W, H = 1920, 1080


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_eeprom(device):
    first = device.read("eeprom", 0, device.eeprom_size)
    second = device.read("eeprom", 0, device.eeprom_size)
    if first != second:
        raise RuntimeError("Two EEPROM reads disagree")
    return sha(first)


def check_chart():
    ready = json.loads((CHART_SESSION / "display-ready.json").read_text())
    if not (ready.get("target_display_available") and ready.get("display_profile_matches")
            and ready.get("window_screen") == "HDMI TO USB"
            and ready.get("chart_kind") == "full-frame-raster"
            and ready.get("full_frame_image_size") == [W, H]):
        raise RuntimeError(f"1:1 chart is not confirmed on the target display: {ready}")
    if not CHART.is_file() or not (CHART_SESSION / "source-render.png").is_file():
        raise RuntimeError("Chart or AppKit source render is missing")
    return ready


def capture_raw(path):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
           "-f", "avfoundation", "-framerate", "5", "-video_size", f"{W}x{H}",
           "-pixel_format", "yuyv422", "-i", "usb video:none", "-frames:v", "8",
           "-fps_mode", "passthrough", "-pix_fmt", "yuyv422", "-f", "rawvideo", str(path)]
    subprocess.run(cmd, check=True, timeout=20)
    frame_size = W * H * 2
    if path.stat().st_size != 8 * frame_size:
        raise RuntimeError(f"Unexpected raw capture size: {path.stat().st_size}")


def analyze(path):
    packed = np.fromfile(path, dtype=np.uint8).reshape(8, H, W, 2)
    y = packed[..., 0]
    src = np.asarray(Image.open(CHART).convert("RGB"), dtype=np.uint8)
    source_y = ((77 * src[..., 0].astype(np.uint16) +
                 150 * src[..., 1].astype(np.uint16) +
                 29 * src[..., 2].astype(np.uint16)) >> 8).astype(np.uint8)
    rendered = np.asarray(Image.open(CHART_SESSION / "source-render.png").convert("RGB"), dtype=np.float32)
    rendered_y = np.rint(0.2126 * rendered[..., 0] + 0.7152 * rendered[..., 1] +
                         0.0722 * rendered[..., 2]).astype(np.uint8)
    delta = y[0].astype(np.int16) - rendered_y.astype(np.int16)
    abs_delta = np.abs(delta)
    all_delta = y.astype(np.int16) - rendered_y[None, ...].astype(np.int16)
    all_abs_delta = np.abs(all_delta)
    outliers = np.argwhere(abs_delta > 1)
    non_ui = np.ones((H, W), dtype=bool)
    non_ui[:12, 1900:] = False
    render_comparison = {
        "reference": str(CHART_SESSION / "source-render.png"),
        "method": "BT.709 luma from the presenter’s AppKit source-render; first raw YUY2 frame",
        "pixel_count": W * H,
        "exact_fraction": round(float(np.mean(delta == 0)), 8),
        "within_1_code_fraction": round(float(np.mean(abs_delta <= 1)), 8),
        "mean_absolute_error_codes": round(float(abs_delta.mean()), 6),
        "mean_signed_error_codes": round(float(delta.mean()), 6),
        "max_absolute_error_codes": int(abs_delta.max()),
        "pixels_over_1_code": int(outliers.shape[0]),
        "pixels_over_1_code_bbox_xyxy": ([int(outliers[:, 1].min()), int(outliers[:, 0].min()),
                                          int(outliers[:, 1].max()) + 1, int(outliers[:, 0].max()) + 1]
                                         if outliers.size else None),
        "outside_top_right_20x12_within_1_code_fraction": round(float(np.mean(abs_delta[non_ui] <= 1)), 8),
        "all_frames_within_1_code_fraction": round(float(np.mean(all_abs_delta <= 1)), 8),
        "all_frames_outside_top_right_20x12_within_1_code_fraction": round(float(np.mean(all_abs_delta[:, non_ui] <= 1)), 8),
        "all_frames_mean_absolute_error_codes": round(float(all_abs_delta.mean()), 6),
        "top_right_exclusion_xyxy": [1900, 0, W, 12],
    }
    stages = []
    for index, period in enumerate((32, 16, 8, 4, 2)):
        x0 = 1040 + index * 158
        columns = np.arange(x0 + 3, x0 + 137)
        bright = (((columns - x0) // max(1, period // 2)) % 2) == 0
        captured = y[:, 260:400, x0 + 3:x0 + 137]
        expected = source_y[260:400, x0 + 3:x0 + 137]
        a = float(captured[..., bright].mean())
        b = float(captured[..., ~bright].mean())
        ea = float(expected[:, bright].mean())
        eb = float(expected[:, ~bright].mean())
        stages.append({"period_px": period,
                       "source_luma_bright_dark": [round(ea, 3), round(eb, 3)],
                       "captured_Y_bright_dark": [round(a, 3), round(b, 3)],
                       "source_michelson": round((ea - eb) / (ea + eb), 6),
                       "captured_michelson": round((a - b) / (a + b), 6),
                       "exact_sample_fraction_vs_png": round(float(np.mean(captured == expected[None, ...])), 6),
                       "exact_sample_fraction_vs_render_luma": round(float(np.mean(captured == rendered_y[None, 260:400, x0 + 3:x0 + 137])), 6),
                       "mean_abs_error_vs_render_luma": round(float(np.mean(np.abs(captured.astype(np.int16) - rendered_y[None, 260:400, x0 + 3:x0 + 137].astype(np.int16)))), 6)})
    flat = {}
    for name, level in (("gray_117", 117), ("gray_232", 232)):
        mask = (rendered_y == level).astype(np.int32)
        integral = np.pad(mask.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
        sums = integral[32:, 32:] - integral[:-32, 32:] - integral[32:, :-32] + integral[:-32, :-32]
        positions = np.argwhere(sums == 32 * 32)
        if positions.size:
            y0, x = map(int, positions[0])
            block = y[:, y0:y0 + 32, x:x + 32]
            flat[name] = {"xyxy": [x, y0, x + 32, y0 + 32],
                          "expected_render_Y": level,
                          "captured_Y_values": np.unique(block).astype(int).tolist(),
                          "captured_Y_mean": round(float(block.mean()), 3),
                          "nonmatching_samples": int(np.count_nonzero(block != level))}
    frame_identical = bool(np.all(y == y[0]))
    return {"capture": str(path), "dimensions": [W, H], "frame_count": 8,
            "frames_identical": frame_identical, "chart_to_Y_exact_fraction": round(float(np.mean(y == source_y[None, ...])), 6),
            "render_luma_comparison": render_comparison,
            "flat_fields": flat, "frequency_patches": stages}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fe84-values", nargs="*", default=["74", "7a", "80"],
                    help="RAM-only FE84 values to test with neutral 0/128 procamp (hex bytes)")
    ap.add_argument("--fe84-current-values", nargs="*", default=[],
                    help="optional FE84 values to test before changing the current procamp")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    args.output.mkdir(parents=True)
    state = check_chart()
    d = Device()
    changed = False
    fe84_original = None
    result = {"chart_ready": state, "before": {}, "neutral": {}, "restored": {},
              "eeprom_before": None, "eeprom_after": None}
    try:
        size = d.identify_eeprom()
        eeprom = checked_eeprom(d)
        if eeprom != EXPECTED_EEPROM:
            raise RuntimeError(f"Unexpected EEPROM image hash: {eeprom}")
        controls = d.read("ram", 0xFE90, 4)
        shadows = d.read("ram", 0xC6A0, 8)
        fe84_original = d.read("ram", 0xFE84, 1)[0]
        result["initial_ram_controls"] = controls.hex()
        result["initial_uvc_shadows"] = shadows.hex()
        result["initial_fe84"] = f"{fe84_original:02x}"
        if controls != bytes.fromhex("ee959300") or shadows != bytes.fromhex("eeff950000009300") or fe84_original != 0x7a:
            raise RuntimeError("Refusing to alter unexpected procamp state")
        result["eeprom_before"] = eeprom
        capture_raw(args.output / "current-profile.yuy2")
        result["before"] = analyze(args.output / "current-profile.yuy2")
        result["fe84_current_profile"] = []
        for value_text in args.fe84_current_values:
            value = int(value_text, 16)
            if not 0 <= value <= 255:
                raise ValueError(f"FE84 value must be a byte: {value_text}")
            d.exchange(0xB6, 0xFE84, value)
            if d.read("ram", 0xFE84, 1)[0] != value:
                raise RuntimeError(f"FE84 readback failed for {value:02x}")
            time.sleep(1)
            check_chart()
            capture_path = args.output / f"fe84-current-{value:02x}.yuy2"
            capture_raw(capture_path)
            result["fe84_current_profile"].append({"value": f"{value:02x}", "analysis": analyze(capture_path)})
            d.exchange(0xB6, 0xFE84, fe84_original)
            if d.read("ram", 0xFE84, 1)[0] != fe84_original:
                raise RuntimeError("FE84 baseline restore failed during current-profile sweep")
        check_chart()
        # Mirror a neutral UVC SET_CUR profile in both hardware and shadows.
        # Restore both regions in finally, including on capture or decode errors.
        neutral_hw = bytes((0, 128, controls[2], controls[3]))
        neutral_shadow = bytes((0, 0, 128, 0)) + shadows[4:]
        for i, value in enumerate(neutral_shadow):
            d.exchange(0xB6, 0xC6A0 + i, value)
        for i, value in enumerate(neutral_hw):
            d.exchange(0xB6, 0xFE90 + i, value)
        changed = True
        if d.read("ram", 0xFE90, 4) != neutral_hw or d.read("ram", 0xC6A0, 8) != neutral_shadow:
            raise RuntimeError("Neutral control readback failed")
        result["neutral_ram_controls"] = neutral_hw.hex()
        result["neutral_uvc_shadows"] = neutral_shadow.hex()
        time.sleep(1)
        check_chart()
        capture_raw(args.output / "neutral-128-128.yuy2")
        result["neutral"] = analyze(args.output / "neutral-128-128.yuy2")
        result["fe84_sweep"] = []
        for value_text in args.fe84_values:
            value = int(value_text, 16)
            if not 0 <= value <= 255:
                raise ValueError(f"FE84 value must be a byte: {value_text}")
            d.exchange(0xB6, 0xFE84, value)
            if d.read("ram", 0xFE84, 1)[0] != value:
                raise RuntimeError(f"FE84 readback failed for {value:02x}")
            time.sleep(1)
            check_chart()
            capture_path = args.output / f"fe84-{value:02x}.yuy2"
            capture_raw(capture_path)
            result["fe84_sweep"].append({"value": f"{value:02x}", "analysis": analyze(capture_path)})
            d.exchange(0xB6, 0xFE84, fe84_original)
            if d.read("ram", 0xFE84, 1)[0] != fe84_original:
                raise RuntimeError("FE84 baseline restore failed during sweep")
    finally:
        if changed:
            if fe84_original is not None:
                d.exchange(0xB6, 0xFE84, fe84_original)
            for i, value in enumerate(shadows):
                d.exchange(0xB6, 0xC6A0 + i, value)
            for i, value in enumerate(controls):
                d.exchange(0xB6, 0xFE90 + i, value)
            if d.read("ram", 0xFE90, 4) != controls or d.read("ram", 0xC6A0, 8) != shadows:
                raise RuntimeError("Failed to restore original procamp state")
            result["restored_ram_controls"] = d.read("ram", 0xFE90, 4).hex()
            result["restored_uvc_shadows"] = d.read("ram", 0xC6A0, 8).hex()
            result["restored_fe84"] = d.read("ram", 0xFE84, 1).hex()
            time.sleep(1)
            capture_raw(args.output / "restored-profile.yuy2")
            result["restored"] = analyze(args.output / "restored-profile.yuy2")
        result["eeprom_after"] = checked_eeprom(d)
        d.close()
    if result["eeprom_before"] != result["eeprom_after"]:
        raise RuntimeError("EEPROM changed during RAM-only procamp test")
    result["test"] = "native 1080 Y-plane comparison, current procamp vs temporary 0/128"
    result["firmware_written"] = False
    result["eeprom_unchanged"] = True
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved guarded native 1080 Y-plane comparison: {args.output / 'result.json'}")


if __name__ == "__main__":
    main()
