#!/usr/bin/env python3
"""Compare repeated and perturbed FE84 chart captures at 1280x720."""
import json
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path("artifacts/scaler-f9a0/grid-01")
FRAMES = {
    "7a": ROOT / "fe84-7a-720.png",
    "7a_repeat": ROOT / "fe84-7a-repeat-720.png",
    "7b": ROOT / "fe84-7b-720.png",
    "80": ROOT / "fe84-80-720.png",
}


def load(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int32)
    y = (77 * rgb[..., 0] + 150 * rgb[..., 1] + 29 * rgb[..., 2]) >> 8
    return rgb, y


def contrast(frame, start_x, period):
    # The capture is 1280x720 for a 1920x1080 source, nominally 2/3 scale.
    scale = 1280 / 1920
    x0 = int(np.ceil((start_x + 3) * scale))
    x1 = int(np.floor((start_x + 137) * scale))
    y0, y1 = 173, 266
    x = np.arange(x0, x1)
    source_x = (x + 0.5) / scale
    stripe = (((source_x - start_x) // max(1, period // 2)) % 2) == 0
    roi = frame[y0:y1, x0:x1].astype(float)
    white = float(roi[:, stripe].mean())
    gray = float(roi[:, ~stripe].mean())
    return {
        "white_line_mean": round(white, 3),
        "gray_gap_mean": round(gray, 3),
        "michelson_contrast": round((white - gray) / (white + gray), 6),
    }


def main():
    loaded = {key: load(path) for key, path in FRAMES.items()}
    rgb = {key: value[0] for key, value in loaded.items()}
    y = {key: value[1] for key, value in loaded.items()}
    results = {"capture_size": [1280, 720], "baseline_repeat_identical":
               hashlib.sha256(rgb["7a"].tobytes()).digest()
               == hashlib.sha256(rgb["7a_repeat"].tobytes()).digest(),
               "comparisons": {}}

    for candidate in ("7b", "80"):
        delta = np.abs(rgb["7a"].astype(np.int16) - rgb[candidate].astype(np.int16))
        results["comparisons"][candidate] = {
            "changed_pixels": int(np.any(delta > 0, axis=2).sum()),
            "mean_abs_rgb_delta": round(float(delta.mean()), 6),
            "max_abs_rgb_delta": int(delta.max()),
            "stripes": [],
        }
        for index, period in enumerate((32, 16, 8, 4, 2)):
            start = 1040 + index * 158
            baseline = contrast(y["7a"], start, period)
            changed = contrast(y[candidate], start, period)
            results["comparisons"][candidate]["stripes"].append({
                "source_period_px": period,
                "baseline_7a": baseline,
                "candidate": changed,
                "delta_michelson": round(
                    changed["michelson_contrast"] - baseline["michelson_contrast"], 6
                ),
            })

    # Detect integer-pixel movement of the A slanted edge.
    edges = {}
    for name in ("7b", "80"):
        deltas = []
        for row in range(85, 650):
            x0 = int(round(312 + 0.1 * (row - 75)))
            crossings = []
            for state in ("7a", name):
                profile = y[state][row, x0 - 25:x0 + 26]
                indices = np.flatnonzero(profile >= 126)
                crossings.append(x0 - 25 + int(indices[0]) if len(indices) else np.nan)
            deltas.append(crossings[1] - crossings[0])
        edges[name] = {
            "mean_crossing_shift_px": round(float(np.nanmean(deltas)), 4),
            "p95_absolute_crossing_shift_px": round(
                float(np.nanquantile(np.abs(deltas), 0.95)), 4
            ),
        }
    results["edge_a_crossing_shift"] = edges
    results["interpretation_limit"] = (
        "FE84 effects are observed in the end-to-end capture. Repeated 7A frames "
        "are identical, but the captures do not prove the internal scaler architecture."
    )
    output = ROOT / "fe84-spatial-response.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
