#!/usr/bin/env python3
"""Analyze the raw YUY2 FE84=7A/40 scaled-mode comparison."""
import argparse
import json
from pathlib import Path

import numpy as np

W, H, N = 1280, 720, 8
SCALE = W / 1920


def load(path):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != N * W * H * 2:
        raise ValueError(f"Unexpected YUY2 payload length in {path}: {data.size}")
    return data.reshape(N, H, W, 2)[..., 0].astype(np.int16)


def stripe_metrics(y):
    out = []
    avg = y.astype(np.float64).mean(axis=0)
    for i, period in enumerate((32, 16, 8, 4, 2)):
        start = 1040 + i * 158
        x0 = int(np.ceil((start + 3) * SCALE))
        x1 = int(np.floor((start + 137) * SCALE))
        x = np.arange(x0, x1)
        source_x = (x + 0.5) / SCALE
        bright = (((source_x - start) // max(1, period // 2)) % 2) == 0
        roi = avg[173:266, x0:x1]
        hi, lo = float(roi[:, bright].mean()), float(roi[:, ~bright].mean())
        out.append({"source_period_px": period, "bright_Y_mean": round(hi, 4),
                    "dark_Y_mean": round(lo, 4),
                    "michelson_contrast": round((hi - lo) / (hi + lo), 6)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture_dir", type=Path)
    args = ap.parse_args()
    root = args.capture_dir.resolve()
    a = load(root / "fe84-7a-1280x720.yuy2")
    b = load(root / "fe84-40-1280x720.yuy2")
    d = b - a
    regions = {"center": (slice(100, 620), slice(100, 1180)),
               "fine_chart": (slice(160, 285), slice(680, 1200)),
               "lower_gray": (slice(680, 705), slice(70, 330))}
    uniform = {"black": (slice(84, 124), slice(700, 920)),
               "white": (slice(84, 124), slice(1010, 1200)),
               "gray": (slice(180, 360), slice(648, 668))}
    result = {"capture_dir": str(root), "capture_size": [W, H], "frame_count": N,
              "fe84_7a_sha256": __import__("hashlib").sha256((root / "fe84-7a-1280x720.yuy2").read_bytes()).hexdigest(),
              "fe84_40_sha256": __import__("hashlib").sha256((root / "fe84-40-1280x720.yuy2").read_bytes()).hexdigest(),
              "mean_absolute_Y_delta": round(float(np.abs(d).mean()), 6),
              "max_absolute_Y_delta": int(np.abs(d).max()),
              "changed_sample_fraction": round(float(np.mean(d != 0)), 8),
              "within_1_code_fraction": round(float(np.mean(np.abs(d) <= 1)), 8),
              "mean_absolute_delta_by_region": {name: round(float(np.abs(d[:, ys, xs]).mean()), 6)
                                                for name, (ys, xs) in regions.items()},
              "stripe_response": {"FE84_7A": stripe_metrics(a), "FE84_40": stripe_metrics(b)},
              "flat_field_Y_levels": {state: {name: np.unique(data[:, ys, xs]).astype(int).tolist()
                                               for name, (ys, xs) in uniform.items()}
                                      for state, data in (("FE84_7A", a), ("FE84_40", b))},
              "interpretation_limit": "Raw device YUY2 output; FE84 response is end-to-end and does not establish the register's internal arithmetic or sharpness semantics."}
    target = root / "analysis.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
