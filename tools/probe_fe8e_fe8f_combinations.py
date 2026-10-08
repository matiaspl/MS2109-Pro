#!/usr/bin/env python3
"""Capture all combinations of FE8E/FE8F bits 0 and 4 with paired formats."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import probe_fe8e_fe8f_color as probe
from ms2109_hid import Device
from probe_procamp_setters import UVC
from probe_scaler_register_block import BASELINE_EEPROM

CURRENT = {"brightness": -18, "contrast": 149, "hue": 0, "saturation": 147}
NEUTRAL = {"brightness": 0, "contrast": 128, "hue": 0, "saturation": 128}
SPECS = {"brightness": (2, True), "contrast": (3, False),
         "hue": (6, True), "saturation": (7, False)}
LEVELS = (0x00, 0x01, 0x10, 0x11)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_controls(uvc: UVC) -> dict[str, int]:
    return {name: int.from_bytes(uvc.get(selector, 0x81), "little", signed=signed)
            for name, (selector, signed) in SPECS.items()}


def set_controls(uvc: UVC, values: dict[str, int]) -> dict:
    checks = {}
    for name in ("brightness", "contrast", "hue", "saturation"):
        selector, signed = SPECS[name]
        payload = int(values[name]).to_bytes(2, "little", signed=signed)
        request = uvc.set(selector, payload)
        actual = int.from_bytes(uvc.get(selector, 0x81), "little", signed=signed)
        checks[name] = {"request": request, "readback": actual,
                        "ok": request["return_code"] == 2 and actual == values[name]}
        if not checks[name]["ok"]:
            raise RuntimeError(f"{name} set/readback mismatch: {checks[name]}")
    return checks


def ram_snapshot(device: Device) -> dict[str, str]:
    return {
        "fe80_fe8f": device.read("ram", 0xFE80, 16).hex(),
        "fe90_fe93": device.read("ram", 0xFE90, 4).hex(),
        "c6a0_c6a7": device.read("ram", 0xC6A0, 8).hex(),
    }


def eeprom_snapshot(device: Device) -> tuple[int, bytes]:
    size = device.identify_eeprom()
    first = device.read("eeprom", 0, size)
    second = device.read("eeprom", 0, size)
    if first != second:
        raise RuntimeError("EEPROM double reads disagree")
    return size, first


def combination_states() -> dict[str, tuple[int, int]]:
    return {
        f"FE8E-{fe8e:02X}_FE8F-{fe8f:02X}": (fe8e, fe8f)
        for fe8e in LEVELS for fe8f in LEVELS
        if (fe8e, fe8f) != (0, 0)
    }


def render_contact_sheets(root: Path, previews: dict[tuple[str, str], np.ndarray]) -> None:
    states = ["Baseline", *probe.PAIR_STATES]
    columns, tile_w, tile_h, header, gap = 4, 320, 180, 32, 12
    rows = (len(states) + columns - 1) // columns
    for mode in ("yuy2", "mjpeg"):
        canvas = Image.new("RGB", (columns * tile_w + (columns - 1) * gap,
                                    rows * (tile_h + header) + (rows - 1) * gap), "#f4f4f4")
        draw = ImageDraw.Draw(canvas)
        for index, state in enumerate(states):
            col, row = index % columns, index // columns
            x, y = col * (tile_w + gap), row * (tile_h + header + gap)
            title = "Baseline" if state == "Baseline" else state.replace("_", " ")
            draw.text((x, y), f"{title} | {mode.upper()}", fill="#111111")
            image = Image.fromarray(previews[(state, mode)], "RGB")
            image = image.resize((tile_w, tile_h), Image.Resampling.BILINEAR)
            canvas.paste(image, (x, y + header))
            draw.rectangle((x, y + header, x + tile_w - 1, y + header + tile_h - 1),
                           outline="#444444")
        canvas.save(root / f"combinations-{mode}-decoded-preview.png")


def projected_rgb(values: np.ndarray) -> np.ndarray:
    transform, offset = probe.matrix("709", "full")
    return (values.astype(np.float64) - offset) @ np.linalg.inv(transform).T


def add_rgb_metrics(result: dict) -> None:
    baseline = result["analysis"]["baseline"]
    for label in probe.PAIR_STATES:
        for mode in probe.FORMATS:
            reference = projected_rgb(np.asarray(baseline[mode]["values"]))
            candidate = projected_rgb(np.asarray(result["analysis"][label][mode]["values"]))
            delta = candidate - reference
            result["analysis"][label][mode]["derived_rgb_bt709_full"] = {
                "median_delta_rgb": np.median(delta, axis=0).round(4).tolist(),
                "rmse_rgb_codes": round(float(np.sqrt(np.mean(delta ** 2))), 4),
                "maximum_absolute_delta_rgb": round(float(np.max(np.abs(delta))), 4),
                "source": "linear BT.709 full-range projection of captured USB YCbCr patches",
            }


def render_summary_grid(root: Path, analysis: dict) -> None:
    image = Image.new("RGB", (1440, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 14), "FE8E/FE8F bit 0+4 combination response (input claimed YUV)",
              fill="#111111")
    draw.text((24, 44), "Rows: FE8E byte | columns: FE8F byte. Cells show direct USB chroma RMS delta.",
              fill="#333333")
    x0, y0, cell_w, cell_h = 190, 130, 300, 170
    levels = [f"{v:02X}" for v in LEVELS]
    maxima = [float(analysis[label][mode]["delta_summary"]["color_chroma_rms"])
              for label in probe.PAIR_STATES for mode in probe.FORMATS]
    maximum = max(max(maxima, default=0.0), 0.01)
    draw.text((28, y0 + cell_h // 2), "FE8E", fill="#111111")
    draw.text((x0 + 2 * cell_w - 20, 92), "FE8F", fill="#111111")
    for col, f_value in enumerate(levels):
        draw.text((x0 + col * cell_w + cell_w // 2 - 12, y0 - 24), f_value, fill="#111111")
    for row, e_value in enumerate(levels):
        draw.text((x0 - 42, y0 + row * cell_h + cell_h // 2 - 8), e_value, fill="#111111")
        for col, f_value in enumerate(levels):
            label = f"FE8E-{e_value}_FE8F-{f_value}"
            x, y = x0 + col * cell_w, y0 + row * cell_h
            if label == "FE8E-00_FE8F-00":
                yuy2 = mjpeg = 0.0
            else:
                yuy2 = float(analysis[label]["yuy2"]["delta_summary"]["color_chroma_rms"])
                mjpeg = float(analysis[label]["mjpeg"]["delta_summary"]["color_chroma_rms"])
            strength = min(255, round(235 * max(yuy2, mjpeg) / maximum))
            color = (255, 255 - strength // 2, 255 - strength)
            draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1),
                           fill=color, outline="#555555", width=2)
            draw.text((x + 12, y + 12), f"FE8E={e_value} FE8F={f_value}", fill="#111111")
            draw.text((x + 12, y + 48), f"ΔC RMS  YUY2: {yuy2:.3f} codes", fill="#111111")
            draw.text((x + 12, y + 76), f"ΔC RMS  MJPEG: {mjpeg:.3f} codes", fill="#111111")
            draw.text((x + 12, y + 112), "Baseline" if label == "FE8E-00_FE8F-00" else "RAM state restored",
                      fill="#333333")
    image.save(root / "combination-response-grid.png")


def write_report(root: Path, result: dict, input_encoding: str) -> None:
    add_rgb_metrics(result)
    lines = [
        "# MS2109 FE8E/FE8F full bit 0+4 combination sweep", "",
        f"Capture UTC: {result['utc_started']}", "",
        f"HDMI input condition: **{input_encoding.upper()}** as specified for this run. The capture software identifies the Mac display but cannot independently verify RGB versus YCbCr on the HDMI wire.",
        "",
        "The tested four-bit field is FE8E.0, FE8E.4, FE8F.0, FE8F.4. The 16 states include 00/00 baseline plus every combination of byte values 00, 01, 10, 11. Each state has eight frames per native USB format (YUY2 and MJPEG) while UVC procamp is neutral (brightness 0, contrast 128, hue 0, saturation 128).",
        "",
        f"EEPROM writes: **0**. EEPROM SHA-256 before/after: `{result.get('eeprom_sha256_before')}` / `{result.get('eeprom_sha256_after')}`; unchanged: **{result.get('eeprom_unchanged')}**.",
        f"FE8E/FE8F pretest/posttest: `{result.get('register_block_before')}` / `{result.get('register_block_after')}`; restored: **{result.get('register_block_restored')}**.",
        "",
        "## Results",
        "",
        "| FE8E | FE8F | USB mode | median ΔY | gray slope ratio | chroma gain | chroma RMS Δ | derived RGB RMS Δ | frame readback covered |",
        "|---:|---:|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for label, (fe8e, fe8f) in probe.PAIR_STATES.items():
        for mode in probe.FORMATS:
            entry = result["analysis"][label][mode]
            delta = entry["delta_summary"]
            baseline_slope = result["analysis"]["baseline"][mode]["gray_ramp_y_slope"]
            slope_ratio = entry["gray_ramp_y_slope"] / baseline_slope if baseline_slope else 0.0
            gain = entry["chroma_affine_fit"]["mean_chroma_axis_gain"]
            rgb = entry["derived_rgb_bt709_full"]["rmse_rgb_codes"]
            covered = all(result["trials"][label]["capture_frame_register_coverage"].values())
            lines.append(f"| {fe8e:02X} | {fe8f:02X} | {mode.upper()} | {delta['gray_ramp_median_delta_y']:.3f} | {slope_ratio:.6f} | {gain:.6f} | {delta['color_chroma_rms']:.4f} | {rgb:.4f} | {covered} |")
    lines += [
        "",
        "YCbCr values are measured directly from the USB payload: packed 4:2:2 for YUY2 and decoded JPEG YCbCr for MJPEG. The RGB column is a mathematical BT.709 full-range projection of those captured YCbCr patch medians; it is not an independent HDMI RGB capture. A difference in YCbCr must also appear under any non-clipping invertible YCbCr-to-RGB transform, while a zero YCbCr delta cannot be explained by the host simply receiving RGB instead.",
        "",
        "This sweep holds the HDMI input condition fixed as YUV. If the response is gated by RGB HDMI input, that requires a second run with the source actually switched to RGB. No USB-output-format change can substitute for changing the HDMI input encoding.",
        "",
        "## Visual evidence",
        "",
        "- `combinations-yuy2-decoded-preview.png` and `combinations-mjpeg-decoded-preview.png`: previews reconstructed from the captured YCbCr payloads with one consistent BT.709 full-range transform.",
        "- `combination-response-grid.png`: direct USB chroma RMS difference for each register-value pair.",
        "- `analysis.json` and `analysis/*-patches.csv`: per-patch measurements, temporal spreads, derived RGB metrics, and per-frame register coverage.",
        "- `trials/*/raw/same-handle/`: original USB payloads and live register logs.",
        "- `../pretest-snapshot.json` and `../restore-report.json`: original and restored RAM, UVC controls, and EEPROM verification.",
        "",
        "No register meaning is inferred from this response matrix; it describes only the tested input condition, modes, chart, and values.",
    ]
    result["hdmi_input_encoding_condition"] = input_encoding
    result["hdmi_input_encoding_wire_verified"] = False
    probe.write_json(root / "analysis.json", result)
    (root / "report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--hdmi-input-encoding", choices=("yuv", "rgb", "unknown"),
                        default="yuv", help="reported test condition; wire encoding is not read by this tool")
    args = parser.parse_args()
    runroot = args.output.resolve()
    if runroot.exists():
        parser.error(f"Refusing to overwrite output: {runroot}")
    runroot.mkdir(parents=True)
    result_path = runroot / "restore-report.json"
    report = {"scope": "RAM-only full factorial FE8E.0/4 x FE8F.0/4 probe",
              "runroot": str(runroot), "hdmi_input_encoding_condition": args.hdmi_input_encoding,
              "hdmi_input_encoding_wire_verified": False,
              "restoration": {"attempted": False}}
    device = None
    uvc = None
    original: dict = {}
    failure = None
    states = combination_states()
    probe.PAIR_STATES = states
    probe.PROBES = tuple((0xFE8E, 0, label) for label in states)
    probe.STATE_COLORS.update({label: (45 + i * 29 % 190, 52 + i * 47 % 185,
                                       61 + i * 71 % 180)
                               for i, label in enumerate(states)})
    probe.render_contact_sheet = render_contact_sheets
    probe.render_analysis_plot = render_summary_grid
    probe.write_report = lambda root, data: write_report(root, data, args.hdmi_input_encoding)
    try:
        device = Device()
        size, eeprom = eeprom_snapshot(device)
        uvc = UVC()
        controls = read_controls(uvc)
        ram = ram_snapshot(device)
        original = {"controls": controls, "ram": ram, "eeprom_size": size,
                    "eeprom_sha256": sha(eeprom)}
        report.update({"controls_before": controls, "ram_before": ram,
                       "eeprom_sha256_before": sha(eeprom)})
        if size != 2048 or sha(eeprom) != BASELINE_EEPROM:
            raise RuntimeError(f"Unexpected EEPROM identity: size={size}, sha256={sha(eeprom)}")
        if bytes.fromhex(ram["fe80_fe8f"])[14:] != b"\0\0":
            raise RuntimeError("FE8E/FE8F are not at expected 00/00 baseline")
        snapshot = {**original, "hdmi_input_encoding_condition": args.hdmi_input_encoding,
                    "hdmi_input_encoding_wire_verified": False}
        (runroot / "pretest-snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        report["neutralization"] = set_controls(uvc, NEUTRAL)
        if read_controls(uvc) != NEUTRAL:
            raise RuntimeError("Neutral UVC GET_CUR verification failed")
        if device.read("ram", 0xFE90, 4) != bytes.fromhex("00808000"):
            raise RuntimeError("Neutral procamp hardware mirror failed")
        if device.read("ram", 0xC6A0, 8) != bytes.fromhex("0000800000008000"):
            raise RuntimeError("Neutral procamp shadow mirror failed")
        uvc.close(); uvc = None
        device.close(); device = None
        sys.argv = [str(ROOT / "tools/probe_fe8e_fe8f_color.py"),
                    "--output", str(runroot / "probe"),
                    "--timeout-seconds", str(args.timeout_seconds)]
        probe.main()
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        report["error"] = failure
        report["traceback"] = traceback.format_exc()
    finally:
        report["restoration"]["attempted"] = True
        if uvc is None:
            try:
                uvc = UVC()
            except Exception as exc:
                report["restoration"]["uvc_open_error"] = str(exc)
        if device is None:
            try:
                device = Device()
            except Exception as exc:
                report["restoration"]["hid_open_error"] = str(exc)
        if uvc is not None and original.get("controls"):
            try:
                report["restoration"]["uvc_set"] = set_controls(uvc, original["controls"])
            except Exception as exc:
                report["restoration"]["uvc_set_error"] = f"{type(exc).__name__}: {exc}"
        if device is not None and original.get("ram"):
            try:
                for name, address in (("fe80_fe8f", 0xFE80), ("fe90_fe93", 0xFE90),
                                      ("c6a0_c6a7", 0xC6A0)):
                    wanted = bytes.fromhex(original["ram"][name])
                    current = device.read("ram", address, len(wanted))
                    if current != wanted:
                        for offset, value in enumerate(wanted):
                            device.exchange(0xB6, address + offset, value)
                report["restoration"]["ram_after"] = ram_snapshot(device)
                report["ram_restored"] = report["restoration"]["ram_after"] == original["ram"]
                size_after, eeprom_after = eeprom_snapshot(device)
                report["eeprom_sha256_after"] = sha(eeprom_after)
                report["eeprom_unchanged"] = (size_after == original["eeprom_size"]
                                               and eeprom_after == eeprom)
            except Exception as exc:
                report["restoration"]["verification_error"] = f"{type(exc).__name__}: {exc}"
        if uvc is not None:
            try:
                report["controls_after"] = read_controls(uvc)
            except Exception as exc:
                report["restoration"]["get_cur_error"] = str(exc)
            uvc.close()
        if device is not None:
            device.close()
        checks = {
            "controls": report.get("controls_after") == original.get("controls"),
            "ram": report.get("ram_restored") is True,
            "eeprom": report.get("eeprom_unchanged") is True
                      and report.get("eeprom_sha256_after") == original.get("eeprom_sha256"),
        }
        report["restoration"]["checks"] = checks
        report["restoration"]["all_ok"] = all(checks.values())
        if failure:
            report["probe_failure"] = failure
        result_path.write_text(json.dumps(report, indent=2) + "\n")
        print("\nRESTORATION " + json.dumps(report["restoration"], sort_keys=True), flush=True)
    if failure or not report["restoration"]["all_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
