#!/usr/bin/env python3
"""Compare FE84=7A and 40 with a 1:1 720p input/output chart."""
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

EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
W, H, FRAMES = 1280, 720, 8
VALUES = (0x7A, 0x40)


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
        raise RuntimeError(f"Expected {expected} YUY2 bytes, got {path.stat().st_size}")
    packed = np.frombuffer(path.read_bytes(), dtype=np.uint8).reshape(FRAMES, H, W, 2)
    return packed[..., 0].copy(), path.read_bytes()


def luma_bt709(rgb):
    rgb = rgb.astype(np.float32)
    return np.rint(0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] +
                   0.0722 * rgb[..., 2]).clip(0, 255).astype(np.uint8)


def chart_correlation(y, chart):
    ref = np.asarray(Image.open(chart).convert("L"), dtype=np.float32)
    out = []
    for frame in y:
        f = frame.astype(np.float32)
        if float(f.std()) < 1 or float(ref.std()) < 1:
            out.append(None)
            continue
        c = float(np.corrcoef(ref.ravel(), f.ravel())[0, 1])
        out.append(c if math.isfinite(c) else None)
    return out


def stripe_metrics(captured, reference):
    sx, sy = W / 1920, H / 1080
    cap = captured.mean(axis=0)
    src = reference.astype(np.float64)
    vertical, horizontal = [], []
    for i, period in enumerate((32, 16, 8, 4, 2)):
        x0 = round((1040 + i * 158) * sx)
        xa, xb = x0 + 4, x0 + round(136 * sx) - 4
        yv0, yv1 = round(228 * sy), round(392 * sy)
        cols = np.arange(xa, xb)
        vmask = (((cols - x0) // max(1, period // 2)) % 2) == 0
        y0 = round(458 * sy)
        ya, yb = y0 + 4, round(554 * sy) - 4
        rows = np.arange(ya, yb)
        hmask = (((rows - y0) // max(1, period // 2)) % 2) == 0

        def pair_metrics(image, axis, mask):
            roi = image[yv0:yv1, xa:xb] if axis == "x" else image[ya:yb, xa:xb]
            a = float(roi[:, mask].mean()) if axis == "x" else float(roi[mask, :].mean())
            b = float(roi[:, ~mask].mean()) if axis == "x" else float(roi[~mask, :].mean())
            contrast = (a - b) / (a + b) if a + b else 0.0
            return {"bright_Y_mean": round(a, 5), "dark_Y_mean": round(b, 5),
                    "michelson_contrast": round(contrast, 7)}

        vertical.append({"period_px": period,
                         "capture": pair_metrics(cap, "x", vmask),
                         "source_render": pair_metrics(src, "x", vmask)})
        horizontal.append({"period_px": period,
                           "capture": pair_metrics(cap, "y", hmask),
                           "source_render": pair_metrics(src, "y", hmask)})
    return {"vertical_stripes_vary_x": vertical,
            "horizontal_stripes_vary_y": horizontal}


def flat_fields(y, reference):
    sx, sy = W / 1920, H / 1080
    out = {}
    for name, xa, xb in (("black", 1018, 1270), ("gray", 1318, 1570),
                         ("white", 1618, 1870)):
        x0, x1 = round(xa * sx), round(xb * sx)
        y0, y1 = round(986 * sy), round(1057 * sy)
        # Skip the field label and border; check only the uniform interior.
        x0, x1, y0, y1 = x0 + 8, x1 - 8, y0 + 20, y1 - 5
        block = y[:, y0:y1, x0:x1]
        src = reference[y0:y1, x0:x1]
        out[name] = {"capture_min": int(block.min()), "capture_max": int(block.max()),
                     "capture_mean": round(float(block.mean()), 5),
                     "source_render_min": int(src.min()), "source_render_max": int(src.max()),
                     "source_render_mean": round(float(src.mean()), 5)}
    return out


def analyze(y, chart, render):
    source = np.asarray(Image.open(chart).convert("RGB"), dtype=np.uint8)
    ref = luma_bt709(np.asarray(Image.open(render).convert("RGB"), dtype=np.uint8))
    if source.shape[:2] != (H, W) or ref.shape != (H, W):
        raise RuntimeError("Chart and source-render must both be exactly 1280x720")
    corr = chart_correlation(y, chart)
    if any(c is None or c < 0.80 for c in corr):
        raise RuntimeError(f"Captured frames are constant or do not match the displayed chart: {corr}")
    delta = y.astype(np.int16) - ref[None, ...].astype(np.int16)
    abs_delta = np.abs(delta)
    non_ui = np.ones((H, W), dtype=bool)
    non_ui[:12, W - 20:] = False
    flat = flat_fields(y, ref)
    return {"chart_correlation_per_frame": [round(c, 7) for c in corr],
            "captured_frames_identical": bool(np.all(y == y[0])),
            "source_render_bt709_y": {
                "exact_fraction_all_frames": round(float(np.mean(delta == 0)), 8),
                "within_1_code_fraction_all_frames": round(float(np.mean(abs_delta <= 1)), 8),
                "outside_top_right_20x12_within_1_code_fraction": round(float(np.mean(abs_delta[:, non_ui] <= 1)), 8),
                "mean_absolute_error_codes": round(float(abs_delta.mean()), 6),
                "mean_signed_error_codes": round(float(delta.mean()), 6),
                "max_absolute_error_codes": int(abs_delta.max()),
            },
            "flat_fields": flat,
            "stripe_response": stripe_metrics(y, ref)}


def check_session(session, ready):
    current = json.loads((session / "display-ready.json").read_text())
    target = next((s for s in current.get("screens", []) if s.get("name") == "HDMI TO USB"), {})
    good = (current.get("target_display_available") and current.get("display_profile_matches") and
            current.get("window_screen") == "HDMI TO USB" and
            current.get("chart_kind") == "full-frame-raster" and
            current.get("full_frame_image_size") == [W, H] and
            target.get("width") == W and target.get("height") == H and target.get("scale") == 1 and
            current.get("display_generation") == ready.get("display_generation") and
            current.get("display_profile_generation") == ready.get("display_profile_generation"))
    if not good:
        raise RuntimeError(f"The 1280x720 1:1 chart/display is no longer ready: {current}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chart-session", type=Path, required=True)
    ap.add_argument("--values", nargs="+", type=lambda x: int(x, 16), default=list(VALUES),
                    help="ordered FE84 bytes in hex; defaults to 7A 40")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    if any(not 0 <= v <= 255 for v in args.values) or len(set(args.values)) != len(args.values):
        ap.error("FE84 values must be unique bytes")

    session = args.chart_session.resolve()
    ready = json.loads((session / "display-ready.json").read_text())
    chart = Path(ready["patch_manifest"]).with_suffix(".png")
    render = session / "source-render.png"
    if not chart.is_file() or not render.is_file():
        raise RuntimeError("Chart PNG or AppKit source render is missing")
    check_session(session, ready)

    args.output.mkdir(parents=True)
    result = {"test": "FE84 7A versus 40 at matched 1280x720 input/output",
              "input_mode": [W, H], "capture_mode": [W, H], "frames_per_value": FRAMES,
              "values": [f"{v:02x}" for v in args.values], "chart_session": str(session),
              "firmware_written": False,
              "interpretation_limit": "Matched 720p mode only; this tests luma and stripe response, not the register's exact internal or comb-filter semantics."}
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

        states = []
        for value in args.values:
            check_session(session, ready)
            write_attempted = True
            d.exchange(0xB6, 0xFE84, value)
            if d.read("ram", 0xFE84, 1)[0] != value:
                raise RuntimeError(f"FE84={value:02X} readback failed")
            time.sleep(0.35)
            path = args.output / f"fe84-{value:02x}-1280x720-matched.yuy2"
            y, raw = capture(path)
            analysis = analyze(y, chart, render)
            state = {"FE84": f"{value:02x}", "raw_sha256": sha(raw), "analysis": analysis}
            states.append(state)
            result["states"] = states
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"FE84": state["FE84"],
                              "within_1_code": analysis["source_render_bt709_y"]["within_1_code_fraction_all_frames"],
                              "vertical_contrast": [x["capture"]["michelson_contrast"] for x in analysis["stripe_response"]["vertical_stripes_vary_x"]],
                              "horizontal_contrast": [x["capture"]["michelson_contrast"] for x in analysis["stripe_response"]["horizontal_stripes_vary_y"]]},
                             separators=(",", ":")), flush=True)

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
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
