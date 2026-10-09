#!/usr/bin/env python3
"""Generate and analyze an exhaustive 24-bit RGB sweep captured as packed YUY2."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
PER_PAGE = W * H
COLOR_COUNT = 1 << 24
PAGES = (COLOR_COUNT + PER_PAGE - 1) // PER_PAGE
# Odd multiplier is invertible modulo 2^24, so this permutation visits every
# RGB code exactly once while keeping neighboring pixels far apart in RGB.
MULTIPLIER = 0x5BD1E9
OFFSET = 0x37A4C1


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    page_records = []
    for page in range(PAGES):
        start = page * PER_PAGE
        count = min(PER_PAGE, COLOR_COUNT - start)
        seq = np.arange(start, start + count, dtype=np.uint32)
        code = (seq * np.uint32(MULTIPLIER) + np.uint32(OFFSET)) & np.uint32(COLOR_COUNT - 1)
        rgb = np.empty((PER_PAGE, 3), dtype=np.uint8)
        rgb[:count, 0] = code & 255
        rgb[:count, 1] = (code >> 8) & 255
        rgb[:count, 2] = (code >> 16) & 255
        # Tail pixels are outside the declared sweep and are omitted by analysis.
        if count < PER_PAGE:
            rgb[count:] = 0
        path = directory / f"page-{page:02d}.png"
        Image.fromarray(rgb.reshape(H, W, 3), "RGB").save(path, optimize=False)
        page_records.append({"page": page, "file": path.name, "first_sequence": start,
                             "valid_pixels": count, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"width": W, "height": H, "unique_input_rgb_triplets": COLOR_COUNT,
                "page_count": PAGES, "rgb_index_permutation": {"multiplier": MULTIPLIER,
                "offset": OFFSET, "modulus": COLOR_COUNT},
                "ordering": "pixel n encodes (n*multiplier+offset) mod 2^24; R is low byte",
                "pages": page_records}
    write_json(directory / "rgb-cube.json", manifest)


def unpack_yuy2(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != PER_PAGE * 2:
        raise ValueError(f"Expected {PER_PAGE*2} packed bytes in {path}; got {data.size}")
    packed = data.reshape(H, W // 2, 4)
    yuv = np.empty((H, W, 3), dtype=np.uint8)
    yuv[:, 0::2, 0] = packed[:, :, 0]
    yuv[:, 1::2, 0] = packed[:, :, 2]
    yuv[:, 0::2, 1] = packed[:, :, 1]
    yuv[:, 1::2, 1] = packed[:, :, 1]
    yuv[:, 0::2, 2] = packed[:, :, 3]
    yuv[:, 1::2, 2] = packed[:, :, 3]
    return yuv


def analyze(run: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    source = json.loads((run / "rgb-cube.json").read_text())
    meta = json.loads((run / "capture.json").read_text())
    if source["unique_input_rgb_triplets"] != COLOR_COUNT or source["page_count"] != PAGES:
        raise ValueError("Unexpected RGB cube manifest")
    if meta.get("width") != W or meta.get("height") != H or meta.get("pixel_format") != "yuvs":
        raise ValueError("Capture must be 1920x1080 packed YUY2 (yuvs)")
    frames = meta.get("frames", [])
    by_page: dict[int, list[dict]] = {p: [] for p in range(PAGES)}
    for frame in frames:
        by_page[int(frame["page"])].append(frame)
    if any(len(by_page[p]) < 2 for p in range(PAGES)):
        raise ValueError("Need at least two captured frames for every page")

    # One bit per possible output code is enough for exact coverage accounting.
    seen_rgb = np.zeros(COLOR_COUNT, dtype=np.bool_)
    seen_yuv = np.zeros(COLOR_COUNT, dtype=np.bool_)
    component_codes = [np.zeros(256, dtype=np.bool_) for _ in range(3)]
    page_stats = []
    total_pixels = 0
    changed_pixels = 0
    first_frame_paths = []
    rcoef, gcb, gcr, bcoef = 1.5748, -0.187324, -0.468124, 1.8556

    for record in source["pages"]:
        page = int(record["page"])
        group = sorted(by_page[page], key=lambda x: int(x["page_frame"]))
        yuv_frames = [unpack_yuy2(run / item["file"]) for item in group]
        base = yuv_frames[0]
        valid = int(record["valid_pixels"])
        flat = base.reshape(-1, 3)[:valid]
        packed = ((flat[:, 0].astype(np.uint32) << 16) |
                  (flat[:, 1].astype(np.uint32) << 8) | flat[:, 2].astype(np.uint32))
        seen_yuv[packed] = True
        for channel in range(3):
            component_codes[channel][flat[:, channel]] = True
        y = flat[:, 0].astype(np.float32)
        cb = flat[:, 1].astype(np.float32) - 128.0
        cr = flat[:, 2].astype(np.float32) - 128.0
        rgb = np.stack((y + rcoef * cr, y + gcb * cb + gcr * cr,
                        y + bcoef * cb), axis=1)
        gamut_clipped = int(np.count_nonzero(np.any((rgb < 0) | (rgb > 255), axis=1)))
        rgb = np.clip(np.rint(rgb), 0, 255).astype(np.uint32)
        rgb_codes = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
        seen_rgb[rgb_codes] = True
        if len(yuv_frames) > 1:
            delta = np.any(yuv_frames[1].reshape(-1, 3)[:valid] != flat, axis=1)
            page_changed = int(np.count_nonzero(delta))
        else:
            page_changed = 0
        changed_pixels += page_changed
        total_pixels += valid
        first_frame_paths.append(group[0]["file"])
        page_stats.append({"page": page, "input_triplets": valid,
                           "captured_frames": len(group),
                           "pixels_different_between_first_two_frames": page_changed,
                           "decoded_rgb_triplets_clipped_before_rounding": gamut_clipped,
                           "unique_packed_yuv_triplets_in_page": int(np.unique(packed).size),
                           "unique_decoded_rgb_triplets_in_page": int(np.unique(rgb_codes).size)})
        del yuv_frames, base, flat, packed, y, cb, cr, rgb, rgb_codes

    if total_pixels != COLOR_COUNT:
        raise ValueError(f"Captured {total_pixels} valid sweep pixels; expected {COLOR_COUNT}")
    absent_examples = np.flatnonzero(~seen_rgb)[:256]
    missing_by_red = np.count_nonzero(~seen_rgb.reshape(256, 256, 256), axis=(1, 2)).tolist()
    result = {
        "scope": "Exhaustive input RGB triplet sweep; raw YUY2 capture; full-range BT.709 decode",
        "firmware_image_sha256": meta.get("firmware_image_sha256"),
        "source_input_triplets": total_pixels,
        "source_coverage_complete": total_pixels == COLOR_COUNT,
        "capture_frames": len(frames),
        "transport": "YUY2 4:2:2, AVFoundation yuvs output",
        "decode": "BT.709 full range; Y'=Y, R'=Y+1.5748(Cr-128), G'=Y-0.187324(Cb-128)-0.468124(Cr-128), B'=Y+1.8556(Cb-128)",
        "observed_unique_packed_yuv_triplets": int(seen_yuv.sum()),
        "unique_packed_yuv_missing_from_24bit_code_space": int(COLOR_COUNT - seen_yuv.sum()),
        "observed_unique_decoded_rgb_triplets": int(seen_rgb.sum()),
        "missing_decoded_rgb_triplets": int(COLOR_COUNT - seen_rgb.sum()),
        "missing_decoded_rgb_first_256_hex": [f"{int(v):06x}" for v in absent_examples],
        "missing_decoded_rgb_count_by_red_code": missing_by_red,
        "observed_yuv_component_code_counts": [int(c.sum()) for c in component_codes],
        "missing_yuv_component_codes": [[int(v) for v in np.flatnonzero(~c)] for c in component_codes],
        "pixels_changed_between_first_two_frames": changed_pixels,
        "pages": page_stats,
        "coverage_bitmap_rgb": "rgb-coverage.bits (one bit per decoded 24-bit RGB code; bit value 1 means observed)",
    }
    np.packbits(seen_rgb, bitorder="little").tofile(output / "rgb-coverage.bits")
    np.packbits(seen_yuv, bitorder="little").tofile(output / "yuv-coverage.bits")
    write_json(output / "result.json", result)
    with (output / "missing-red-slices.csv").open("w") as f:
        f.write("red_code,missing_decoded_rgb_triplets\n")
        for code, count in enumerate(missing_by_red):
            f.write(f"{code},{count}\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.iterdir()) if p.is_file() and p.name != "sha256.json"}
    write_json(output / "sha256.json", hashes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--output", type=Path, required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--pages", type=Path, required=True)
    cap.add_argument("--output", type=Path, required=True)
    cap.add_argument("--firmware-image", type=Path, required=True)
    ana = sub.add_parser("analyze")
    ana.add_argument("run", type=Path)
    ana.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.output)
    elif args.command == "capture":
        helper = ROOT / "tools" / "rgb_cube_capture.m"
        compile_cmd = ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                       "-framework", "Cocoa", "-framework", "AVFoundation",
                       "-framework", "CoreMedia", "-framework", "CoreVideo"]
        with tempfile.TemporaryDirectory(prefix="rgb-cube-capture-") as temp:
            binary = Path(temp) / "rgb_cube_capture"
            subprocess.run(compile_cmd + [str(helper), "-o", str(binary)], check=True)
            subprocess.run([str(binary), "--pages", str(args.pages.resolve()), "--output",
                            str(args.output.resolve())], check=True)
        meta_path = args.output / "capture.json"
        meta = json.loads(meta_path.read_text())
        meta["firmware_image_sha256"] = hashlib.sha256(args.firmware_image.read_bytes()).hexdigest()
        meta["source_manifest_sha256"] = hashlib.sha256((args.pages / "rgb-cube.json").read_bytes()).hexdigest()
        write_json(meta_path, meta)
    else:
        result = analyze(args.run.resolve(), args.output.resolve())
        print(json.dumps({k: result[k] for k in ["source_input_triplets", "observed_unique_packed_yuv_triplets",
              "observed_unique_decoded_rgb_triplets", "missing_decoded_rgb_triplets",
              "observed_yuv_component_code_counts", "pixels_changed_between_first_two_frames"]}, indent=2))


if __name__ == "__main__":
    main()
