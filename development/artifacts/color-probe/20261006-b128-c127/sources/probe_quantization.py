#!/usr/bin/env python3
"""Generate and analyze every 8-bit RGB primary/gray ramp level.

This file-only tool does not change controls or open hardware. Original USB
captures and AVFoundation captures are discovered in the supplied run directory.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from PIL import Image
from probe_colors import ROOT, matrix, decode, unpack, rmse, write_json

GROUPS = ["gray", "red", "green", "blue"]


def chart():
    patches = []
    for group in GROUPS:
        for code in range(256):
            rgb = [code]*3 if group == "gray" else [code if group == c else 0 for c in GROUPS[1:]]
            i = len(patches); row = i // 32
            y, bottom = row*1080//32, (row+1)*1080//32
            patches.append({"name": f"{group}-{code}", "group": group, "code": code,
                            "rgb": rgb, "rect": [i % 32*60, y, 60, bottom-y]})
    return {"width": 1920, "height": 1080, "columns": 32, "rows": 32, "sample_size": 8,
            "coverage": "Every code 0..255 on gray and each RGB primary ramp; not exhaustive RGB triplets",
            "patches": patches}


def roi(image, patch):
    x, y, w, h = patch["rect"]
    cx, cy = x+w//2, y+h//2
    return image[cy-4:cy+4, cx-4:cx+4].reshape(64, 3)


def plateaus(values):
    output = []
    start = 0
    for i in range(1, 257):
        if i == 256 or not np.array_equal(values[i], values[start]):
            if i-start > 1:
                output.append({"first_input": start, "last_input": i-1, "output": values[start].tolist()})
            start = i
    return output


def metrics(values):
    delta = np.diff(values, axis=0)
    return {"black_end": values[0].tolist(), "full_end": values[-1].tolist(),
            "unique_median_triplets": int(len(np.unique(values, axis=0))),
            "unique_median_codes_per_component": [int(len(np.unique(values[:, c]))) for c in range(3)],
            "unchanged_adjacent_input_pairs": int(np.sum(np.all(delta == 0, axis=1))),
            "plateaus": plateaus(values),
            "steps_per_component": [{str(float(v)): int(n) for v, n in zip(*np.unique(delta[:, c], return_counts=True))} for c in range(3)]}


def analyze(args):
    run = args.run.resolve(); out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((run / "pattern.json").read_text())
    if manifest != chart():
        raise ValueError("Manifest is not the complete 1024-patch quantization chart")
    datasets = []
    for path in sorted(run.glob("avf-*/capture.json")):
        meta = json.loads(path.read_text())
        profile = "ui128c127" if "ui128c127" in path.parent.name else "ui127" if "ui127" in path.parent.name else "current"
        datasets.append((path.parent.name, path.parent, meta, meta, profile, False))
    for path in sorted(run.glob("usb/*/*/usb-capture.json")):
        meta = json.loads(path.read_text())
        source = json.loads((run / "usb-source/display-ready.json").read_text())
        profile = path.parent.parent.name
        datasets.append((f"usb-{profile}-{meta['mode']}", path.parent, meta, source, profile, True))
    if not datasets:
        raise ValueError("No completed recordings found")
    summaries = {}; measured = {}; first = {}
    histograms = {}
    with tempfile.TemporaryDirectory(prefix="ms2109-quantization-decode-") as tmp:
        tmp = Path(tmp); binary = tmp / "decode"
        if any(d[-1] and d[2]["mode"] == "mjpeg" for d in datasets):
            subprocess.run(["clang", "-I/opt/homebrew/include", "-L/opt/homebrew/lib",
                            str(ROOT / "tools/decode_jpeg_ycbcr.c"), "-ljpeg", "-o", str(binary)], check=True)
        for name, directory, meta, source, profile, usb in datasets:
            frames = meta["frames"]
            if len(frames) != 8 or meta.get("exit_code", 0) or meta.get("error"):
                raise ValueError(f"Incomplete recording: {name}")
            if usb and not meta["controls_restoration_ok"]:
                raise ValueError(f"Control restoration failed: {name}")
            patches = source["patch_reference"]
            if [(p["rgb"], p["rect"]) for p in patches] != [(p["rgb"], p["rect"]) for p in manifest["patches"]]:
                raise ValueError("Captured reference differs from chart")
            rgb = np.array([p["expected_display_rgb"] for p in patches], float)
            source_dir = run / "usb-source" if usb else directory
            source_image = np.array(Image.open(source_dir / "source-render.png").convert("RGB"))
            source_error = rmse(np.array([np.median(roi(source_image, p), axis=0) for p in patches]), rgb)
            if source_error > .5:
                raise ValueError(f"Source render mismatch: {name} {source_error}")
            per_frame = []; pixel_samples = []; jpeg_info = []
            for i, frame in enumerate(frames):
                if frame["width"] != 1920 or frame["height"] != 1080:
                    raise ValueError("Unexpected frame size")
                path = directory / frame["file"]
                if usb and meta["mode"] == "mjpeg":
                    payload = path.read_bytes()
                    if len(payload) != frame["bytes"] or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
                        raise ValueError("Original JPEG payload validation failed")
                    decoded, info = tmp / f"{i}.ycbcr", tmp / f"{i}.json"
                    subprocess.run([str(binary), str(path), str(decoded), str(info)], check=True)
                    details = json.loads(info.read_text())
                    if details["warnings"]:
                        raise ValueError("JPEG decoder warning")
                    jpeg_info.append(details)
                    image = np.fromfile(decoded, np.uint8).reshape(1080, 1920, 3)
                    decoded.unlink(); info.unlink()
                else:
                    image = unpack(path, frame)
                regions = np.stack([roi(image, p) for p in patches])
                per_frame.append(np.median(regions, axis=1)); pixel_samples.append(regions)
                if i == 0:
                    first[name] = image
            pixels = np.concatenate(pixel_samples, axis=1)
            values = np.median(per_frame, axis=0)
            measured[name] = values
            temporal = np.ptp(per_frame, axis=0)
            # Validate ramp presence before interpreting its quantization.
            gray = values[:256]
            if gray[-1, 0]-gray[0, 0] < 100 or np.corrcoef(np.arange(256), gray[:, 0])[0, 1] < .99:
                raise ValueError(f"Captured content is not the chart: {name}")
            reconstructed = decode(values, "709", "limited")
            ramps = {}
            for g, group in enumerate(GROUPS):
                section = slice(g*256, (g+1)*256)
                v = values[section]; r = reconstructed[section]
                index = max(0, g-1)
                slope, offset = np.linalg.lstsq(np.c_[np.arange(256), np.ones(256)], v[:, 0], rcond=None)[0]
                ramps[group] = {"yuv": metrics(v), "reconstructed_rgb_709_limited": metrics(np.rint(np.clip(r, 0, 255))),
                    "unique_patch_mean_triplets": int(len(np.unique(np.mean(pixels[section], axis=1), axis=0))),
                    "unique_pixel_distribution_signatures": len({json.dumps([{str(int(code)): int(count) for code,count in zip(*np.unique(pixel[:,c],return_counts=True))} for c in range(3)],sort_keys=True) for pixel in pixels[section]}),
                    "reconstructed_active_channel": r[:, index].tolist(),
                    "y_fit_slope": float(slope), "y_fit_offset": float(offset),
                    "maximum_temporal_patch_span": float(temporal[section].max()),
                    "maximum_pixel_span": float(np.ptp(pixels[section], axis=1).max()),
                    "unique_raw_codes_per_component": [int(len(np.unique(pixels[section, :, c]))) for c in range(3)]}
            model_results = []
            for mname in ["601", "709", "2020"]:
                for quantization in ["limited", "full"]:
                    m, offset = matrix(mname, quantization)
                    model_results.append({"matrix": mname, "range": quantization, "direct_yuv_rmse": rmse(rgb @ m.T + offset, values)})
            summaries[name] = {"directory": str(directory.relative_to(ROOT)), "control_profile": profile,
                "capture_backend": meta.get("capture_backend", "AVFoundation delivered YUV"),
                "delivered_pixel_format": frames[0]["pixel_format"], "frame_count": len(frames), "patch_count": len(patches),
                "sample_pixels_per_patch": pixels.shape[1], "source_render_rgb_rmse": source_error,
                "controls_active": meta.get("controls_active", meta.get("controls_snapshot")),
                "controls_restoration_ok": meta.get("controls_restoration_ok"), "jpeg_decoder": jpeg_info,
                "models": sorted(model_results, key=lambda x: x["direct_yuv_rmse"]), "ramps": ramps}
            histograms[name] = [{"name": p["name"], "median_yuv": values[i].tolist(),
                "mean_yuv": np.mean(pixels[i], axis=0).tolist(),
                "channel_histograms": [{str(int(v)): int(n) for v, n in zip(*np.unique(pixels[i, :, c], return_counts=True))} for c in range(3)]} for i, p in enumerate(patches)]
            with (out / f"{name}.csv").open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["ramp", "input_code", "source_R", "source_G", "source_B", "median_Y", "median_Cb", "median_Cr", "inverse709_R", "inverse709_G", "inverse709_B"])
                for i, patch in enumerate(patches):
                    writer.writerow([patch["group"], patch["code"], *rgb[i], *values[i], *reconstructed[i]])
    scale = np.array([219/255, 224/255, 224/255]); offset = np.array([16, 128, 128])-np.array([0, 128, 128])*scale
    comparisons = {}
    for profile in sorted({dataset[4] for dataset in datasets}):
        n, j, a, d = [f"usb-{profile}-{f}" for f in ["yuy2", "mjpeg"]] + [f"avf-{profile}-{f}" for f in ["yuy2", "decoded"]]
        compare = {}
        if n in measured and j in measured:compare["usb_jpeg_vs_yuy2_yuv_rmse"] = rmse(measured[n], measured[j])
        if a in measured and n in measured:compare["avf_yuy2_vs_usb_yuy2_yuv_rmse"] = rmse(measured[a], measured[n])
        raw = j if j in measured else a
        if d in measured and raw in measured:
            compare["avf_decoded_vs_reference"] = raw
            compare["avf_decoded_identity_rmse"] = rmse(measured[d], measured[raw])
            compare["avf_decoded_extra_full_to_limited_rmse"] = rmse(measured[d], measured[raw]*scale+offset)
        if compare:comparisons[profile] = compare
    result = {"coverage": manifest["coverage"], "roi_size": [8, 8], "datasets": summaries, "comparisons": comparisons}
    write_json(out / "analysis.json", result); write_json(out / "histograms.json", histograms)
    plot_data = {name: {group: {"yuv": values[g*256:(g+1)*256].tolist(),
                         "rgb709": decode(values[g*256:(g+1)*256], "709", "limited").tolist()} for g, group in enumerate(GROUPS)} for name, values in measured.items()}
    write_json(out / "plot-data.json", plot_data)
    lines = ["# Measured 8-bit quantization ramps", "", manifest["coverage"], "",
             "Central 8×8 pixels from eight frames give 512 pixel samples per input code. Counts below describe these ramps, not effective bit depth over arbitrary RGB combinations.", "",
             "| Capture | Ramp | Median endpoints Y/Cb/Cr | Unique median YUV triplets | Unique patch-mean triplets | Unique raw pixel codes Y/Cb/Cr | Adjacent equal medians |",
             "|---|---|---|---:|---:|---|---:|"]
    for name, summary in summaries.items():
        for group, ramp in summary["ramps"].items():
            v = ramp["yuv"]
            lines.append(f"| {name} | {group} | {v['black_end']} → {v['full_end']} | {v['unique_median_triplets']} | {ramp['unique_patch_mean_triplets']} | {ramp['unique_raw_codes_per_component']} | {v['unchanged_adjacent_input_pairs']} |")
    lines += ["", "Full pixel-code histograms: [histograms.json](histograms.json). Each capture has a CSV containing all 256 levels on each ramp. YUV samples and explicit reconstructed RGB are retained separately.", "", "The RGB reference is the AppKit source render in the active display profile, before late compositor/HDMI processing. JPEG decompression uses YCbCr output with no RGB matrix or range conversion."]
    (out / "report.md").write_text("\n".join(lines)+"\n")
    write_json(out / "sha256.json", {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()})
    print(json.dumps({"comparisons": comparisons, "ramps": {name: {g: {k: r['yuv'][k] for k in ['black_end','full_end','unique_median_codes_per_component','unique_median_triplets','unchanged_adjacent_input_pairs']} for g,r in s['ramps'].items()} for name,s in summaries.items()}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("chart"); generate.add_argument("output", type=Path)
    analyze_parser = sub.add_parser("analyze"); analyze_parser.add_argument("run", type=Path); analyze_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "chart":
        if args.output.exists():raise ValueError("Refusing to overwrite existing manifest")
        write_json(args.output, chart())
    else:analyze(args)
