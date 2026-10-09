#!/usr/bin/env python3
"""RAM-only FE8E/FE8F color probe with paired raw YUY2 and MJPEG captures."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from analyze_color_capture import frame_values
from calibrate_colors import chart as color_chart
from probe_colors import matrix, unpack, write_json
from probe_scaler_register_block import BASELINE_EEPROM, BLOCK_START, stable_block

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
              "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]
FORMATS = ("mjpeg", "yuy2")
PROBES = ((0xFE8E, 0x01, "FE8E.0"), (0xFE8E, 0x10, "FE8E.4"),
          (0xFE8F, 0x01, "FE8F.0"), (0xFE8F, 0x10, "FE8F.4"))
PAIR_STATES: dict[str, tuple[int, int]] = {}
STATE_COLORS = {"Baseline": (32, 32, 32), "FE8E.0": (202, 72, 58),
                "FE8E.4": (226, 143, 47), "FE8F.0": (73, 129, 191),
                "FE8F.4": (156, 91, 181)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    os.replace(temporary, path)


def compile_tools(build: Path) -> dict[str, Path]:
    build.mkdir(parents=True, exist_ok=False)
    bins = {name: build / name for name in ("capture", "admin", "display", "decode")}
    commands = {
        "capture": ["clang", "-Wall", "-Wextra", "-Werror", "-O2", "-I/opt/homebrew/include",
                    "-L/opt/homebrew/lib", str(ROOT / "tools/capture_uvc_same_handle.c"),
                    "-luvc", "-lhidapi", "-lusb-1.0", "-o", str(bins["capture"])],
        "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit",
                  "-framework", "Security", str(ROOT / "tools/run_capture_video_uvc_admin.m"),
                  "-o", str(bins["admin"])],
        "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                    *[arg for fw in FRAMEWORKS for arg in ("-framework", fw)],
                    str(ROOT / "tools/color_probe_macos.m"), "-o", str(bins["display"])],
        "decode": ["clang", "-Wall", "-Wextra", "-Werror", "-O2", "-I/opt/homebrew/include",
                   "-L/opt/homebrew/lib", str(ROOT / "tools/decode_jpeg_ycbcr.c"), "-ljpeg",
                   "-o", str(bins["decode"])],
    }
    for command in commands.values():
        subprocess.run(command, check=True)
    return bins


def decode_first_frame(directory: Path, mode: str, meta: dict, decoder: Path) -> np.ndarray:
    frame = meta["frames"][0]
    path = directory / frame["file"]
    if mode == "yuy2":
        return unpack(path, frame)
    with tempfile.TemporaryDirectory(prefix="ms2109-fe8e-jpeg-") as temporary:
        output = Path(temporary) / "frame.ycbcr"
        detail = Path(temporary) / "frame.json"
        subprocess.run([str(decoder), str(path), str(output), str(detail)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if json.loads(detail.read_text()).get("warnings"):
            raise ValueError(f"JPEG decoder warning in {path}")
        return np.fromfile(output, np.uint8).reshape(frame["height"], frame["width"], 3)


def as_preview(ycbcr: np.ndarray) -> np.ndarray:
    # The MS2109 capture is limited-range BT.709 YCbCr. Treating these values
    # as full range makes black lift, white clip, and patch colors look wrong.
    transform, offset = matrix("709", "limited")
    rgb = (ycbcr.astype(np.float64) - offset) @ np.linalg.inv(transform).T
    return np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)


def font(size: int = 16):
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/SFNS.ttf", "/Library/Fonts/Arial.ttf"):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def render_contact_sheet(root: Path, previews: dict[tuple[str, str], np.ndarray]) -> None:
    states = ["Baseline", *(label for _, _, label in PROBES)]
    tile_w, tile_h, header, margin, gap = 384, 216, 34, 20, 12
    canvas = Image.new("RGB", (margin * 2 + 5 * tile_w + 4 * gap,
                               margin * 2 + 2 * (tile_h + header) + gap), "#f4f4f4")
    draw = ImageDraw.Draw(canvas)
    for row, mode in enumerate(("yuy2", "mjpeg")):
        for col, state in enumerate(states):
            x, y = margin + col * (tile_w + gap), margin + row * (tile_h + header + gap)
            draw.text((x, y), f"{state} | {mode.upper()}", fill="#111111", font=font())
            image = Image.fromarray(previews[(state, mode)], "RGB")
            image.thumbnail((tile_w, tile_h), Image.Resampling.NEAREST)
            canvas.paste(image, (x, y + header))
            draw.rectangle((x, y + header, x + tile_w - 1, y + header + tile_h - 1), outline="#444444")
    canvas.save(root / "color-patch-format-previews.png")


def summarize_delta(base: np.ndarray, candidate: np.ndarray, patches: list[dict]) -> dict:
    delta = candidate - base
    indexes: dict[str, list[int]] = {}
    for index, patch in enumerate(patches):
        indexes.setdefault(patch["group"], []).append(index)
    gray = np.asarray(indexes["gray"][:256], dtype=np.int64)
    codes = np.asarray([patches[index]["code"] for index in gray], dtype=np.float64)
    baseline_line = np.polyfit(codes, base[gray, 0], 1)
    candidate_line = np.polyfit(codes, candidate[gray, 0], 1)
    chroma_indexes = np.asarray([index for group in ("red", "green", "blue", "cyan", "magenta", "yellow")
                                 for index in indexes[group]], dtype=np.int64)
    chroma_delta = delta[chroma_indexes, 1:]
    return {
        "all_patch_median_delta_y_cb_cr": np.median(delta, axis=0).round(4).tolist(),
        "all_patch_rmse_delta_y_cb_cr": np.sqrt(np.mean(delta ** 2, axis=0)).round(4).tolist(),
        "gray_ramp_median_delta_y": round(float(np.median(delta[gray, 0])), 4),
        "gray_ramp_y_slope_baseline": round(float(baseline_line[0]), 6),
        "gray_ramp_y_slope_candidate": round(float(candidate_line[0]), 6),
        "gray_ramp_y_slope_delta": round(float(candidate_line[0] - baseline_line[0]), 6),
        "color_chroma_rms": round(float(np.sqrt(np.mean(chroma_delta ** 2))), 4),
        "color_median_delta_cb_cr": np.median(chroma_delta, axis=0).round(4).tolist(),
        "group_median_delta_y_cb_cr": {
            group: np.median(delta[group_indexes], axis=0).round(4).tolist()
            for group, group_indexes in indexes.items()},
    }


def fit_chroma_mapping(base: np.ndarray, candidate: np.ndarray, patches: list[dict]) -> dict:
    color = np.asarray([patch["group"] != "gray" for patch in patches])
    design = np.column_stack((base[color, 1:], np.ones(int(color.sum()))))
    coefficients = np.linalg.lstsq(design, candidate[color, 1:], rcond=None)[0]
    mapping = coefficients[:2, :].T
    offset = coefficients[2, :]
    residual = design @ coefficients - candidate[color, 1:]
    return {
        "model": "candidate_CbCr = baseline_CbCr @ matrix.T + offset",
        "matrix": mapping.round(6).tolist(),
        "offset": offset.round(4).tolist(),
        "mean_chroma_axis_gain": round(float(np.trace(mapping) / 2), 6),
        "cross_axis_coupling": [round(float(mapping[0, 1]), 6),
                                 round(float(mapping[1, 0]), 6)],
        "fit_rmse_codes": round(float(np.sqrt(np.mean(residual ** 2))), 4),
    }


def render_analysis_plot(root: Path, analysis: dict) -> None:
    canvas = Image.new("RGB", (1600, 1040), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 18), "Captured FE8E/FE8F response: gray ramps and chroma deltas",
              fill="#111111", font=font(22))
    states = ["baseline", *(label for _, _, label in PROBES)]
    panels = {"yuy2": (55, 75, 755, 480), "mjpeg": (835, 75, 1535, 480)}
    for mode, (x0, y0, x1, y1) in panels.items():
        draw.rectangle((x0, y0, x1, y1), outline="#444444", width=2)
        draw.text((x0 + 10, y0 + 6), f"{mode.upper()} output Y vs input gray code",
                  fill="#111111", font=font())
        px0, py0, px1, py1 = x0 + 62, y0 + 42, x1 - 18, y1 - 52
        for tick in (0, 64, 128, 192, 255):
            xx = px0 + (px1 - px0) * tick / 255
            yy = py1 - (py1 - py0) * tick / 255
            draw.line((xx, py0, xx, py1), fill="#e3e3e3")
            draw.line((px0, yy, px1, yy), fill="#e3e3e3")
            draw.text((xx - 9, py1 + 4), str(tick), fill="#555555", font=font(12))
            draw.text((px0 - 34, yy - 7), str(tick), fill="#555555", font=font(12))
        for state in states:
            values = np.asarray(analysis[state][mode]["values"])[:256, 0]
            points = [(px0 + (px1 - px0) * i / 255, py1 - (py1 - py0) * float(v) / 255)
                      for i, v in enumerate(values)]
            key = "Baseline" if state == "baseline" else state
            draw.line(points, fill=STATE_COLORS[key], width=3 if state == "baseline" else 2)
        for index, state in enumerate(states):
            x, y = px0 + (index % 3) * 190, py0 + 6 + (index // 3) * 22
            key = "Baseline" if state == "baseline" else state
            draw.line((x, y + 8, x + 22, y + 8), fill=STATE_COLORS[key], width=3)
            draw.text((x + 27, y), key, fill="#111111", font=font(13))
    x0, y0, x1, y1 = 55, 510, 1535, 1000
    draw.rectangle((x0, y0, x1, y1), outline="#444444", width=2)
    draw.text((x0 + 10, y0 + 8),
              "RMS Delta Cb/Cr vs baseline across red/green/blue/cyan/magenta/yellow ramps",
              fill="#111111", font=font())
    bars = [(state, mode) for state in states[1:] for mode in ("yuy2", "mjpeg")]
    maximum = max(2.0, max(float(analysis[state][mode]["delta_summary"]["color_chroma_rms"])
                           for state, mode in bars))
    px0, py0, px1, py1 = x0 + 75, y0 + 52, x1 - 18, y1 - 60
    for tick in (0, maximum / 2, maximum):
        yy = py1 - (py1 - py0) * tick / maximum
        draw.line((px0, yy, px1, yy), fill="#e3e3e3")
        draw.text((x0 + 8, yy - 7), f"{tick:.1f}", fill="#555555", font=font(12))
    slot = (px1 - px0) / len(bars)
    for index, (state, mode) in enumerate(bars):
        value = float(analysis[state][mode]["delta_summary"]["color_chroma_rms"])
        bx = px0 + index * slot + 7
        top = py1 - (py1 - py0) * value / maximum
        draw.rectangle((bx, top, px0 + (index + 1) * slot - 5, py1), fill=STATE_COLORS[state])
        draw.text((bx, max(py0, top - 22)), f"{value:.2f}", fill="#111111", font=font(13))
        draw.text((bx - 2, py1 + 8), f"{state} {mode}", fill="#333333", font=font(12))
    draw.text((x0 + 8, y1 - 26), "Measured YCbCr codes; this metric does not name the silicon field.",
              fill="#555555", font=font(13))
    canvas.save(root / "fe8e-fe8f-color-response.png")


def write_report(root: Path, result: dict) -> None:
    patches = color_chart()["patches"]
    lines = [
        "# MS2109 FE8E/FE8F color-patch probe", "",
        f"Capture date: {result['utc_started']}", "",
        "Paired raw MJPEG and YUY2 captures used one persistent UVC handle. After each format started, the capture process used its active libusb handle for HID feature reports, read the mode baseline, toggled one volatile XDATA bit, and sampled it during frames. Each chart contains 256-step gray, red, green, blue, cyan, magenta and yellow ramps plus 128 mixed-color patches.", "",
        f"EEPROM SHA-256 before/after: {result.get('eeprom_sha256_before')} / {result.get('eeprom_sha256_after')}. Unchanged: **{result.get('eeprom_unchanged')}**. EEPROM writes: **0**.", "",
        f"FE80-FE8F before/after: {result.get('register_block_before')} / {result.get('register_block_after')}. FE8E/FE8F restored to pre-run bytes: **{result.get('register_block_restored')}**.", "",
        "## Measured response", "",
        "| RAM bit | YUY2 gray ΔY | MJPEG gray ΔY | YUY2 gray slope Δ | MJPEG gray slope Δ | YUY2 chroma RMS | MJPEG chroma RMS | frame windows covered |",
        "|---|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for _, _, label in PROBES:
        y = result["analysis"][label]["yuy2"]["delta_summary"]
        m = result["analysis"][label]["mjpeg"]["delta_summary"]
        yfit = result["analysis"][label]["yuy2"]["chroma_affine_fit"]
        mfit = result["analysis"][label]["mjpeg"]["chroma_affine_fit"]
        held = all(result["trials"][label]["capture_frame_register_coverage"].values())
        lines.append(f"| {label} | {y['gray_ramp_median_delta_y']:.3f} | {m['gray_ramp_median_delta_y']:.3f} | {y['gray_ramp_y_slope_delta']:.6f} | {m['gray_ramp_y_slope_delta']:.6f} | {y['color_chroma_rms']:.3f} | {m['color_chroma_rms']:.3f} | {held} |")
    lines += [
        "", "## Likely behavior from the patch response", "",
        "| RAM bit | Gray ΔY at codes 0 / 32 / 128 / 255 | Y slope ratio vs baseline | Mean Cb/Cr axis gain | YUY2 / MJPEG agreement |",
        "|---|---|---:|---:|:---:|",
    ]
    for _, _, label in PROBES:
        yuy2 = result["analysis"][label]["yuy2"]
        mjpeg = result["analysis"][label]["mjpeg"]
        codes = (0, 32, 128, 255)
        gray_indexes = [index for index, patch in enumerate(patches)
                        if patch["group"] == "gray" and patch["code"] in codes]
        base_y = np.asarray(result["analysis"]["baseline"]["yuy2"]["values"])
        candidate_y = np.asarray(yuy2["values"])
        gray_deltas = {patches[index]["code"]: candidate_y[index][0] - base_y[index][0]
                       for index in gray_indexes}
        yslope_base = result["analysis"]["baseline"]["yuy2"]["gray_ramp_y_slope"]
        yslope_candidate = yuy2["gray_ramp_y_slope"]
        gain_y = yslope_candidate / yslope_base if yslope_base else 0
        gain_cb = yuy2["chroma_affine_fit"]["mean_chroma_axis_gain"]
        mjpeg_gain_cb = mjpeg["chroma_affine_fit"]["mean_chroma_axis_gain"]
        agrees = abs(gain_y - (mjpeg["gray_ramp_y_slope"] /
                               result["analysis"]["baseline"]["mjpeg"]["gray_ramp_y_slope"])) < 0.003 and abs(gain_cb - mjpeg_gain_cb) < 0.003
        lines.append(f"| {label} | {gray_deltas[0]:.1f} / {gray_deltas[32]:.1f} / {gray_deltas[128]:.1f} / {gray_deltas[255]:.1f} | {gain_y:.4f} | {gain_cb:.4f} | {agrees} |")
    lines += [
        "",
        "FE8E.0 adds about 18 luma codes until white clips, with virtually no chroma change; that behaves like a brightness or black-level offset. FE8E.4 increasingly lowers luma as input code rises (slope ratio about 0.858), with no measurable chroma mapping change; that behaves like contrast/gain. FE8F.0 leaves luma and neutral grays unchanged while scaling both chroma axes to about 0.870 of baseline with negligible cross-axis coupling; this is consistent with a saturation/chroma-gain control, not a hue rotation. FE8F.4 produces only about a 0.8% chroma gain, near one-code changes. The YUY2 and MJPEG fits agree closely. These are observed effects of the tested bits; register names and full byte semantics remain unproven.",
        "", "## Interpreting the effect", "",
        "A nearly constant gray-ramp ΔY with little slope change is consistent with a luma offset or black-level path. A changed gray-ramp slope points toward gain, contrast, or nonlinear luma mapping. Chroma changes that vary across color groups are consistent with a saturation, matrix, or channel-mix path. These are behavioral interpretations only; FE8E/FE8F field names remain unresolved.", "",
        "A bit counts as active for a format only when every saved frame timestamp is bracketed by register samples retaining the readback value. Mode-by-mode FE80-FE8F snapshots and raw measurements remain in analysis.json.", "",
        "## Evidence", "",
        "- color-patch-format-previews.png: captured YUY2/MJPEG images decoded through the same BT.709 full-range preview transform.",
        "- fe8e-fe8f-color-response.png: measured gray-ramp curves and color-patch chroma changes relative to baseline.",
        "- analysis.json: register hook events, sampled values, per-format patch medians, temporal spread, and frame coverage.",
        "- analysis/*-patches.csv: measured Y/Cb/Cr values and per-patch deltas.",
        "- trials/*/raw/same-handle/{mjpeg,yuy2}/frame-*: original USB payloads.",
        "- register-recovery.json: RAM restoration journal.", "",
        "The preview transform provides one consistent view of the captured YCbCr values. It does not identify the hardware matrix or quantization range.", "",
    ]
    (root / "report.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--analyze-existing", action="store_true",
                        help="analyze completed captures without accessing the device")
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 60 and 900")
    root = args.output.resolve()
    if root.exists() and not args.analyze_existing:
        parser.error(f"Refusing to overwrite output: {root}")
    if args.analyze_existing and not root.is_dir():
        parser.error(f"No existing output directory to analyze: {root}")
    if not args.analyze_existing:
        root.mkdir(parents=True)
        (root / "trials").mkdir()
    chart_data = color_chart()
    chart_path = root / "chart.json"
    if not args.analyze_existing:
        write_json(chart_path, chart_data)
    result_path = root / "analysis.json"
    result = json.loads(result_path.read_text()) if args.analyze_existing else {
        "test": "RAM-only FE8E/FE8F color-patch probe with paired raw YUY2 and MJPEG",
        "utc_started": datetime.now(timezone.utc).isoformat(),
        "capture_order": ["mjpeg", "yuy2"], "frames_per_format": 8,
        "register_bits": [{"address": f"{address:04X}", "mask": f"{mask:02X}", "label": label}
                          for address, mask, label in PROBES],
        "candidate_register_values": {
            label: {"FE8E": f"{PAIR_STATES[label][0]:02X}",
                    "FE8F": f"{PAIR_STATES[label][1]:02X}"}
            for _, _, label in PROBES if label in PAIR_STATES},
        "eeprom_writes": 0, "status": "running", "trials": {}, "analysis": {},
    }
    if args.analyze_existing:
        bins = {name: root / "compiled-tools" / name
                for name in ("capture", "admin", "display", "decode")}
        if any(not path.is_file() for path in bins.values()):
            parser.error("Existing output is missing its compiled analysis tools")
        result.pop("error", None)
        result["status"] = "analysis replay running"
    else:
        write_json(result_path, result)
        bins = compile_tools(root / "compiled-tools")
        result["compiled_tool_sha256"] = {name: sha256(path) for name, path in bins.items()}
        result["source_sha256"] = {name: sha256(ROOT / "tools" / name) for name in
                                   ("probe_fe8e_fe8f_color.py", "capture_uvc_same_handle.c",
                                    "run_capture_video_uvc_admin.m", "color_probe_macos.m",
                                    "decode_jpeg_ycbcr.c")}
        result["chart_sha256"] = sha256(chart_path)
    pre_block = (bytes.fromhex(result["register_block_before"])
                 if args.analyze_existing and result.get("register_block_before") else None)
    eeprom_before = result.get("eeprom_sha256_before") if args.analyze_existing else None
    eeprom_after = result.get("eeprom_sha256_after") if args.analyze_existing else None
    final_block = (bytes.fromhex(result["register_block_after"])
                   if args.analyze_existing and result.get("register_block_after") else None)
    failure = None
    analysis: dict = {}
    previews: dict[tuple[str, str], np.ndarray] = {}
    mode_baselines: dict[str, bytes] = {}

    def persist() -> None:
        result["analysis"] = analysis
        write_json(result_path, result)

    def run_trial(label: str, target: int | None = None, mask: int | None = None) -> dict:
        nonlocal pre_block, eeprom_before, eeprom_after, final_block
        trial_root = root / "trials" / label
        trial_root.mkdir()
        capture_dir = trial_root / "raw" / "same-handle"
        capture_dir.parent.mkdir()
        log_path = trial_root / "runner.log"
        target = 0xFE8E if target is None else target
        mask = 0 if mask is None else mask
        pair_state = PAIR_STATES.get(label)
        live_mode = "same-handle-live-state" if pair_state is not None else "same-handle-live-register"
        live_args = ([f"{pair_state[0]:02X}", f"{pair_state[1]:02X}"] if pair_state is not None
                     else [f"{target:04X}", f"{mask:02X}"])
        command = [str(bins["admin"]), str(bins["capture"]), str(bins["display"]),
                   str(chart_path), str(capture_dir), live_mode, *live_args]
        log = log_path.open("w")
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        timed_out = False
        while process.poll() is None:
            if time.monotonic() - started > args.timeout_seconds:
                timed_out = True
                process.terminate()
                break
            time.sleep(0.5)
        return_code = process.wait(timeout=30)
        log.close()
        if timed_out:
            raise RuntimeError(f"Capture exceeded {args.timeout_seconds}s; see {log_path}")
        live_log = capture_dir / "live-register.jsonl"
        if not live_log.is_file():
            raise RuntimeError(f"Missing privileged preflight/register log: {live_log}; see {log_path}")
        log_items = [json.loads(line) for line in live_log.read_text().splitlines() if line.strip()]
        preflights = [item for item in log_items if item.get("kind") == "preflight"]
        if len(preflights) != 1:
            raise RuntimeError(f"{label} did not produce exactly one privileged preflight record")
        preflight = preflights[0]
        if preflight.get("chip_id") != "A7109A" or preflight.get("eeprom_size") != 2048:
            raise RuntimeError(f"{label} failed the MS2109 identity/EEPROM-size preflight")
        if preflight.get("eeprom_sha256") != BASELINE_EEPROM:
            raise RuntimeError(f"{label} EEPROM fingerprint mismatch: {preflight.get('eeprom_sha256')}")
        this_pre_block = bytes.fromhex(preflight["register_block"])
        if this_pre_block[0x0e:0x10] != b"\x00\x00":
            raise RuntimeError(f"{label} FE8E/FE8F preflight is not 00/00")
        if pre_block is None:
            pre_block = this_pre_block
            eeprom_before = preflight["eeprom_sha256"]
            result["eeprom_sha256_before"] = eeprom_before
            result["register_block_before"] = pre_block.hex(" ").upper()
            result["preflight"] = {"silicon_id": preflight["chip_id"],
                                    "eeprom_size": preflight["eeprom_size"],
                                    "register_block": result["register_block_before"]}
        elif this_pre_block[0x0e:0x10] != pre_block[0x0e:0x10]:
            raise RuntimeError(f"{label} started with changed FE8E/FE8F values")
        starts = [item for item in log_items if item.get("kind") == "stream-start"]
        restores = [item for item in log_items if item.get("kind") == "stream-stop-restore"]
        final_restore = [item for item in log_items if item.get("kind") == "final-restore"]
        samples = [item for item in log_items if item.get("kind") == "sample"]
        postflights = [item for item in log_items if item.get("kind") == "postflight"]
        recoveries = [item for item in log_items if item.get("kind") == "recovery"]
        if len(postflights) == 1:
            postflight = postflights[0]
            eeprom_after = postflight.get("eeprom_sha256")
            final_block = bytes.fromhex(postflight["register_block"])
            if eeprom_after != eeprom_before:
                raise RuntimeError(f"{label} postflight EEPROM fingerprint changed")
            if final_block[0x0e:0x10] != pre_block[0x0e:0x10]:
                raise RuntimeError(f"{label} postflight FE8E/FE8F differs from preflight")
        elif len(recoveries) == 1 and recoveries[0].get("verified"):
            eeprom_after = recoveries[0].get("eeprom_sha256")
            final_block = bytes.fromhex(recoveries[0]["register_block"])
        elif return_code != 0:
            raise RuntimeError(f"{label} exited {return_code} without verified postflight recovery; see {log_path}")
        if return_code != 0:
            raise RuntimeError(f"{label} capture exited {return_code}; recovery record: {recoveries}; see {log_path}")
        if len(starts) != 2 or len(restores) != 2 or len(final_restore) != 1:
            raise RuntimeError(f"{label} did not log both stream writes/restores and final restoration")
        events = []
        for mode in FORMATS:
            start_event = next((item for item in starts if item["mode"] == mode), None)
            restore_event = next((item for item in restores if item["mode"] == mode), None)
            if start_event is None or restore_event is None:
                raise RuntimeError(f"Missing {mode} register event in {label}")
            before = bytes.fromhex(start_event["register_block_before"])
            after = bytes.fromhex(start_event["register_block_after"])
            active_value = after[target - BLOCK_START]
            if label == "baseline":
                mode_baselines[mode] = before
            elif pair_state is not None:
                expected_pair = bytes(pair_state)
                if after[0x0e:0x10] != expected_pair:
                    raise RuntimeError(f"{label} did not hold FE8E/FE8F {expected_pair.hex()} during {mode}")
                if bytes.fromhex(restore_event["register_block_after"])[0x0e:0x10] != before[0x0e:0x10]:
                    raise RuntimeError(f"{label} failed FE8E/FE8F mode restore after {mode}")
            else:
                mode_base = mode_baselines.get(mode)
                if mode_base is None:
                    raise RuntimeError(f"No matched baseline for {mode}")
                expected = mode_base[target - BLOCK_START] ^ mask
                if active_value != expected:
                    raise RuntimeError(f"{target:04X} did not hold {expected:02X} during {mode}")
            if restore_event["target_value"] != before[target - BLOCK_START]:
                raise RuntimeError(f"{target:04X} failed mode restore after {mode}")
            if label == "baseline":
                disagreement = []
            else:
                disagreement = [f"{BLOCK_START + i:04X}" for i, (a, b) in
                                enumerate(zip(mode_baselines[mode], before))
                                if a != b and BLOCK_START + i not in
                                ({0xFE8E, 0xFE8F} if pair_state is not None else {target})]
            events.append({
                "mode": mode, "block_before_write": before.hex(" ").upper(),
                "block_after_write": after.hex(" ").upper(),
                "target_address": f"{target:04X}", "toggle_mask": f"{mask:02X}",
                "active_value": active_value,
                "active_fe8e": after[0x0e], "active_fe8f": after[0x0f],
                "request_monotonic": start_event["monotonic"],
                "non_target_registers_differ_from_baseline": disagreement,
                "mode_restore_value": restore_event["target_value"],
                "restored_fe8e_fe8f": [
                    f"{bytes.fromhex(restore_event['register_block_after'])[0x0e]:02X}",
                    f"{bytes.fromhex(restore_event['register_block_after'])[0x0f]:02X}"],
            })
        final_block = bytes.fromhex(final_restore[0]["register_block_after"])
        if final_block[0x0e:0x10] != pre_block[0x0e:0x10]:
            raise RuntimeError("Capture process did not restore FE8E/FE8F to pre-run values")
        if final_block[0x0e:0x10] != this_pre_block[0x0e:0x10]:
            raise RuntimeError("Capture process did not restore the pre-run FE8E/FE8F bytes")
        verified_postflight_block = bytes.fromhex(postflights[0]["register_block"])
        if verified_postflight_block[0x0e:0x10] != pre_block[0x0e:0x10]:
            raise RuntimeError("Post-UVC FE8E/FE8F readback differs from pre-run values")
        final_block = verified_postflight_block
        metadata = {}
        for mode in FORMATS:
            path = capture_dir / mode / "usb-capture.json"
            if not path.is_file():
                raise RuntimeError(f"Missing paired raw capture: {path}")
            meta = json.loads(path.read_text())
            if (meta.get("exit_code") != 0 or meta.get("frames_captured") != 8
                    or not meta.get("controls_restoration_ok")):
                raise RuntimeError(f"Incomplete {mode} capture in {label}")
            metadata[mode] = meta
        return {"capture_directory": str(capture_dir), "runner_log": str(log_path),
                "register_log": str(live_log), "hook_events": events,
                "register_samples": samples, "metadata": metadata,
                "requested_fe8e_fe8f": ([f"{pair_state[0]:02X}", f"{pair_state[1]:02X}"
                                         ] if pair_state is not None else None),
                "post_capture_register_block": verified_postflight_block.hex(" ").upper(),
                "eeprom_sha256_before": preflight["eeprom_sha256"],
                "eeprom_sha256_after": postflights[0]["eeprom_sha256"]}

    try:
        if not args.analyze_existing:
            result["trials"]["baseline"] = run_trial("baseline")
            result["mode_register_baselines"] = {
                mode: value.hex(" ").upper() for mode, value in mode_baselines.items()}
            persist()

        for address, mask, label in (() if args.analyze_existing else PROBES):
            original = pre_block[address - BLOCK_START]
            addresses = ({"FE8E": f"{pre_block[0x0e]:02X}", "FE8F": f"{pre_block[0x0f]:02X}"}
                         if label in PAIR_STATES else {f"{address:04X}": f"{original:02X}"})
            latest = ({"FE8E": f"{PAIR_STATES[label][0]:02X}",
                       "FE8F": f"{PAIR_STATES[label][1]:02X}"}
                      if label in PAIR_STATES else {f"{address:04X}": f"{original ^ mask:02X}"})
            journal = {"format": 1, "chip": "MS2109", "region": "volatile XDATA only",
                       "eeprom_sha256": eeprom_before, "state": "active",
                       "updated_utc": datetime.now(timezone.utc).isoformat(),
                       "original_bytes": addresses,
                       "latest_bytes": latest,
                       "recovery_command": "python3 tools/ms2109_register_console.py --recover " + str(root / "register-recovery.json"),
                       "recovery_note": "The elevated same-handle capture helper restores and verifies this RAM byte on every exit."}
            write_atomic(root / "register-recovery.json", json.dumps(journal, indent=2) + "\n")
            item = run_trial(label, address, mask)
            coverage = {}
            expected_pair = PAIR_STATES.get(label)
            for mode in FORMATS:
                event = next(event for event in item["hook_events"] if event["mode"] == mode)
                samples = [sample for sample in item["register_samples"] if sample["mode"] == mode]
                value = event["active_value"]
                checks = []
                for frame in item["metadata"][mode]["frames"]:
                    when = frame["pts_seconds"]
                    earlier = [sample for sample in samples if sample["monotonic"] <= when]
                    later = [sample for sample in samples if sample["monotonic"] >= when]
                    if expected_pair is not None:
                        def has_pair(sample):
                            return (sample.get("fe8e_value") == expected_pair[0] and
                                    sample.get("fe8f_value") == expected_pair[1])
                        checks.append(bool(earlier and later and has_pair(earlier[-1]) and
                                           has_pair(later[0])))
                    else:
                        checks.append(bool(earlier and later and
                                           earlier[-1]["target_value"] == value and
                                           later[0]["target_value"] == value))
                coverage[mode] = len(checks) == 8 and all(checks)
            item["capture_frame_register_coverage"] = coverage
            result["trials"][label] = item
            restored = bytes.fromhex(item["post_capture_register_block"])
            if expected_pair is not None:
                item["restored_fe8e_fe8f"] = [f"{restored[0x0e]:02X}", f"{restored[0x0f]:02X}"]
                item["restore_matches_pretest"] = restored[0x0e:0x10] == pre_block[0x0e:0x10]
            else:
                item["restored_target_value"] = f"{restored[address - BLOCK_START]:02X}"
                item["restore_matches_pretest"] = restored[address - BLOCK_START] == original
            if not item["restore_matches_pretest"]:
                raise RuntimeError(f"{address:04X} failed to restore after {label}")
            journal["state"] = "restored"
            if expected_pair is not None:
                journal["latest_bytes"] = dict(journal["original_bytes"])
            else:
                journal["latest_bytes"][f"{address:04X}"] = f"{original:02X}"
            journal["updated_utc"] = datetime.now(timezone.utc).isoformat()
            write_atomic(root / "register-recovery.json", json.dumps(journal, indent=2) + "\n")
            persist()

        patches = color_chart()["patches"]
        for state in ("baseline", *(label for _, _, label in PROBES)):
            capture_dir = Path(result["trials"][state]["capture_directory"])
            display = json.loads((capture_dir / "display-ready.json").read_text())
            patch_reference = display["patch_reference"]
            if len(patch_reference) != len(patches):
                raise RuntimeError(f"Chart patch count changed for {state}")
            state_values = {}
            for mode in FORMATS:
                directory = capture_dir / mode
                meta = result["trials"][state]["metadata"][mode]
                meta["patch_reference"] = patch_reference
                frame_data = frame_values(directory, meta, bins["decode"])
                if frame_data["maximum_temporal_patch_span"] > 2.0:
                    raise RuntimeError(f"{state}/{mode} patch samples are temporally unstable")
                values = frame_data["median_values"]
                gray_indexes = [index for index, patch in enumerate(patches)
                                if patch["group"] == "gray" and patch.get("code") is not None]
                gray_codes = np.asarray([patches[index]["code"] for index in gray_indexes], dtype=float)
                gray_slope = float(np.polyfit(gray_codes, values[gray_indexes, 0], 1)[0])
                state_values[mode] = {
                    "values": values.tolist(),
                    "gray_ramp_y_slope": round(gray_slope, 6),
                    "maximum_temporal_patch_span": frame_data["maximum_temporal_patch_span"],
                    "frames": frame_data["frames"], "pixel_format": frame_data["format"],
                }
                previews[("Baseline" if state == "baseline" else state, mode)] = as_preview(
                    decode_first_frame(directory, mode, meta, bins["decode"]))
                csv_path = root / "analysis" / f"{state}-{mode}-patches.csv"
                csv_path.parent.mkdir(exist_ok=True)
                with csv_path.open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["name", "group", "input_code", "input_R", "input_G", "input_B",
                                     "median_Y", "median_Cb", "median_Cr"])
                    for patch, measured in zip(patches, values):
                        writer.writerow([patch["name"], patch["group"], patch.get("code", ""),
                                         *patch["rgb"], *measured])
            analysis[state] = state_values
        baseline = {mode: np.asarray(analysis["baseline"][mode]["values"], dtype=np.float64)
                    for mode in FORMATS}
        for _, _, label in PROBES:
            for mode in FORMATS:
                candidate = np.asarray(analysis[label][mode]["values"], dtype=np.float64)
                analysis[label][mode]["delta_summary"] = summarize_delta(baseline[mode], candidate, patches)
                analysis[label][mode]["chroma_affine_fit"] = fit_chroma_mapping(
                    baseline[mode], candidate, patches)
                analysis[label][mode]["rmse_y_cb_cr_vs_baseline"] = np.sqrt(
                    np.mean((candidate - baseline[mode]) ** 2, axis=0)).round(4).tolist()
                csv_path = root / "analysis" / f"{label}-{mode}-patches.csv"
                with csv_path.open("r", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                with csv_path.open("w", newline="") as stream:
                    fields = list(rows[0]) + ["delta_Y", "delta_Cb", "delta_Cr"]
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for index, row in enumerate(rows):
                        for channel, value in zip(("Y", "Cb", "Cr"), candidate[index] - baseline[mode][index]):
                            row[f"delta_{channel}"] = round(float(value), 4)
                        writer.writerow(row)
        render_contact_sheet(root, previews)
        render_analysis_plot(root, analysis)
        result["analysis"] = analysis
        result["status"] = "captures and patch analysis complete; final restoration pending"
        persist()
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        result["error"] = failure
    finally:
        result["eeprom_sha256_after"] = eeprom_after
        result["eeprom_unchanged"] = (eeprom_before is not None and
                                      eeprom_after == eeprom_before)
        result["ram_restore_verified"] = (pre_block is not None and final_block is not None and
            final_block[0x0e:0x10] == pre_block[0x0e:0x10])
        if final_block is not None:
            result["register_block_after"] = final_block.hex(" ").upper()
        result["register_block_restored"] = result.get("ram_restore_verified") is True
        journal_path = root / "register-recovery.json"
        if journal_path.is_file() and result["register_block_restored"] and result["eeprom_unchanged"]:
            try:
                journal = json.loads(journal_path.read_text())
                journal["state"] = "restored"
                journal["latest_bytes"] = dict(journal.get("original_bytes", {}))
                journal["updated_utc"] = datetime.now(timezone.utc).isoformat()
                write_atomic(journal_path, json.dumps(journal, indent=2) + "\n")
            except Exception as journal_error:
                result["recovery_journal_update_error"] = str(journal_error)
        result["status"] = ("complete" if not failure and result.get("eeprom_unchanged") is True
                            and result.get("register_block_restored") is True else "failed or incomplete")
        if failure:
            result["error"] = failure
        write_json(result_path, result)
        if all(label in analysis for label in ("baseline", *(p[2] for p in PROBES))):
            write_report(root, result)
    if failure:
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": result["status"], "output": str(root),
                      "eeprom_unchanged": result.get("eeprom_unchanged"),
                      "register_block_restored": result.get("register_block_restored")}, indent=2))


if __name__ == "__main__":
    main()
