#!/usr/bin/env python3
"""Compare original MS2109 USB YUY2/JPEG samples with AVFoundation output.

Acquisition is separate. This analyzer opens only saved files, builds the local
libjpeg helper, and decodes JPEG to YCbCr without an RGB matrix/range conversion.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from probe_colors import ROOT, MATRICES, matrix, decode, unpack, patch_samples, rmse, save_rgb, write_json


def models(samples, rgb):
    results = []
    for name in MATRICES:
        for quantization in ["limited", "full"]:
            m, offset = matrix(name, quantization)
            results.append({"matrix": name, "range": quantization,
                            "direct_yuv_rmse": rmse(rgb @ m.T + offset, samples),
                            "rgb_rmse": rmse(decode(samples, name, quantization), rgb)})
    return sorted(results, key=lambda x: x["direct_yuv_rmse"])


def run(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = json.loads((args.source / "display-ready.json").read_text())
    patches = source["patch_reference"]
    rgb = np.array([p["expected_display_rgb"] for p in patches], float)
    source_image = np.array(Image.open(args.source / "source-render.png").convert("RGB"))
    source_error = rmse(patch_samples(source_image, patches)[0], rgb)
    if source_error > 2:
        raise ValueError("Source render does not agree with reference")
    decoder_meta = []
    samples = {}
    first_images = {}
    summaries = {}
    with tempfile.TemporaryDirectory(prefix="ms2109-jpeg-samples-") as temporary:
        temporary = Path(temporary)
        binary = temporary / "decode"
        subprocess.run(["clang", "-Wall", "-Wextra", "-I/opt/homebrew/include", "-L/opt/homebrew/lib",
                        str(ROOT / "tools/decode_jpeg_ycbcr.c"), "-ljpeg", "-o", str(binary)], check=True)
        for mode in ["yuy2", "mjpeg"]:
            directory = args.usb / mode
            meta = json.loads((directory / "usb-capture.json").read_text())
            if meta["exit_code"] or len(meta["frames"]) != 8:
                raise ValueError("Incomplete original USB recording")
            values, spreads = [], []
            for i, frame in enumerate(meta["frames"]):
                path = directory / frame["file"]
                if path.stat().st_size != frame["bytes"]:
                    raise ValueError("Frame size differs from acquisition metadata")
                if mode == "yuy2":
                    image = unpack(path, frame)
                else:
                    payload = path.read_bytes()
                    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
                        raise ValueError("JPEG payload lacks SOI/EOI markers")
                    decoded = out / "mjpeg-first-frame.ycbcr" if i == 0 else temporary / f"frame-{i}.ycbcr"
                    info_path = out / f"mjpeg-decoder-{i:03}.json"
                    subprocess.run([str(binary), str(path), str(decoded), str(info_path)], check=True)
                    info = json.loads(info_path.read_text())
                    if info["warnings"]:
                        raise ValueError("JPEG decoder reported warnings")
                    decoder_meta.append(info)
                    image = np.fromfile(decoded, np.uint8)
                    if image.size != frame["width"] * frame["height"] * 3:
                        raise ValueError("Invalid decoded JPEG buffer length")
                    image = image.reshape(frame["height"], frame["width"], 3)
                v, spread = patch_samples(image, patches)
                values.append(v); spreads.append(spread)
                if i == 0:
                    first_images[mode] = image
            samples[mode] = np.median(values, axis=0)
            # Validate chart content independently of choosing a standard matrix.
            x = np.c_[rgb, np.ones(len(rgb))]
            train = np.arange(len(rgb)) % 2 == 0
            fit = np.linalg.lstsq(x[train], samples[mode][train], rcond=None)[0]
            holdout = rmse((x @ fit)[~train], samples[mode][~train])
            if holdout > 12 or samples[mode][31, 0] - samples[mode][0, 0] < 100:
                raise ValueError("USB recording does not contain the displayed chart")
            times = np.array([f["pts_seconds"] for f in meta["frames"]])
            summaries[mode] = {"frame_count": len(values), "size": [1920, 1080],
                "negotiated_fps": 1e7 / meta["interval_100ns"],
                "median_callback_interval_seconds": float(np.median(np.diff(times))),
                "sequence": [f["sequence"] for f in meta["frames"]],
                "black": samples[mode][0].tolist(), "white": samples[mode][31].tolist(),
                "maximum_patch_temporal_span": float(np.ptp(values, axis=0).max()),
                "maximum_patch_spatial_p95_p05": float(np.max(spreads)),
                "affine_holdout_yuv_rmse": holdout, "models": models(samples[mode], rgb)}
    avf = json.loads((args.avf / "analysis.json").read_text())
    if [(p["name"], p["expected_display_rgb"]) for p in patches] != [(p["name"], p["expected_display_rgb"]) for p in avf["patches"]]:
        raise ValueError("AVFoundation comparison has a different chart/reference")
    samples["avf_decoded"] = np.array([p["measured_yuv"] for p in avf["patches"]])
    avf_meta = json.loads((args.avf / "capture.json").read_text())
    first_images["avf_decoded"] = unpack(args.avf / avf_meta["frames"][0]["file"], avf_meta["frames"][0])
    scale = np.array([219/255, 224/255, 224/255])
    offset = np.array([16, 128, 128]) - np.array([0, 128, 128]) * scale
    restored = (samples["avf_decoded"] - offset) / scale
    standard_jpeg = np.array(Image.open(args.usb / "mjpeg" / "frame-000.jpg").convert("RGB"))
    standard_values = patch_samples(standard_jpeg, patches)[0]
    comparison = {
        "jpeg_vs_yuy2_yuv_rmse": rmse(samples["mjpeg"], samples["yuy2"]),
        "avf_vs_original_jpeg_identity_rmse": rmse(samples["avf_decoded"], samples["mjpeg"]),
        "avf_vs_original_jpeg_extra_full_to_limited_rmse": rmse(samples["avf_decoded"], samples["mjpeg"] * scale + offset),
        "avf_vs_original_jpeg_full_to_limited_rmse": rmse(samples["avf_decoded"], samples["mjpeg"] * scale + offset),
        "usb_range": args.usb_range,
        "avf_decoded_models": models(samples["avf_decoded"], rgb),
        "avf_range_restored_vs_original_jpeg_rmse": rmse(restored, samples["mjpeg"]),
        "avf_range_restored_models": models(restored, rgb),
        "standard_jpeg_rgb_rmse": rmse(standard_values, rgb),
        "standard_jpeg_vs_clipped_601_full_rgb_rmse": rmse(standard_values, np.clip(decode(samples["mjpeg"], "601", "full"), 0, 255)),
        "relative_scale": scale.tolist(), "relative_offset": offset.tolist(),
    }
    # The earlier limited-range USB profile suffered an additional compression.
    # For calibrated full-range USB samples this same conversion is appropriate.
    comparison["paired_capture_samples_agree"] = min(
        comparison["avf_vs_original_jpeg_identity_rmse"],
        comparison["avf_vs_original_jpeg_full_to_limited_rmse"]) <= 2
    comparison["range_conversion_interpretation"] = (
        ("full-range USB to limited-range AVFoundation" if args.usb_range == "full"
         else "additional compression of limited-range USB")
        if comparison["paired_capture_samples_agree"] else
        "Captures differ beyond identity/range conversion; do not attribute the discrepancy to the decoder alone")
    for mode in ["yuy2", "mjpeg"]:
        save_rgb(decode(first_images[mode], "709", args.usb_range), out / f"{mode}-709-{args.usb_range}.png")
    restored_preview = out / f"avf-range-restored-709-{args.usb_range}.png"
    save_rgb(decode((first_images["avf_decoded"] - offset) / scale, "709", args.usb_range), restored_preview)
    save_rgb(decode(first_images["avf_decoded"], "709", "limited"), out / "avf-uncorrected-709-limited.png")
    Image.fromarray(standard_jpeg).save(out / "mjpeg-standard-rgb.png")
    panels = [(args.source / "source-render.png", "Source: display ICC reference"),
              (out / f"yuy2-709-{args.usb_range}.png", f"USB YUY2: 709 {args.usb_range} inverse"),
              (out / f"mjpeg-709-{args.usb_range}.png", f"USB MJPEG: 709 {args.usb_range} inverse"),
              (out / "mjpeg-standard-rgb.png", "USB JPEG: ordinary RGB decode"),
              (out / "avf-uncorrected-709-limited.png", "AVF MJPEG path: 709 limited inverse"),
              (restored_preview, "AVF: range restored + 709 inverse")]
    canvas = Image.new("RGB", (1440, 620), "#f1f1f1")
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 19)
    draw = ImageDraw.Draw(canvas)
    for i, (path, label) in enumerate(panels):
        x, y = i % 3 * 480, i // 3 * 310
        draw.text((x + 8, y + 9), label, font=font, fill="black")
        canvas.paste(Image.open(path).convert("RGB").resize((480, 270), Image.Resampling.NEAREST), (x, y + 40))
    canvas.save(out / "comparison.png")
    with (out / "patches.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["patch", "reference_R", "reference_G", "reference_B", "YUY2_Y", "YUY2_Cb", "YUY2_Cr", "JPEG_Y", "JPEG_Cb", "JPEG_Cr", "AVF_Y", "AVF_Cb", "AVF_Cr"])
        for i, patch in enumerate(patches):
            writer.writerow([patch["name"], *rgb[i], *samples["yuy2"][i], *samples["mjpeg"][i], *samples["avf_decoded"][i]])
    result = {"usb_directory": str(args.usb.resolve()), "source_directory": str(args.source.resolve()),
              "avfoundation_directory": str(args.avf.resolve()), "source_render_rgb_rmse": source_error,
              "original_usb": summaries, "jpeg_decoder_metadata": decoder_meta, "comparison": comparison,
              "patches": [{**patch, **{key: value[i].tolist() for key, value in samples.items()}} for i, patch in enumerate(patches)]}
    write_json(out / "analysis.json", result)
    gray = []
    for key, label in [("yuy2", "USB YUY2"), ("mjpeg", "Original USB JPEG samples"), ("avf_decoded", "AVFoundation decoded")]:
        gray.append({"run": label, "gray": [{"source_code": patch["rgb"][0], "yuv": samples[key][i].tolist()} for i, patch in enumerate(patches) if patch["name"].startswith("gray-")]})
    write_json(out / "gray-ramp-data.json", gray)
    evidence = [*args.usb.rglob("*"), *args.source.rglob("*"), *out.rglob("*")]
    write_json(out / "sha256.json", {str(path.resolve().relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(evidence) if path.is_file()})
    print(json.dumps({"original_usb": summaries, "comparison": comparison, "jpeg_header": decoder_meta[0]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usb", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("avf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--usb-range", choices=["limited", "full"], default="limited",
                        help="Measured original USB range; determines explicit preview inverse")
    run(parser.parse_args())
