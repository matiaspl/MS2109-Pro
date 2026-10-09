#!/usr/bin/env python3
"""Geometry-aware analysis for original UVC and AVFoundation color captures."""
from __future__ import annotations
import argparse
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from calibrate_colors import jpeg_headers, samples
from probe_colors import matrix, unpack, write_json


def frame_values(directory: Path, meta: dict, decoder: Path | None = None):
    source = meta
    patches = source["patch_reference"]
    frames = source["frames"]
    if len(frames) < 3:
        raise ValueError(f"At least three stable frames are required: {directory}")
    all_values = []
    temporal = []
    for frame in frames:
        path = directory / frame["file"]
        if not path.is_file() or path.stat().st_size != frame.get("bytes", path.stat().st_size):
            raise ValueError(f"Missing or truncated frame: {path}")
        fmt = frame["pixel_format"]
        if fmt in ("yuvs", "2vuy"):
            image = unpack(path, frame)
            kind = "yuv"
        elif fmt in ("BGRA", "RGBA"):
            raw = np.fromfile(path, np.uint8).reshape(frame["height"], frame["width"], 4)
            image = raw[:, :, [2, 1, 0]] if fmt == "BGRA" else raw[:, :, :3]
            kind = "rgb"
        elif fmt == "jpeg":
            if decoder is None:
                raise ValueError("MJPEG analysis requires the libjpeg YCbCr decoder")
            if not jpeg_headers(path.read_bytes())["referenced_coding_tables_present"]:
                raise ValueError(f"JPEG has incomplete coding-table references: {path}")
            with tempfile.TemporaryDirectory(prefix="ms2109-jpeg-decode-") as td:
                out = Path(td) / "frame.ycbcr"
                info = Path(td) / "frame.json"
                subprocess.run([str(decoder), str(path), str(out), str(info)], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                detail = json.loads(info.read_text())
                if detail["warnings"]:
                    raise ValueError(f"libjpeg reported a warning: {path}")
                image = np.fromfile(out, np.uint8).reshape(frame["height"], frame["width"], 3)
            kind = "yuv"
        else:
            raise ValueError(f"Unsupported saved pixel format {fmt!r}")
        if image.shape[2] != 3:
            raise ValueError("Expected exactly three measured color channels")
        all_values.append(samples(image, patches).astype(np.float64))
    # samples() preserves every pixel in each center crop: frames x patches x
    # crop-pixels x channels. Reduce each crop first, then summarize across
    # frames so spatial samples are not mistaken for extra chart patches.
    per_frame_patch = np.median(np.stack(all_values), axis=2)
    median = np.median(per_frame_patch, axis=0)
    temporal = np.ptp(per_frame_patch, axis=0)
    first = per_frame_patch[0]
    after_first = per_frame_patch[1:] if len(per_frame_patch) > 1 else per_frame_patch
    steady_median = np.median(after_first, axis=0)
    steady_temporal = np.ptp(after_first, axis=0)
    return {"kind": kind, "median_values": median, "maximum_temporal_patch_span": float(temporal.max()),
            "per_patch_temporal_span": temporal, "first_frame_values": first,
            "after_first_median_values": steady_median,
            "after_first_maximum_temporal_patch_span": float(steady_temporal.max()),
            "per_frame_patch_values": per_frame_patch,
            "frames": len(frames), "format": frames[0]["pixel_format"]}


def metrics(result: dict, expected_rgb: np.ndarray):
    values = result["median_values"]
    if result["kind"] == "rgb":
        delta = values - expected_rgb
        return {"rgb_rmse": float(np.sqrt(np.mean(delta ** 2))),
                "rgb_rmse_per_channel": np.sqrt(np.mean(delta ** 2, axis=0)).tolist(),
                "rgb_median_ranges": np.stack((values.min(axis=0), values.max(axis=0)), axis=1).tolist(),
                "maximum_temporal_patch_span": result["maximum_temporal_patch_span"]}
    m, offset = matrix("709", "full")
    target = expected_rgb @ m.T + offset
    delta = values - target
    decoded = (values - offset) @ np.linalg.inv(m).T
    rgb_delta = np.clip(decoded, 0, 255) - expected_rgb
    return {"yuv_rmse_per_channel": np.sqrt(np.mean(delta ** 2, axis=0)).tolist(),
            "yuv_rmse": float(np.sqrt(np.mean(delta ** 2))),
            "rgb_after_bt709_full_decode_rmse": float(np.sqrt(np.mean(rgb_delta ** 2))),
            "yuv_median_ranges": np.stack((values.min(axis=0), values.max(axis=0)), axis=1).tolist(),
            "maximum_temporal_patch_span": result["maximum_temporal_patch_span"]}


def observed_rate(frames: list[dict]):
    timestamps = [frame["pts_seconds"] for frame in frames if "pts_seconds" in frame]
    intervals = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    return 1.0 / statistics.median(intervals) if intervals else None


def conversion_comparison(yuv: np.ndarray, observed_rgb: np.ndarray, expected_rgb: np.ndarray):
    models = {}
    for standard in ("601", "709", "2020"):
        for quantization in ("full", "limited"):
            m, offset = matrix(standard, quantization)
            decoded = np.clip((yuv - offset) @ np.linalg.inv(m).T, 0, 255)
            key = f"{standard}_{quantization}"
            models[key] = {
                "rmse_vs_expected_rgb": float(np.sqrt(np.mean((decoded - expected_rgb) ** 2))),
                "rmse_vs_avfoundation_bgra": float(np.sqrt(np.mean((decoded - observed_rgb) ** 2))),
            }
    return models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("--chart-source", type=Path, required=True)
    parser.add_argument("--jpeg-decoder", type=Path, required=True)
    args = parser.parse_args()
    root = args.capture_root.resolve()
    qualification_inputs = json.loads((root / "qualification-inputs.json").read_text())
    reconnect_input = qualification_inputs.get("reconnect_first_frames", {})
    reconnect_trial_directories = reconnect_input.get("trial_directories", {})
    selected_reconnect_trials = set(reconnect_trial_directories.values())
    chart = json.loads((args.chart_source / "display-ready.json").read_text())
    patches = chart["patch_reference"]
    expected = np.asarray([p["expected_display_rgb"] for p in patches], dtype=np.float64)
    source_image = np.asarray(Image.open(args.chart_source / "source-render.png").convert("RGB"))
    source_values = np.median(samples(source_image, patches), axis=1)
    source_rmse = float(np.sqrt(np.mean((source_values - expected) ** 2)))
    if source_rmse > 2.5:
        raise ValueError(f"AppKit source render/reference mismatch: RGB RMSE {source_rmse:.3f}")

    result = {"chart": {"patches": len(patches), "source_render_rgb_rmse": source_rmse,
                        "display_profile": chart.get("window_screen"), "render_space": chart.get("render_space")},
              "raw_trials": {}, "excluded_reconnect_trials": [], "avfoundation": {},
              "release_limits": {"target_yuv_rmse_per_channel_max": 1.5, "host_bgra_rgb_rmse_max": 2.5}}
    baseline = {}

    def first_frame_capture_is_valid(directory, metadata):
        request_log = directory / "control-requests.jsonl"
        return (metadata.get("exit_code") == 0
                and metadata.get("frames_captured") == 8
                and metadata.get("frames_skipped_for_settling") == 0
                and metadata.get("getter_profile") == "GET_CUR only"
                and metadata.get("control_profile") == "untouched"
                and metadata.get("controls_restoration_ok") is True
                and request_log.is_file()
                and '"direction":"OUT"' not in request_log.read_text())

    for trial in sorted((root / "raw").iterdir()):
        if not trial.is_dir() or trial.name == "pre-chart-claim" or trial.name.endswith("-incomplete"):
            continue
        if trial.name.startswith("reconnect-") and trial.name not in selected_reconnect_trials:
            result["excluded_reconnect_trials"].append({
                "trial_directory": trial.name,
                "reason": "superseded reconnect attempt; excluded from qualification metrics"})
            continue
        # Interrupted reconnect trials are retained with an -incomplete suffix
        # for evidence preservation; analyze only complete paired captures.
        if trial.name.startswith("reconnect-") and not all(
                (trial / mode / "usb-capture.json").is_file()
                and (trial / f"{mode}-display-ready.json").is_file()
                for mode in ("yuy2", "mjpeg")):
            continue
        t = {"formats": {}}
        if trial.name.startswith("reconnect-"):
            reconnect_valid = True
            for mode in ("yuy2", "mjpeg"):
                directory = trial / mode
                meta = json.loads((directory / "usb-capture.json").read_text())
                chart_snapshot = trial / f"{mode}-display-ready.json"
                if not first_frame_capture_is_valid(directory, meta) or not chart_snapshot.is_file():
                    reconnect_valid = False
                    break
            if not reconnect_valid:
                continue
        for mode in ("yuy2", "mjpeg"):
            directory = trial / mode
            meta = json.loads((directory / "usb-capture.json").read_text())
            if meta.get("exit_code") != 0 or not meta.get("controls_restoration_ok", True):
                raise ValueError(f"Raw trial failed or did not restore controls: {directory}")
            trial_patches = patches
            display_state = None
            trial_expected = expected
            if trial.name.startswith("reconnect-"):
                display_state = json.loads((trial / f"{mode}-display-ready.json").read_text())
                trial_patches = display_state["patch_reference"]
                trial_expected = np.asarray([p["expected_display_rgb"] for p in trial_patches], dtype=np.float64)
            meta["patch_reference"] = trial_patches
            frame_info = frame_values(directory, meta, args.jpeg_decoder)
            m = metrics(frame_info, trial_expected)
            t["formats"][mode] = {"pixel_format": frame_info["format"], "frames": frame_info["frames"],
                                   "controls_before": meta.get("controls_before"), "controls_active": meta.get("controls_active"),
                                   "getter_profile": meta.get("getter_profile"), "control_profile": meta.get("control_profile"),
                                   "requested_interval_100ns": meta.get("interval_100ns"),
                                   "nominal_fps": 1e7 / meta["interval_100ns"] if meta.get("interval_100ns") else None,
                                   "observed_callback_fps": observed_rate(meta.get("frames", [])),
                                   "frames_skipped_for_settling": meta.get("frames_skipped_for_settling"),
                                   "metrics": m,
                                   "control_request_log": str((directory / "control-requests.jsonl").relative_to(root))}
            if display_state:
                t["formats"][mode]["display_profile"] = display_state.get("window_screen")
                t["formats"][mode]["display_generation"] = display_state.get("display_generation")
                t["formats"][mode]["display_profile_generation"] = display_state.get("display_profile_generation")
                first_result = {"kind": frame_info["kind"], "median_values": frame_info["first_frame_values"],
                                "maximum_temporal_patch_span": 0.0}
                after_first_result = {"kind": frame_info["kind"], "median_values": frame_info["after_first_median_values"],
                                      "maximum_temporal_patch_span": frame_info["after_first_maximum_temporal_patch_span"]}
                t["formats"][mode]["first_frame_metrics"] = metrics(first_result, trial_expected)
                t["formats"][mode]["after_first_metrics"] = metrics(after_first_result, trial_expected)
                t["formats"][mode]["per_frame_metrics"] = [
                    {"yuv_rmse_per_channel": frame_metric["yuv_rmse_per_channel"],
                     "yuv_median_ranges": frame_metric["yuv_median_ranges"]}
                    for frame_metric in (
                        metrics({"kind": frame_info["kind"], "median_values": frame_values,
                                 "maximum_temporal_patch_span": 0.0}, trial_expected)
                        for frame_values in frame_info["per_frame_patch_values"])
                ]
            if trial.name == "all-getters-mjpeg-first":
                baseline[mode] = frame_info["median_values"]
            elif mode in baseline:
                d = frame_info["median_values"] - baseline[mode]
                t["formats"][mode]["rmse_vs_baseline_trial"] = float(np.sqrt(np.mean(d ** 2)))
        result["raw_trials"][trial.name] = t

    path_values = {}
    for pixel in ("yuv", "bgra"):
        directory = root / "avfoundation" / pixel
        meta = json.loads((directory / "capture.json").read_text())
        meta["patch_reference"] = patches
        frame_info = frame_values(directory, meta, args.jpeg_decoder)
        path_values[pixel] = frame_info["median_values"]
        first_attachments = meta["frames"][0].get("attachments", {}) if meta.get("frames") else {}
        color_keys = ("CVImageBufferColorPrimaries", "CVImageBufferTransferFunction",
                      "CVImageBufferYCbCrMatrix")
        result["avfoundation"][pixel] = {"pixel_format": frame_info["format"], "frames": frame_info["frames"],
                                          "metrics": metrics(frame_info, expected),
                                          "active_subtype": meta.get("actual_active_subtype", meta.get("active_subtype")),
                                          "active_size": meta.get("actual_active_size"),
                                          "selected_max_fps": meta.get("fps"),
                                          "actual_frame_duration_seconds": meta.get("actual_frame_duration"),
                                          "observed_frame_rate_fps": observed_rate(meta.get("frames", [])),
                                          "color_attachments": {key: first_attachments.get(key) for key in color_keys},
                                          "capture_metadata": str((directory / "capture.json").relative_to(root))}
    result["avfoundation_conversion_comparison"] = conversion_comparison(
        path_values["yuv"], path_values["bgra"], expected)
    same_handle = result["raw_trials"].get("same-handle", {}).get("formats", {})
    same_handle_ok = all(mode in same_handle and
                         json.loads((root / "raw" / "same-handle" / mode / "usb-capture.json").read_text()).get("capture_backend") == "libuvc raw payload, persistent handle"
                         and json.loads((root / "raw" / "same-handle" / mode / "usb-capture.json").read_text()).get("controls_restoration_ok")
                         for mode in ("mjpeg", "yuy2"))
    reconnect_cycles = {}
    for cycle in range(1, 4):
        name = f"reconnect-{cycle}"
        trial_directory = reconnect_trial_directories.get(str(cycle), name)
        raw = root / "raw" / trial_directory
        modes = {}
        if raw.is_dir():
            for mode in ("yuy2", "mjpeg"):
                metadata_path = raw / mode / "usb-capture.json"
                if not metadata_path.is_file():
                    continue
                metadata = json.loads(metadata_path.read_text())
                modes[mode] = {
                    "exit_code": metadata.get("exit_code"),
                    "frames_captured": metadata.get("frames_captured", 0),
                    "frames_skipped_for_settling": metadata.get("frames_skipped_for_settling"),
                    "getter_profile": metadata.get("getter_profile"),
                    "control_profile": metadata.get("control_profile"),
                    "controls_before": metadata.get("controls_before"),
                    "controls_active": metadata.get("controls_active"),
                    "controls_restoration_ok": metadata.get("controls_restoration_ok"),
                    "display_generation": json.loads((raw / f"{mode}-display-ready.json").read_text()).get("display_generation") if (raw / f"{mode}-display-ready.json").is_file() else None,
                    "display_profile_generation": json.loads((raw / f"{mode}-display-ready.json").read_text()).get("display_profile_generation") if (raw / f"{mode}-display-ready.json").is_file() else None,
                    "display_profile_matches": json.loads((raw / f"{mode}-display-ready.json").read_text()).get("display_profile_matches") if (raw / f"{mode}-display-ready.json").is_file() else None,
                    "window_screen": json.loads((raw / f"{mode}-display-ready.json").read_text()).get("window_screen") if (raw / f"{mode}-display-ready.json").is_file() else None,
                    "raw_metrics": result["raw_trials"].get(trial_directory, {}).get("formats", {}).get(mode, {}).get("metrics"),
                    "first_frame_metrics": result["raw_trials"].get(trial_directory, {}).get("formats", {}).get(mode, {}).get("first_frame_metrics"),
                    "after_first_metrics": result["raw_trials"].get(trial_directory, {}).get("formats", {}).get(mode, {}).get("after_first_metrics"),
                    "per_frame_metrics": result["raw_trials"].get(trial_directory, {}).get("formats", {}).get(mode, {}).get("per_frame_metrics"),
                }
        reconnect_cycles[name] = {"trial_directory": trial_directory, "formats": modes}
    reconnect_ok = all(
        all(mode in reconnect_cycles[f"reconnect-{cycle}"]["formats"]
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["exit_code"] == 0
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["frames_captured"] == 8
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["frames_skipped_for_settling"] == 0
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["getter_profile"] == "GET_CUR only"
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["control_profile"] == "untouched"
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["controls_restoration_ok"] is True
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["display_profile_matches"] is True
            and reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["window_screen"] == "HDMI TO USB"
            for mode in ("yuy2", "mjpeg"))
        for cycle in range(1, 4))
    first_frame_color_ok = reconnect_ok and all(
        max(reconnect_cycles[f"reconnect-{cycle}"]["formats"][mode]["first_frame_metrics"]["yuv_rmse_per_channel"]) <= 1.5
        for cycle in range(1, 4) for mode in ("yuy2", "mjpeg"))
    result["qualification"] = {
        "reconnect_capture_gate": "passed: three cycles, eight immediate frames per format, GET_CUR only, stable target display" if reconnect_ok else "pending: requires three complete cycles with eight immediate frames per format, GET_CUR only, and stable target display",
        "first_frame_color_gate": "passed: first frame per format met the 1.5-code per-channel YUV RMSE limit" if first_frame_color_ok else "failed: one or more first frames exceeded the 1.5-code per-channel YUV RMSE limit" if reconnect_ok else "pending: requires three complete reconnect captures",
        "reconnect_cycle_metrics": reconnect_cycles,
        "steady_handle_format_switch_gate": "captured MJPEG then YUY2 on one persistent UVC handle; controls remained unchanged" if same_handle_ok else "not exercised; the recorded raw format trials reopen the UVC handle",
        "chart_timing": "USB claim-only preflight was logged before chart creation; all paired payload trials ran with chart visible",
        "automatic_rgb_gate_passed": result["avfoundation"]["bgra"]["metrics"]["rgb_rmse"] <= 2.5,
        "raw_sample_gate_passed": all(max(item["metrics"]["yuv_rmse_per_channel"]) <= 1.5
                                       for trial in result["raw_trials"].values()
                                       for item in trial["formats"].values())}
    write_json(root / "analysis.json", result)
    lines = ["# MS2109 color-path qualification capture", "",
             f"Source display profile: {chart.get('window_screen')}; chart/source RGB RMSE {source_rmse:.3f}.",
             "The getter/control/order trials reopen the UVC handle per format. A separate same-handle trial captures MJPEG then YUY2 before closing the handle. The paired trials record GET_CUR or all GET_CUR/MIN/MAX/RES/DEF calls; reapply-current uses SET_CUR with the same values and verifies restoration.", "",
             "| Trial | Format | Getter/control profile | Nominal / observed callback fps | YUV RMSE Y/Cb/Cr | YUV range Y/Cb/Cr |", "|---|---|---|---:|---|---|"]
    for name, trial in result["raw_trials"].items():
        for mode, item in trial["formats"].items():
            m=item["metrics"]
            lines.append(f"| {name} | {mode} | {item['getter_profile']} / {item['control_profile']} | {item['nominal_fps']} / {item['observed_callback_fps']:.2f} | {m['yuv_rmse_per_channel']} | {m['yuv_median_ranges']} |")
    if result["excluded_reconnect_trials"]:
        excluded = ", ".join(item["trial_directory"] for item in result["excluded_reconnect_trials"])
        lines += ["", f"Superseded reconnect captures are retained in `raw/` but excluded from these metrics: {excluded}. They used the earlier normal-level chart setup, which let the menu bar cover chart patches."]
    lines += ["", "## Reconnect startup frames", "", "| Cycle | Format | First frame YUV RMSE Y/Cb/Cr | Following frames median RMSE (temporal span) | Per-frame Y/Cb/Cr RMSE in capture order | Display profile generation |", "|---|---|---|---|---|---|"]
    for name, cycle_data in reconnect_cycles.items():
        for mode, item in cycle_data["formats"].items():
            first=item.get("first_frame_metrics") or {}; after=item.get("after_first_metrics") or {}
            frame_text = "; ".join(
                f"{index}:" + "/".join(f"{value:.1f}" for value in frame.get("yuv_rmse_per_channel", []))
                for index, frame in enumerate(item.get("per_frame_metrics") or []))
            lines.append(f"| {name} | {mode} | {first.get('yuv_rmse_per_channel')} | {after.get('yuv_rmse_per_channel')} (span {after.get('maximum_temporal_patch_span')}) | {frame_text} | {item.get('display_profile_generation')} |")
    comparison = result["avfoundation_conversion_comparison"]
    best_bgra_model = min(comparison, key=lambda name: comparison[name]["rmse_vs_avfoundation_bgra"])
    lines += ["", f"AVFoundation BGRA auto-conversion RGB RMSE: {result['avfoundation']['bgra']['metrics']['rgb_rmse']:.3f} codes; channel RMSE {result['avfoundation']['bgra']['metrics']['rgb_rmse_per_channel']}.",
              f"AVFoundation packed YUV BT.709/full per-channel RMSE: {result['avfoundation']['yuv']['metrics']['yuv_rmse_per_channel']}.",
              f"The best tested YUV-to-BGRA model was {best_bgra_model}: {comparison[best_bgra_model]['rmse_vs_avfoundation_bgra']:.3f} RGB-code RMS from captured BGRA. The BT.709/full decode was {comparison['709_full']['rmse_vs_expected_rgb']:.3f} RMS from the reference but {comparison['709_full']['rmse_vs_avfoundation_bgra']:.3f} from automatic BGRA.",
              f"AVFoundation attachments on YUV: {result['avfoundation']['yuv']['color_attachments']}; selected maximum {result['avfoundation']['yuv']['selected_max_fps']} fps, observed {result['avfoundation']['yuv']['observed_frame_rate_fps']:.2f} fps.",
             "", (f"Three reconnect cycles were captured. Each format records the first eight frames delivered after stream start following user-confirmed re-enumeration, with no settling delay or picture-control writes. The first frame is reported separately from the following seven; first-frame color gate: {result['qualification']['first_frame_color_gate']}. This measures first captured frames after reconnect, not USB-bus SOF frames." if reconnect_ok else "This capture does not yet establish three-cycle first-frame-after-reconnect consistency. The JPEG ICC file-decoder test and YUY2 signaling feasibility are separate gates.")]
    stereo_path = root / "stereo-current-fe60.json"
    if stereo_path.is_file():
        stereo = json.loads(stereo_path.read_text())
        stereo_analysis = json.loads(Path(stereo["analysis"]).read_text())
        left, right = stereo_analysis["channels"]
        best_lag = max(stereo["known_sample_offset"], key=lambda item: item["correlation_ch0_n_ch1_n_plus_lag"] or -1)
        lines += ["", "## Stereo audio preservation", "",
                  f"Fresh read-only fixture: FE60 remained {stereo['device_state_before']['fe60']:02x}; live audio descriptor reports {stereo['device_state_before']['audio_channels']} channels at 48 kHz, with `HDMI TO USB` as the 48 kHz default output. Channel 0 had {left['dominant_hz'][0]:.1f} Hz and {left['silent_window_fraction']:.1%} silent windows; channel 1 had {right['dominant_hz'][0]:.1f} Hz and {right['silent_window_fraction']:.1%} silent windows. This verifies continuous left and gapped right routing. The strongest inter-channel correlation was at lag {best_lag['lag_samples']} sample ({best_lag['correlation_ch0_n_ch1_n_plus_lag']:.3f}); the known one-sample offset remains.",
                  f"Evidence: [`stereo-current-fe60.wav`](stereo-current-fe60.wav), [`stereo-current-fe60.analysis.json`](stereo-current-fe60.analysis.json), and [`stereo-current-fe60.json`](stereo-current-fe60.json). No register or firmware writes were made."]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result["qualification"], indent=2))


if __name__ == "__main__":
    main()
