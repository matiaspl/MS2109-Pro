#!/usr/bin/env python3
"""Render claim-focused figures from the saved MS2109 scaler captures."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/ms2109-repair/20261008/scaler-fe80-8f"
OUT = ARTIFACTS / "visual-evidence"


def load_result(relative: str) -> dict:
    return json.loads((ARTIFACTS / relative).read_text())


def capture_y(relative: str, width: int, height: int) -> np.ndarray:
    """Return the mean Y plane of all saved YUYV frames in a capture."""
    raw = np.fromfile(ARTIFACTS / relative, dtype=np.uint8)
    frame_bytes = width * height * 2
    if raw.size == 0 or raw.size % frame_bytes:
        raise ValueError(f"unexpected YUYV size for {relative}: {raw.size}")
    frames = raw.reshape(-1, height, width, 2)
    return frames[..., 0].astype(np.float32).mean(axis=0)


def probe(document: dict, label: str) -> dict:
    for item in document["probe_results"]:
        if item.get("label") == label or item.get("state") == label:
            return item
    raise KeyError(f"probe {label!r} not found")


def contrast_values(document: dict, label: str, orientation: str = "B1_vertical_lines_vary_x") -> list[float]:
    rows = probe(document, label)["metrics"]["spatial_response"][orientation]
    return [float(row["michelson_contrast"]) for row in rows]


def flat_values(document: dict, label: str) -> dict[str, float]:
    fields = probe(document, label)["metrics"]["spatial_response"]["flat_fields"]
    return {name: float(fields[name]["mean_y"]) for name in ("black", "gray", "white")}


def add_image_crop(ax, image: np.ndarray, bounds: tuple[int, int, int, int], *, vmin=16, vmax=235):
    x0, y0, x1, y1 = bounds
    ax.imshow(image[y0:y1, x0:x1], cmap="gray", vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect="auto")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#777")
        spine.set_linewidth(0.8)


def detail_figure() -> None:
    repeat = load_result("repeat-native/result.json")
    full = load_result("native-1080/result.json")
    width, height = 1920, 1080
    repeat_frames = {
        "Baseline": capture_y("repeat-native/baseline.yuy2", width, height),
        "FE80.0: 01→00": capture_y("repeat-native/probe-00-FE800.yuy2", width, height),
        "FE84: 7A→40": capture_y("repeat-native/probe-02-FE84-40.yuy2", width, height),
    }

    fig = plt.figure(figsize=(17, 11))
    grid = fig.add_gridspec(3, 2, width_ratios=(1.2, 1.0))
    fig.subplots_adjust(top=0.88, bottom=0.09, left=0.16, right=0.97, hspace=0.30, wspace=0.22)
    fig.suptitle("Captured evidence: FE80 and FE84 reduce high-frequency horizontal detail", fontsize=18, y=0.985)
    fig.text(0.5, 0.94,
             "Left: actual YUYV capture crops (P4 and P2 vertical stripes), fixed Y range 16–235. "
             "Right: measured B1 Michelson contrast from 9-frame averages.",
             ha="center", fontsize=10)

    crop_bounds = (1522, 228, 1804, 392)
    periods = [32, 16, 8, 4, 2]
    for row, (label, image) in enumerate(repeat_frames.items()):
        ax = fig.add_subplot(grid[row, 0])
        add_image_crop(ax, image, crop_bounds)
        values = contrast_values(repeat, {"Baseline": "baseline", "FE80.0: 01→00": "FE80.0", "FE84: 7A→40": "FE84=40"}[label])
        ax.set_title(f"{label}   |   P4 contrast {values[3]:.3f}   |   P2 contrast {values[4]:.3f}",
                     fontsize=10, pad=4, loc="left")
    ax = fig.add_subplot(grid[:, 1])
    series = [
        ("Baseline", "baseline", "#222222"),
        ("FE80.0: 01→00", "FE80.0", "#2878b5"),
        ("FE84: 7A→40", "FE84=40", "#d17a22"),
    ]
    positions = np.arange(len(periods))
    for label, state, color in series:
        ax.plot(positions, contrast_values(repeat, state), marker="o", linewidth=2.4,
                markersize=6, color=color, label=label)
    ax.set_xticks(positions, [f"P{p}" for p in periods])
    ax.set_ylim(0.25, 0.66)
    ax.set_xlabel("B1 stripe period in source pixels (smaller = finer horizontal detail)")
    ax.set_ylabel("Michelson contrast in captured Y")
    ax.set_title("Measured response by stripe pitch", fontsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    ax.annotate("At P2: 0.599 → 0.355",
                xy=(4, contrast_values(repeat, "FE84=40")[4]), xytext=(-135, 35),
                textcoords="offset points", fontsize=10,
                arrowprops={"arrowstyle": "->", "color": "#555"})
    fig.text(0.5, 0.025,
             "The crops are magnified for inspection; pixel values are not contrast-enhanced. "
             "FE80.0 and FE84 show similar measured responses, not proof of identical internal roles.",
             ha="center", fontsize=9, color="#444")
    fig.savefig(OUT / "detail-response.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # FE85.1 full sweep: compare the highest-frequency B1 patch and its measured polarity.
    baseline = capture_y("native-1080/baseline.yuy2", width, height)
    candidate = capture_y("native-1080/probe-13-FE851.yuy2", width, height)
    fig = plt.figure(figsize=(16, 8))
    grid = fig.add_gridspec(2, 2, height_ratios=(1.1, 1.0))
    fig.subplots_adjust(top=0.86, bottom=0.13, left=0.08, right=0.97, hspace=0.32, wspace=0.12)
    fig.suptitle("Captured evidence: FE85.1 reverses the P2 horizontal-pattern response", fontsize=18, y=0.985)
    fig.text(0.5, 0.93,
             "P2 vertical-stripe patch from the native 1080p capture; same fixed grayscale range.",
             ha="center", fontsize=10)
    p2_bounds = (1680, 228, 1804, 392)
    ax = fig.add_subplot(grid[0, 0])
    add_image_crop(ax, baseline, p2_bounds)
    ax.set_title(f"Baseline — P2 contrast {contrast_values(full, 'baseline')[4]:+.3f}")
    ax = fig.add_subplot(grid[0, 1])
    add_image_crop(ax, candidate, p2_bounds)
    ax.set_title(f"FE85.1 set — P2 contrast {contrast_values(full, 'FE85.1')[4]:+.3f}")
    ax = fig.add_subplot(grid[1, :])
    positions = np.arange(len(periods))
    for label, state, color in [
        ("Baseline", "baseline", "#222222"),
        ("FE85.1: 00→02", "FE85.1", "#b64949"),
    ]:
        ax.plot(positions, contrast_values(full, state), marker="o", linewidth=2.4,
                markersize=6, color=color, label=label)
    ax.axhline(0, color="#555", linewidth=1)
    ax.set_xticks(positions, [f"P{p}" for p in periods])
    ax.set_ylim(-0.4, 0.68)
    ax.set_xlabel("B1 stripe period in source pixels")
    ax.set_ylabel("Michelson contrast in captured Y")
    ax.set_title("Three-frame capture measurement; sign reversal is at the P2 patch")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.text(0.5, 0.025,
             "B1 uses vertical stripes, so its P2 patch tests horizontal spatial frequency. "
             "This FE85 phase observation comes from the 3-frame sweep; it was not part of the 9-frame repeat.",
             ha="center", fontsize=9, color="#444")
    fig.savefig(OUT / "fe85-phase-response.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def luma_figure() -> None:
    native = load_result("native-1080/result.json")
    scaled = load_result("scaled-1080-to-720/result.json")
    states = [
        ("1080p baseline", native, "baseline", "native-1080/baseline.yuy2", 1920, 1080),
        ("FE8E.0: 00→01", native, "FE8E.0", "native-1080/probe-14-FE8E0.yuy2", 1920, 1080),
        ("FE8E.4: 00→10", native, "FE8E.4", "native-1080/probe-15-FE8E4.yuy2", 1920, 1080),
        ("720p baseline", scaled, "baseline", "scaled-1080-to-720/baseline.yuy2", 1280, 720),
        ("720p FE8F.0: 00→01", scaled, "FE8F.0", "scaled-1080-to-720/probe-16-FE8F0.yuy2", 1280, 720),
    ]
    field_boxes = {
        "Black": (1100, 1020, 1245, 1048),
        "Gray": (1400, 1020, 1545, 1048),
        "White": (1700, 1020, 1845, 1048),
    }

    fig, axes = plt.subplots(len(states), 3, figsize=(16, 10))
    fig.subplots_adjust(top=0.88, bottom=0.09, left=0.22, right=0.98, hspace=0.50, wspace=0.04)
    fig.suptitle("Captured evidence: FE8E and FE8F alter flat-field luma levels", fontsize=18, y=0.985)
    fig.text(0.5, 0.94,
             "Each cell is a crop from the device capture. All crops use one fixed 0–255 display mapping; "
             "numbers are measured mean Y codes.", ha="center", fontsize=10)
    for row, (label, document, state, capture, width, height) in enumerate(states):
        image = capture_y(capture, width, height)
        # These rectangles are the generator's black, gray and white flat-field ROIs.
        values = flat_values(document, state)
        sx, sy = width / 1920, height / 1080
        for col, (field, (x0, y0, x1, y1)) in enumerate(field_boxes.items()):
            bounds = (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))
            ax = axes[row, col]
            add_image_crop(ax, image, bounds, vmin=0, vmax=255)
            ax.set_title(f"{field}: mean Y {values[field.lower()]:.1f}", fontsize=9, pad=3)
            if col == 0:
                ax.set_ylabel(label, rotation=0, ha="right", va="center", labelpad=100, fontsize=10)
    fig.text(0.5, 0.025,
             "FE8E.0 raises native black/gray/white by about 18 codes; FE8E.4 compresses the native range. "
             "FE8F.0 shows a level change in the 720p path. These are end-to-end capture values.",
             ha="center", fontsize=9, color="#444")
    fig.savefig(OUT / "luma-levels.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def corner_figure() -> None:
    native_result = load_result("corner-geometry-native/result.json")
    scaled_result = load_result("corner-geometry-scaled/result.json")
    captures = [
        ("Native 1080p baseline", "corner-geometry-native/baseline.yuy2", 1920, 1080),
        ("Native 1080p FE84=40", "corner-geometry-native/candidate-01-FE84-40.yuy2", 1920, 1080),
        ("720p output baseline", "corner-geometry-scaled/baseline.yuy2", 1280, 720),
        ("720p output FE84=40", "corner-geometry-scaled/candidate-01-FE84-40.yuy2", 1280, 720),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.subplots_adjust(top=0.88, bottom=0.13, left=0.06, right=0.98, hspace=0.35, wspace=0.10)
    fig.suptitle("Captured evidence: FE84 did not move the four corner markers", fontsize=18, y=0.985)
    fig.text(0.5, 0.94,
             "Full captured frames from the corner chart; all four markers are inside the output raster.",
             ha="center", fontsize=10)
    for ax, (label, capture, width, height) in zip(axes.flat, captures):
        image = capture_y(capture, width, height)
        ax.imshow(image, cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        ax.set_title(label, fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#555")
    native_base = native_result["baseline_geometry"]["per_frame_viewport_fit"][0]
    scaled_base = scaled_result["baseline_geometry"]["per_frame_viewport_fit"][0]
    fig.text(0.5, 0.045,
             f"Native fit: scale 1.000, offset (0, 0), predicted overflow 0 px.  "
             f"720p fit: scale 1.000, offset ({scaled_base['horizontal_offset_px']:.2f}, "
             f"{scaled_base['vertical_offset_px']:.2f}) px; predicted right/bottom rounding at most 1 px.  "
             f"FE84 candidates match the baseline marker coordinates. Analyzer tolerance: 2 px.",
             ha="center", fontsize=9, color="#444")
    fig.savefig(OUT / "corner-geometry.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    detail_figure()
    luma_figure()
    corner_figure()
    for path in sorted(OUT.glob("*.png")):
        print(path)


if __name__ == "__main__":
    main()
