#!/usr/bin/env python3
"""Capture/analyze FE8E/FE8F combinations against external SMPTE HD color bars."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import probe_fe8e_fe8f_color as color_probe
from probe_colors import unpack
from probe_fe8e_fe8f_combinations import (LEVELS, NEUTRAL, SPECS, combination_states,
                                          eeprom_snapshot, read_controls, set_controls,
                                          sha as sha256_bytes)
from probe_scaler_register_block import BASELINE_EEPROM
from ms2109_hid import Device
from probe_procamp_setters import UVC

FORMATS = ("mjpeg", "yuy2")
BAR_NAMES = ("white", "yellow", "cyan", "green", "magenta", "red", "blue")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compile_tools(build: Path) -> dict[str, Path]:
    build.mkdir(parents=True, exist_ok=False)
    bins = {name: build / name for name in ("capture", "admin", "display", "decode")}
    frameworks = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
                  "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]
    commands = {
        "capture": ["clang", "-Wall", "-Wextra", "-Werror", "-O2", "-I/opt/homebrew/include",
                    "-L/opt/homebrew/lib", str(ROOT / "tools/capture_uvc_same_handle.c"),
                    "-luvc", "-lhidapi", "-lusb-1.0", "-o", str(bins["capture"])],
        "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit",
                  "-framework", "Security", str(ROOT / "tools/run_capture_video_uvc_admin.m"),
                  "-o", str(bins["admin"])],
        "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                    *[arg for framework in frameworks for arg in ("-framework", framework)],
                    str(ROOT / "tools/color_probe_macos.m"), "-o", str(bins["display"])],
        "decode": ["clang", "-Wall", "-Wextra", "-Werror", "-O2", "-I/opt/homebrew/include",
                   "-L/opt/homebrew/lib", str(ROOT / "tools/decode_jpeg_ycbcr.c"), "-ljpeg",
                   "-o", str(bins["decode"])],
    }
    for command in commands.values():
        subprocess.run(command, check=True)
    return bins


def decode_frame(path: Path, frame: dict, mode: str, decoder: Path, scratch: Path) -> np.ndarray:
    if mode == "yuy2":
        return unpack(path, frame)
    output = scratch / "decoded.ycbcr"
    detail = scratch / "decoded.json"
    output.unlink(missing_ok=True)
    detail.unlink(missing_ok=True)
    subprocess.run([str(decoder), str(path), str(output), str(detail)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    info = json.loads(detail.read_text())
    if info.get("warnings"):
        raise RuntimeError(f"JPEG decode warning for {path}: {info['warnings']}")
    return np.fromfile(output, np.uint8).reshape(frame["height"], frame["width"], 3)


def bar_rois(width: int, height: int) -> list[tuple[slice, slice]]:
    # The generator letterboxes its 4:3 seven-bar chart with gray side columns.
    # Sample only the centered 75% chart area, away from bar boundaries.
    y0, y1 = round(height * 0.20), round(height * 0.58)
    chart_left, chart_right = width * 0.125, width * 0.875
    bar_width = (chart_right - chart_left) / 7
    rois = []
    for index in range(7):
        left = chart_left + index * bar_width
        right = left + bar_width
        pad = (right - left) * 0.20
        rois.append((slice(y0, y1), slice(round(left + pad), round(right - pad))))
    return rois


def sample_bars(runroot: Path, decoder: Path, labels: list[str]) -> tuple[dict, dict]:
    values: dict[str, dict[str, list[list[float]]]] = {}
    previews: dict[tuple[str, str], np.ndarray] = {}
    scratch = runroot / "decode-scratch"
    scratch.mkdir()
    try:
        for label in labels:
            values[label] = {}
            for mode in FORMATS:
                directory = runroot / "trials" / label / "raw" / "same-handle" / mode
                metadata = json.loads((directory / "usb-capture.json").read_text())
                if metadata.get("frames_captured") != 8 or len(metadata.get("frames", [])) != 8:
                    raise RuntimeError(f"{label}/{mode} did not save exactly eight frames")
                per_frame: list[np.ndarray] = []
                for index, frame in enumerate(metadata["frames"]):
                    image = decode_frame(directory / frame["file"], frame, mode, decoder, scratch)
                    if image.shape[:2] != (1080, 1920):
                        raise RuntimeError(f"Unexpected {mode} frame geometry {image.shape[:2]}")
                    if index == 0:
                        previews[(label, mode)] = color_probe.as_preview(image)
                    per_frame.append(np.asarray([np.median(image[ys, xs], axis=(0, 1))
                                                 for ys, xs in bar_rois(image.shape[1], image.shape[0])]))
                values[label][mode] = np.median(np.stack(per_frame), axis=0).round(4).tolist()
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    return values, previews


def render_contact_sheets(runroot: Path, previews: dict) -> None:
    labels = ["FE8E-00_FE8F-00", *combination_states().keys()]
    for mode in FORMATS:
        columns, tile_w, tile_h, head, gap = 4, 480, 270, 36, 12
        rows = (len(labels) + columns - 1) // columns
        canvas = Image.new("RGB", (columns * tile_w + (columns - 1) * gap,
                                    rows * (tile_h + head) + (rows - 1) * gap), "#f2f2f2")
        draw = ImageDraw.Draw(canvas)
        for index, label in enumerate(labels):
            x, y = index % columns * (tile_w + gap), index // columns * (tile_h + head + gap)
            draw.text((x + 3, y + 5), f"{label.replace('_', ' ')} | {mode.upper()}", fill="#111111")
            image = Image.fromarray(previews[(label, mode)], "RGB")
            image = image.resize((tile_w, tile_h), Image.Resampling.BILINEAR)
            canvas.paste(image, (x, y + head))
            draw.rectangle((x, y + head, x + tile_w - 1, y + head + tile_h - 1), outline="#444444")
        canvas.save(runroot / f"smpte-bars-{mode}-contact-sheet.png")


def summarize(values: dict) -> dict:
    baseline = "FE8E-00_FE8F-00"
    result = {}
    for label, formats in values.items():
        result[label] = {}
        for mode, bars in formats.items():
            bars_array = np.asarray(bars, dtype=np.float64)
            base = np.asarray(values[baseline][mode], dtype=np.float64)
            delta = bars_array - base
            cbcr_delta = delta[:, 1:]
            design = np.column_stack((base[:, 1:], np.ones(len(base))))
            coefficients = np.linalg.lstsq(design, bars_array[:, 1:], rcond=None)[0]
            matrix = coefficients[:2, :].T
            result[label][mode] = {
                "bar_medians_y_cb_cr": bars,
                "delta_medians_y_cb_cr": np.median(delta, axis=0).round(4).tolist(),
                "luma_rms_delta_codes": round(float(np.sqrt(np.mean(delta[:, 0] ** 2))), 4),
                "chroma_rms_delta_codes": round(float(np.sqrt(np.mean(cbcr_delta ** 2))), 4),
                "chroma_linear_mapping": {
                    "matrix": matrix.round(6).tolist(),
                    "offset": coefficients[2, :].round(4).tolist(),
                    "mean_axis_gain": round(float(np.trace(matrix) / 2), 6),
                    "cross_axis_terms": [round(float(matrix[0, 1]), 6),
                                         round(float(matrix[1, 0]), 6)],
                },
            }
    return result


def write_report(runroot: Path, encoding: str, values: dict, analysis: dict,
                 original: dict, register_data: dict) -> None:
    lines = [
        "# MS2109 FE8E/FE8F SMPTE bars probe", "",
        f"HDMI input encoding selected on Decimator MD-CROSS: **{encoding.upper()}** (user-reported; not read from the HDMI link).",
        "Source timing: 1080p60. Test pattern: SMPTE HD color bars. USB capture formats: YUY2 and MJPEG, eight frames per register state.",
        "UVC procamp during sweep: brightness 0, contrast 128, hue 0, saturation 128.",
        "The 16 RAM states cover FE8E and FE8F values 00, 01, 10, and 11 (all combinations of bits 0 and 4). EEPROM writes: 0.",
        f"EEPROM SHA-256 before/after: `{register_data.get('eeprom_sha256_before')}` / `{register_data.get('eeprom_sha256_after')}`; unchanged: **{register_data.get('eeprom_unchanged')}**.",
        f"FE80–FE8F before/after: `{register_data.get('register_block_before')}` / `{register_data.get('register_block_after')}`; restored: **{register_data.get('register_block_restored')}**.",
        "", "## Response by state", "",
        "Each delta compares seven central color-bar regions with the same input-encoding baseline and USB format.",
        "| FE8E | FE8F | USB mode | luma RMS Δ | chroma RMS Δ | mean chroma axis gain |", "|---:|---:|---|---:|---:|---:|",
    ]
    for label, (e_value, f_value) in {"FE8E-00_FE8F-00": (0, 0), **combination_states()}.items():
        for mode in FORMATS:
            entry = analysis[label][mode]
            gain = entry["chroma_linear_mapping"]["mean_axis_gain"]
            lines.append(f"| {e_value:02X} | {f_value:02X} | {mode.upper()} | {entry['luma_rms_delta_codes']:.4f} | {entry['chroma_rms_delta_codes']:.4f} | {gain:.6f} |")
    lines += ["", "## Visual evidence", "",
              "- `smpte-bars-yuy2-contact-sheet.png` and `smpte-bars-mjpeg-contact-sheet.png` show decoded USB captures for every register state.",
              "- `analysis.json` stores the seven bar medians and direct YCbCr deltas for each frame format.",
              "- `trials/*/raw/same-handle/` contains the original USB frames and live register logs.",
              "- `pretest-snapshot.json` and `restore-report.json` record original/restored state.", "",
              "The preview uses a single BT.709 full-range transform for display. Measurements use the captured YCbCr payload values directly. The seven-bar pattern does not provide a neutral gray ramp, so this run cannot establish contrast or black-level behavior. Register interpretation remains behavioral and condition-specific.", ""]
    (runroot / "report.md").write_text("\n".join(lines))


def run_capture(bins: dict[str, Path], runroot: Path, encoding: str, label: str,
                pair: tuple[int, int], timeout: int) -> dict:
    trial = runroot / "trials" / label
    raw_parent = trial / "raw"
    capture_dir = raw_parent / "same-handle"
    raw_parent.mkdir(parents=True)
    log = trial / "runner.log"
    command = [str(bins["admin"]), str(bins["capture"]), str(bins["display"]),
               str(runroot / "external-input-manifest.json"), str(capture_dir),
               "same-handle-live-state-external", f"{pair[0]:02X}", f"{pair[1]:02X}"]
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        start = time.monotonic()
        while process.poll() is None:
            if time.monotonic() - start > timeout:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise TimeoutError(f"Capture timed out; see {log}")
            time.sleep(0.25)
        code = process.returncode
    if code:
        raise RuntimeError(f"Capture {label} failed with exit {code}; see {log}")
    records = [json.loads(line) for line in (capture_dir / "live-register.jsonl").read_text().splitlines() if line]
    preflight = next((item for item in records if item.get("kind") == "preflight"), None)
    postflight = next((item for item in records if item.get("kind") == "postflight"), None)
    if not preflight or not postflight or preflight.get("chip_id") != "A7109A":
        raise RuntimeError(f"{label} missing verified MS2109 identity or postflight")
    if preflight.get("eeprom_sha256") != BASELINE_EEPROM or postflight.get("eeprom_sha256") != BASELINE_EEPROM:
        raise RuntimeError(f"{label} EEPROM hash did not match expected unchanged image")
    for mode in FORMATS:
        metadata = json.loads((capture_dir / mode / "usb-capture.json").read_text())
        if metadata.get("exit_code") != 0 or not metadata.get("controls_restoration_ok") or metadata.get("frames_captured") != 8:
            raise RuntimeError(f"{label}/{mode} frame capture or control restoration failed")
        start_event = next((item for item in records if item.get("kind") == "stream-start" and item.get("mode") == mode), None)
        restore = next((item for item in records if item.get("kind") == "stream-stop-restore" and item.get("mode") == mode), None)
        samples = [item for item in records if item.get("kind") == "sample" and item.get("mode") == mode]
        if not start_event or not restore:
            raise RuntimeError(f"{label}/{mode} is missing register start/restore evidence")
        active = bytes.fromhex(start_event["register_block_after"])[14:16]
        if active != bytes(pair):
            raise RuntimeError(f"{label}/{mode} requested FE8E/FE8F {pair} but read back {active.hex()}")
        coverage = []
        for frame in metadata["frames"]:
            when = frame["pts_seconds"]
            earlier = [item for item in samples if item["monotonic"] <= when]
            later = [item for item in samples if item["monotonic"] >= when]
            coverage.append(bool(earlier and later and
                                 (earlier[-1]["fe8e_value"], earlier[-1]["fe8f_value"]) == pair and
                                 (later[0]["fe8e_value"], later[0]["fe8f_value"]) == pair))
        if len(coverage) != 8 or not all(coverage):
            raise RuntimeError(f"{label}/{mode} did not have requested RAM value bracketing each frame")
    final_block = bytes.fromhex(postflight["register_block"])
    if final_block[14:16] != b"\x00\x00":
        raise RuntimeError(f"{label} failed to restore FE8E/FE8F to 00/00")
    return {"encoding_condition": encoding, "pair": [f"{pair[0]:02X}", f"{pair[1]:02X}"],
            "preflight_eeprom_sha256": preflight["eeprom_sha256"],
            "postflight_eeprom_sha256": postflight["eeprom_sha256"],
            "register_block_after": postflight["register_block"],
            "frame_register_coverage": {mode: True for mode in FORMATS}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-encoding", choices=("rgb", "yuv422", "yuv444"), required=True)
    parser.add_argument("--capture-timeout", type=int, default=300)
    parser.add_argument("--analyze-existing", action="store_true")
    args = parser.parse_args()
    runroot = args.output.resolve()
    if args.analyze_existing:
        if not runroot.is_dir():
            parser.error(f"No capture directory at {runroot}")
    else:
        if runroot.exists():
            parser.error(f"Refusing to overwrite {runroot}")
        runroot.mkdir(parents=True)
        (runroot / "trials").mkdir()
    labels = ["FE8E-00_FE8F-00", *combination_states().keys()]
    states = {"FE8E-00_FE8F-00": (0, 0), **combination_states()}
    original: dict = {}
    device = None
    uvc = None
    failure = None
    restoration = {"attempted": False, "eeprom_writes": 0}
    records: dict[str, dict] = {}
    try:
        if not args.analyze_existing:
            device = Device()
            size, eeprom = eeprom_snapshot(device)
            uvc = UVC()
            original = {"controls": read_controls(uvc), "eeprom_size": size,
                        "eeprom_sha256": sha256_bytes(eeprom),
                        "fe80_fe8f": device.read("ram", 0xFE80, 16).hex(),
                        "fe90_fe93": device.read("ram", 0xFE90, 4).hex(),
                        "c6a0_c6a7": device.read("ram", 0xC6A0, 8).hex()}
            if size != 2048 or sha256_bytes(eeprom) != BASELINE_EEPROM:
                raise RuntimeError("MS2109 EEPROM identity/hash mismatch; refusing live sweep")
            if bytes.fromhex(original["fe80_fe8f"])[14:16] != b"\x00\x00":
                raise RuntimeError("FE8E/FE8F are not at the expected 00/00 baseline")
            (runroot / "pretest-snapshot.json").write_text(json.dumps({
                "input_encoding_condition": args.input_encoding,
                "input_encoding_wire_verified": False, **original}, indent=2) + "\n")
            set_controls(uvc, NEUTRAL)
            if read_controls(uvc) != NEUTRAL:
                raise RuntimeError("Could not set and verify neutral UVC procamp")
            if device.read("ram", 0xFE90, 4) != bytes.fromhex("00808000") or \
               device.read("ram", 0xC6A0, 8) != bytes.fromhex("0000800000008000"):
                raise RuntimeError("Neutral procamp register/shadow readback mismatch")
            uvc.close(); uvc = None
            device.close(); device = None
            bins = compile_tools(runroot / "compiled-tools")
            for label in labels:
                print(f"Capturing {args.input_encoding.upper()} source, {label}", flush=True)
                records[label] = run_capture(bins, runroot, args.input_encoding, label,
                                             states[label], args.capture_timeout)
                (runroot / "capture-progress.json").write_text(json.dumps(records, indent=2) + "\n")
        else:
            progress = json.loads((runroot / "capture-progress.json").read_text())
            records = progress
            original = json.loads((runroot / "pretest-snapshot.json").read_text())
            original.pop("input_encoding_condition", None)
            original.pop("input_encoding_wire_verified", None)
            bins = {name: runroot / "compiled-tools" / name
                    for name in ("capture", "admin", "display", "decode")}
            if any(not path.is_file() for path in bins.values()):
                raise RuntimeError("Existing output is missing its compiled analysis tools")
        values, previews = sample_bars(runroot, bins["decode"], labels)
        analysis = summarize(values)
        render_contact_sheets(runroot, previews)
        report_data = {"input_encoding_condition": args.input_encoding,
                       "input_encoding_wire_verified": False,
                       "utc_started": datetime.now(timezone.utc).isoformat(),
                       "tested_values": ["00", "01", "10", "11"],
                       "register_states": records, "bar_names_assumed": list(BAR_NAMES),
                       "values": values, "analysis": analysis,
                       "eeprom_writes": 0, "source_sha256": {
                           name: sha256_file(ROOT / "tools" / name)
                           for name in ("probe_fe8e_fe8f_generator_bars.py",
                                        "run_capture_video_uvc_admin.m",
                                        "capture_uvc_same_handle.c")}}
        (runroot / "analysis.json").write_text(json.dumps(report_data, indent=2) + "\n")
        # Restore report is populated from the capture journals even if the Python process exits later.
        post_blocks = [item.get("register_block_after") for item in records.values()]
        unchanged = all(item.get("postflight_eeprom_sha256") == BASELINE_EEPROM for item in records.values())
        restored = bool(post_blocks) and all(bytes.fromhex(block)[14:16] == b"\x00\x00" for block in post_blocks)
        restoration.update({"attempted": True, "fe8e_fe8f_restored": restored,
                            "eeprom_unchanged": unchanged,
                            "eeprom_sha256_before": original.get("eeprom_sha256", BASELINE_EEPROM),
                            "eeprom_sha256_after": records[labels[-1]]["postflight_eeprom_sha256"] if records else None,
                            "register_block_before": original.get("fe80_fe8f"),
                            "register_block_after": post_blocks[-1] if post_blocks else None})
        (runroot / "restore-report.json").write_text(json.dumps(restoration, indent=2) + "\n")
        write_report(runroot, args.input_encoding, values, analysis, original, {
            "eeprom_sha256_before": restoration["eeprom_sha256_before"],
            "eeprom_sha256_after": restoration["eeprom_sha256_after"],
            "eeprom_unchanged": unchanged,
            "register_block_before": original.get("fe80_fe8f"),
            "register_block_after": restoration["register_block_after"],
            "register_block_restored": restored})
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        (runroot / "failure.txt").write_text(failure + "\n")
        raise
    finally:
        restoration["attempted"] = True
        if not args.analyze_existing and uvc is None:
            try:
                uvc = UVC()
            except Exception as exc:
                restoration["uvc_reopen_error"] = str(exc)
        if not args.analyze_existing and device is None:
            try:
                device = Device()
            except Exception as exc:
                restoration["hid_reopen_error"] = str(exc)
        if uvc is not None and original.get("controls"):
            try:
                restoration["uvc_restore"] = set_controls(uvc, original["controls"])
                restoration["uvc_readback"] = read_controls(uvc)
                restoration["uvc_restored"] = restoration["uvc_readback"] == original["controls"]
            except Exception as exc:
                restoration["uvc_restore_error"] = str(exc)
        if device is not None and original:
            try:
                # The helper owns FE8E/FE8F restoration. Restore only the procamp RAM mirrors changed via UVC.
                for address, field in ((0xFE90, "fe90_fe93"), (0xC6A0, "c6a0_c6a7")):
                    expected = bytes.fromhex(original[field])
                    if device.read("ram", address, len(expected)) != expected:
                        device.write("ram", address, expected)
                    if device.read("ram", address, len(expected)) != expected:
                        raise RuntimeError(f"RAM restoration failed at {address:04X}")
                current_eeprom = device.read("eeprom", 0, original["eeprom_size"])
                restoration["eeprom_sha256_after"] = sha256_bytes(current_eeprom)
                restoration["eeprom_unchanged"] = restoration["eeprom_sha256_after"] == original["eeprom_sha256"]
                current_block = device.read("ram", 0xFE80, 16)
                restoration["register_block_after"] = current_block.hex()
                restoration["fe8e_fe8f_restored"] = current_block[14:16] == bytes.fromhex(original["fe80_fe8f"])[14:16]
                restoration["ram_restored"] = all([
                    device.read("ram", 0xFE90, 4) == bytes.fromhex(original["fe90_fe93"]),
                    device.read("ram", 0xC6A0, 8) == bytes.fromhex(original["c6a0_c6a7"]),
                    restoration["fe8e_fe8f_restored"]])
            except Exception as exc:
                restoration["ram_restore_error"] = str(exc)
        if uvc is not None:
            uvc.close()
        if device is not None:
            device.close()
        if args.output.exists():
            restoration["error"] = failure
            (runroot / "restore-report.json").write_text(json.dumps(restoration, indent=2) + "\n")


if __name__ == "__main__":
    main()
