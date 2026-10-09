#!/usr/bin/env python3
"""Analyze the chart-gated FE84 7A→74 early/settled captures."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from probe_fe84_negative import flat_plane_check


def load(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    if rgb.shape != (720, 1280, 3):
        raise ValueError(f"Unexpected capture dimensions for {path}: {rgb.shape}")
    values = rgb.astype(np.int32)
    y = (77 * values[..., 0] + 150 * values[..., 1] + 29 * values[..., 2]) >> 8
    return rgb, y


def stripe_contrast(y, start_x, period):
    scale = 1280 / 1920
    x0 = int(np.ceil((start_x + 3) * scale))
    x1 = int(np.floor((start_x + 137) * scale))
    x = np.arange(x0, x1)
    source_x = (x + 0.5) / scale
    stripe = (((source_x - start_x) // max(1, period // 2)) % 2) == 0
    roi = y[173:266, x0:x1].astype(float)
    white = float(roi[:, stripe].mean())
    gray = float(roi[:, ~stripe].mean())
    return {"white_line_mean": round(white, 3), "gray_gap_mean": round(gray, 3),
            "michelson_contrast": round((white-gray)/(white+gray), 6)}


def edge_crossings(y):
    hits = []
    for row in range(85, 650):
        x0 = int(round(312 + 0.1 * (row - 75)))
        indices = np.flatnonzero(y[row, x0-25:x0+26] >= 126)
        hits.append(x0 - 25 + int(indices[0]) if len(indices) else np.nan)
    return np.asarray(hits)


def compare(base_rgb, base_y, candidate_rgb, candidate_y, base_edges):
    delta = np.abs(base_rgb.astype(np.int16) - candidate_rgb.astype(np.int16))
    edges = edge_crossings(candidate_y) - base_edges
    stripes = []
    for index, period in enumerate((32, 16, 8, 4, 2)):
        start = 1040 + index * 158
        baseline = stripe_contrast(base_y, start, period)
        tested = stripe_contrast(candidate_y, start, period)
        stripes.append({"source_period_px": period, "baseline_7a": baseline,
                        "tested": tested,
                        "delta_michelson": round(tested["michelson_contrast"] -
                                                  baseline["michelson_contrast"], 6)})
    return {"changed_pixels": int(np.any(delta != 0, axis=2).sum()),
            "mean_abs_rgb_delta": round(float(delta.mean()), 6),
            "max_abs_rgb_delta": int(delta.max()), "stripes": stripes,
            "edge_a_crossing_shift_px": {
                "mean": round(float(np.nanmean(edges)), 4),
                "p95_absolute": round(float(np.nanquantile(np.abs(edges), .95)), 4)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    args = parser.parse_args()
    root = args.capture_dir.resolve()
    manifest = json.loads((root / "result.json").read_text())
    stages = {stage["state"]: root / Path(stage["capture"]["image"]).name
              for stage in manifest["stages"]}
    expected = ("FE84=7A", "FE84=74, early", "FE84=74, settled", "FE84 restored to 7A")
    if any(name not in stages or not stages[name].is_file() for name in expected):
        raise ValueError("Expected baseline, early, settled, and restored frames are required")
    frames = {name: load(stages[name]) for name in expected}
    baseline_stage = next(stage for stage in manifest["stages"] if stage["state"] == "FE84=7A")
    uniform_video_files = {
        "baseline_a": root / Path(baseline_stage["capture"]["movie"]).name,
        "baseline_b": root / Path(baseline_stage["repeat_capture"]["movie"]).name,
    }
    for stage in manifest["stages"]:
        if stage["state"] != "FE84=7A":
            uniform_video_files[stage["state"]] = root / Path(stage["capture"]["movie"]).name
    baseline_rgb, baseline_y = frames["FE84=7A"]
    baseline_edges = edge_crossings(baseline_y)
    result = {"capture_dir": str(root), "capture_size": [1280, 720],
              "baseline_image_sha256": hashlib.sha256(stages["FE84=7A"].read_bytes()).hexdigest(),
              "uniform_plane_validation": {
                  name: flat_plane_check(path)
                  for name, path in uniform_video_files.items()},
              "comparisons": {},
              "interpretation_limit": (
                  "This records end-to-end 720p response to a temporary FE84 value. "
                  "A settling-dependent image change is consistent with calibration or "
                  "adaptation, but does not alone identify the internal mechanism.")}
    for name in expected[1:]:
        rgb, y = frames[name]
        result["comparisons"][name] = compare(baseline_rgb, baseline_y, rgb, y, baseline_edges)
    early = frames["FE84=74, early"][0]
    late = frames["FE84=74, settled"][0]
    drift = np.abs(early.astype(np.int16) - late.astype(np.int16))
    result["early_to_settled"] = {"changed_pixels": int(np.any(drift != 0, axis=2).sum()),
                                  "mean_abs_rgb_delta": round(float(drift.mean()), 6),
                                  "max_abs_rgb_delta": int(drift.max())}
    output = root / "fe84-negative-analysis.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
