#!/usr/bin/env python3
"""Measure spatial-frequency response in the saved MS2109 grid-chart captures."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def luma(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int32)
    return (77 * rgb[..., 0] + 150 * rgb[..., 1] + 29 * rgb[..., 2]) >> 8


def michelson(values, mask):
    stripe = float(values[:, mask].mean())
    background = float(values[:, ~mask].mean())
    contrast = (stripe - background) / (stripe + background)
    return {
        "stripe_mean": round(stripe, 3),
        "background_mean": round(background, 3),
        "michelson_contrast": round(contrast, 6),
    }


def analyze(source_path, off_path, on_path):
    source, off, on = map(luma, (source_path, off_path, on_path))
    if source.shape != off.shape or off.shape != on.shape:
        raise ValueError(f"Frame dimension mismatch: {source.shape}, {off.shape}, {on.shape}")

    patches = []
    for index, period in enumerate((32, 16, 8, 4, 2)):
        x = 1040 + index * 158
        xx = np.arange(x + 3, x + 137)
        stripe_mask = (((xx - x) // max(1, period // 2)) % 2) == 0
        rows = slice(260, 400)
        source_stats = michelson(source[rows, x + 3:x + 137], stripe_mask)
        off_stats = michelson(off[rows, x + 3:x + 137], stripe_mask)
        on_stats = michelson(on[rows, x + 3:x + 137], stripe_mask)
        patches.append({
            "period_px": period,
            "source": source_stats,
            "f9a0_00": off_stats,
            "f9a0_01": on_stats,
            "contrast_gain_vs_source": round(
                off_stats["michelson_contrast"] / source_stats["michelson_contrast"], 4
            ),
        })

    # The 1-pixel checker is a 2-pixel-period Nyquist target.
    checker_roi = np.s_[720:940, 1680:1800]
    checker_mask = np.fromfunction(lambda y, x: ((y + x) % 2) * 2 - 1,
                                   off[checker_roi].shape)
    checker = {}
    for name, frame in (("source", source), ("f9a0_00", off), ("f9a0_01", on)):
        checker[name + "_alternating_luma_amplitude"] = round(
            float(np.mean(frame[checker_roi] * checker_mask)), 3
        )

    changed = np.any(off != on, axis=0)
    return {
        "source": str(source_path),
        "f9a0_00_frame": str(off_path),
        "f9a0_01_frame": str(on_path),
        "dimensions": [int(off.shape[1]), int(off.shape[0])],
        "f9a0_frames_byte_identical": hashlib.sha256(off.tobytes()).digest()
            == hashlib.sha256(on.tobytes()).digest(),
        "changed_pixel_count": int(changed.sum()),
        "stripe_patches": patches,
        "checker_patch": checker,
        "2px_to_32px_contrast_ratio": round(
            patches[-1]["f9a0_00"]["michelson_contrast"] / patches[0]["f9a0_00"]["michelson_contrast"], 4
        ),
        "interpretation_limit": (
            "This is end-to-end display, HDMI, MS2109 and YUY2/RGB-conversion response; "
            "it identifies frequency-dependent contrast shaping but cannot isolate the "
            "chip stage by itself."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("artifacts/scaler-f9a0/test-chart-1920x1080.png"))
    parser.add_argument("--off", type=Path,
                        default=Path("artifacts/scaler-f9a0/grid-01/f9a0-00-1080.png"))
    parser.add_argument("--on", type=Path,
                        default=Path("artifacts/scaler-f9a0/grid-01/f9a0-01-1080.png"))
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/scaler-f9a0/grid-01/spatial-response.json"))
    args = parser.parse_args()
    result = analyze(args.source, args.off, args.on)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
