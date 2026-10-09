#!/usr/bin/env python3
"""Analyze chart-ROI luma histograms and edge ringing from saved YUY2 captures.

This offline report uses the matched 1280x720 FE84 pair and the saved FE85
1080p-input/720p-capture sweep. It reads capture files only; it never opens or
writes the USB device.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/scaler-f9a0"
CHART_720 = ART / "test-chart-bidirectional-v2-1280x720.png"
CHART_1080 = ART / "test-chart-bidirectional-v2-1920x1080.png"
FE84_DIR = ART / "fe84-matched-720-20261007"
FE85_DIR = ART / "fe85-scaled-resume-20261007"
SIZE_OUT = (1280, 720)
FE85_VALUES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xFF)
PITCHES = (16, 8, 4, 2, 1)
COLORS = {
    "source raster": (45, 45, 45),
    "ideal step": (45, 45, 45),
    "FE84=7A": (38, 105, 180),
    "FE84=40": (215, 91, 42),
    "FE85=00": (38, 105, 180),
    "FE85=02": (215, 91, 42),
    "FE85=40": (54, 145, 91),
    "FE85=FF": (142, 86, 166),
}


def gray_image(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    if not (np.array_equal(rgb[..., 0], rgb[..., 1]) and
            np.array_equal(rgb[..., 1], rgb[..., 2])):
        raise ValueError(f"Chart is not neutral grayscale: {path}")
    return rgb[..., 0]


def load_capture(path, width, height):
    raw = Path(path).read_bytes()
    frame_bytes = width * height * 2
    if len(raw) == 0 or len(raw) % frame_bytes:
        raise ValueError(f"Invalid YUY2 payload length for {path}: {len(raw)}")
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 2)
    return packed[..., 0].copy()


def read_chart_metadata(chart_path):
    metadata_path = Path(chart_path).with_suffix(".json")
    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)
    return json.loads(metadata_path.read_text())


def mapped_bounds(bounds, sx, sy):
    x0, y0, x1, y1 = bounds
    return (int(round(x0 * sx)), int(round(y0 * sy)),
            int(round(x1 * sx)), int(round(y1 * sy)))


def edge_profile(frames, source, edge_meta, out_size):
    """Build a phase-binned, plateau-normalized edge-spread profile."""
    out_w, out_h = out_size
    src_h, src_w = source.shape
    sx, sy = out_w / src_w, out_h / src_h
    bounds = edge_meta["bounds_xyxy"]
    x0, y0, x1, y1 = bounds
    y_lo = max(0, int(round(y0 * sy)) + (12 if (y1 - y0) * sy > 100 else 3))
    y_hi = min(out_h, int(round(y1 * sy)) - (12 if (y1 - y0) * sy > 100 else 3))
    averaged = frames.mean(axis=0) if frames.ndim == 3 else frames.astype(np.float64)
    probe_y = min(max(int(round((y0 + y1) / 2)), 0), src_h - 1)
    probe_expected = edge_meta["edge_origin_x"] + edge_meta["edge_slope_px_per_row"] * (probe_y - y0)
    probe = int(round(probe_expected))
    left_probe = source[probe_y, max(0, probe - 24):max(1, probe - 8)].astype(np.float64)
    right_probe = source[probe_y, min(src_w - 1, probe + 8):min(src_w, probe + 24)].astype(np.float64)
    polarity = "dark-to-light" if float(right_probe.mean()) > float(left_probe.mean()) else "light-to-dark"
    # A 0.25-pixel phase bin uses the slant to combine many scanlines.
    bin_width = 0.25
    half_window = 8.0
    bin_count = int(2 * half_window / bin_width)
    sums = np.zeros(bin_count, dtype=np.float64)
    counts = np.zeros(bin_count, dtype=np.int64)
    low_samples, high_samples = [], []
    for oy in range(y_lo, y_hi):
        source_y = int(round((oy + 0.5) / sy - 0.5))
        source_y = min(max(source_y, int(y0)), min(int(y1), src_h - 1))
        # Use the line's continuous vector geometry rather than the rasterized
        # staircase so the slant contributes subpixel edge phases.
        boundary_source = (edge_meta["edge_origin_x"] +
                           edge_meta["edge_slope_px_per_row"] * (source_y - y0))
        boundary_out = boundary_source * sx
        xs = np.arange(max(0, int(boundary_out - half_window - 1)),
                       min(out_w, int(boundary_out + half_window + 2)))
        rel = xs.astype(np.float64) + 0.5 - boundary_out
        if polarity == "light-to-dark":
            rel = -rel
        values = averaged[oy, xs]
        idx = np.floor((rel + half_window) / bin_width).astype(int)
        keep = (idx >= 0) & (idx < bin_count)
        np.add.at(sums, idx[keep], values[keep])
        np.add.at(counts, idx[keep], 1)
        left_x = np.arange(max(0, int(boundary_out - 24)), max(0, int(boundary_out - 8)))
        right_x = np.arange(min(out_w, int(boundary_out + 8)), min(out_w, int(boundary_out + 24)))
        if polarity == "dark-to-light":
            low_samples.extend(averaged[oy, left_x].tolist())
            high_samples.extend(averaged[oy, right_x].tolist())
        else:
            high_samples.extend(averaged[oy, left_x].tolist())
            low_samples.extend(averaged[oy, right_x].tolist())
    if not len(low_samples) or not len(high_samples):
        raise ValueError(f"Could not measure edge plateaus: {edge_meta['label']}")
    low, high = float(np.median(low_samples)), float(np.median(high_samples))
    profile = np.divide(sums, counts, out=np.full_like(sums, np.nan), where=counts > 0)
    normalized = (profile - low) / max(high - low, 1.0)
    centers = -half_window + (np.arange(bin_count) + 0.5) * bin_width
    return {
        "x_px": centers.tolist(),
        "normalized_y": normalized.tolist(),
        "low_plateau_y": low,
        "high_plateau_y": high,
        "overshoot_codes": round(max(0.0, float(np.nanmax(profile)) - high), 4),
        "undershoot_codes": round(max(0.0, low - float(np.nanmin(profile))), 4),
        "polarity": polarity,
        "chart_label": edge_meta["label"],
        "rows_used": int(y_hi - y_lo),
    }


ROI_SPECS = {
    "B1 vertical bars": (32, 16, 8, 4, 2),
    "B2 horizontal bars": (32, 16, 8, 4, 2),
    "C1 grids": (16, 8, 4, 2, 1),
}


def roi_slice(name, index, out_size):
    """Map a text-free chart ROI from the canonical 1920x1080 geometry."""
    out_w, out_h = out_size
    patch_x = 1040 + index * 158
    if name == "B1 vertical bars":
        bounds = (patch_x + 4, 220 + 8, patch_x + 136, 400 - 8)
    elif name == "B2 horizontal bars":
        bounds = (patch_x + 8, 458 + 4, patch_x + 132, 554 - 4)
    elif name == "C1 grids":
        bounds = (patch_x + 4, 704 + 4, patch_x + 136, 958 - 4)
    else:
        raise ValueError(f"Unknown chart ROI: {name}")
    x0, y0, x1, y1 = mapped_bounds(bounds, out_w / 1920, out_h / 1080)
    return slice(y0, y1), slice(x0, x1)


def normalized_histogram(samples, low, high, bins=48):
    edges = np.linspace(-0.12, 1.12, bins + 1)
    normalized = (samples.astype(np.float64) - low) / max(high - low, 1.0)
    counts, _ = np.histogram(normalized, bins=edges)
    mass = counts / max(int(normalized.size), 1)
    low_fraction = float(np.mean(normalized <= 0.25))
    mid_fraction = float(np.mean((normalized > 0.25) & (normalized < 0.75)))
    high_fraction = float(np.mean(normalized >= 0.75))
    return {
        "x": ((edges[:-1] + edges[1:]) / 2).tolist(),
        "mass": mass.tolist(),
        "low_fraction": round(low_fraction, 6),
        "mid_fraction": round(mid_fraction, 6),
        "high_fraction": round(high_fraction, 6),
        "sample_count": int(normalized.size),
    }


def profile_from_chart(source, edge_meta):
    result = edge_profile(source[None, ...], source, edge_meta,
                          (source.shape[1], source.shape[0]))
    return result


def font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Supplemental/Helvetica.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_plot(canvas, draw, box, title, x_label, y_label, series, x_range, y_range,
              x_ticks, y_ticks, legend=True):
    x0, y0, x1, y1 = box
    draw.text((x0, y0), title, fill=(20, 20, 20), font=font(22))
    left, top, right, bottom = x0 + 82, y0 + 42, x1 - 12, y1 - 56
    for tick in y_ticks:
        y = bottom - (tick - y_range[0]) / (y_range[1] - y_range[0]) * (bottom - top)
        draw.line((left, y, right, y), fill=(225, 225, 225), width=1)
        draw.text((x0 + 39, y - 9), f"{tick:g}", fill=(70, 70, 70), font=font(15))
    for tick in x_ticks:
        x = left + (tick - x_range[0]) / (x_range[1] - x_range[0]) * (right - left)
        draw.line((x, top, x, bottom), fill=(238, 238, 238), width=1)
        label = f"{tick:g}"
        draw.text((x - 14, bottom + 8), label, fill=(70, 70, 70), font=font(15))
    draw.rectangle((left, top, right, bottom), outline=(80, 80, 80), width=1)
    xfont = font(16)
    xlabel_width = draw.textbbox((0, 0), x_label, font=xfont)[2]
    draw.text(((left + right - xlabel_width) // 2, y1 - 26), x_label,
              fill=(40, 40, 40), font=xfont)
    vertical = Image.new("RGBA", (220, 24), (255, 255, 255, 0))
    ImageDraw.Draw(vertical).text((0, 0), y_label, fill=(40, 40, 40, 255), font=font(14))
    vertical = vertical.rotate(90, expand=True)
    canvas.paste(vertical, (x0 + 4, (top + bottom - vertical.height) // 2), vertical)
    for label, xs, ys, color, dashed in series:
        points = []
        for xv, yv in zip(xs, ys):
            if not np.isfinite(yv) or xv < x_range[0] or xv > x_range[1]:
                points.append(None)
                continue
            px = left + (xv - x_range[0]) / (x_range[1] - x_range[0]) * (right - left)
            py = bottom - (yv - y_range[0]) / (y_range[1] - y_range[0]) * (bottom - top)
            points.append((int(round(px)), int(round(py))))
        previous = None
        for index, point in enumerate(points):
            if point is None:
                previous = None
            elif previous is not None:
                if not dashed or (index % 4 < 2):
                    draw.line((previous, point), fill=color, width=3)
                previous = point
            else:
                previous = point
    if legend:
        lx, ly = left + 8, top + 8
        for label, _, _, color, _ in series:
            width = draw.textbbox((0, 0), label, font=font(14))[2]
            draw.line((lx, ly + 8, lx + 22, ly + 8), fill=color, width=3)
            draw.text((lx + 28, ly), label, fill=(25, 25, 25), font=font(14))
            lx += width + 52
            if lx > right - 120:
                lx, ly = left + 8, ly + 20


def pooled_bar_hist(group, label, pitch):
    """Pool B1/B2 bins by sample count for an orientation-neutral view."""
    first = group["roi_histograms"][label]["B1 vertical bars"][str(pitch)]
    second = group["roi_histograms"][label]["B2 horizontal bars"][str(pitch)]
    total = first["sample_count"] + second["sample_count"]
    mass = [
        (a * first["sample_count"] + b * second["sample_count"]) / total
        for a, b in zip(first["mass"], second["mass"])
    ]
    return {"x": first["x"], "mass": mass, "sample_count": total}


def histogram_series(group, roi_name, pitch, labels):
    series = []
    for label in labels:
        hist = group["roi_histograms"][label][roi_name][str(pitch)]
        series.append((label, hist["x"], hist["mass"], COLORS[label], label == "source raster"))
    return series


def bar_series(group, pitch, labels):
    series = []
    for label in labels:
        hist = pooled_bar_hist(group, label, pitch)
        series.append((label, hist["x"], hist["mass"], COLORS[label], label == "source raster"))
    return series


def draw_figure(result, output):
    image = Image.new("RGB", (1880, 1280), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.text((52, 24), "MS2109 ROI histograms and edge response",
              fill=(18, 18, 18), font=font(28))
    draw.text((52, 58), "Raw YUY2 luma; histograms count all samples in text-free grid/bar ROIs, independent of edge polarity.",
              fill=(70, 70, 70), font=font(16))

    fe84 = result["FE84_matched_720"]
    fe84_edges = fe84["dark_to_light_profiles"]
    series = []
    for label in ("source raster", "FE84=7A", "FE84=40"):
        p = fe84_edges[label]
        series.append((label, p["x_px"], p["normalized_y"], COLORS[label], label == "source raster"))
    draw_plot(image, draw, (52, 104, 918, 432), "FE84 at matched 720p: edge A response",
              "distance from edge (pixels)", "normalized Y", series,
              (-4, 4), (-0.12, 1.12), [-4, -2, 0, 2, 4], [0, 0.5, 1.0])

    fe85 = result["FE85_scaled_1080_to_720"]
    fe85_edges = fe85["dark_to_light_profiles"]
    series = []
    ideal_x = fe85_edges["FE85=00"]["x_px"]
    series.append(("ideal step", ideal_x, [0.0 if x < 0 else 1.0 for x in ideal_x], COLORS["ideal step"], True))
    for label in ("FE85=00", "FE85=02", "FE85=40", "FE85=FF"):
        p = fe85_edges[label]
        series.append((label, p["x_px"], p["normalized_y"], COLORS[label], False))
    draw_plot(image, draw, (950, 104, 1828, 432), "FE85 on 1080p→720p: edge A response",
              "distance from edge (pixels)", "normalized Y", series,
              (-4, 4), (-0.12, 1.12), [-4, -2, 0, 2, 4], [0, 0.5, 1.0])

    draw_plot(image, draw, (52, 456, 918, 812), "FE84: B1/B2 2px bar ROIs, pooled",
              "normalized luma", "sample fraction / bin",
              bar_series(fe84, 2, ("source raster", "FE84=7A", "FE84=40")),
              (-0.1, 1.1), (0, 1.0), [0, 0.25, 0.5, 0.75, 1], [0, 0.25, 0.5, 0.75, 1])
    draw_plot(image, draw, (950, 456, 1828, 812), "FE84: C1 1px checker grid ROI",
              "normalized luma", "sample fraction / bin",
              histogram_series(fe84, "C1 grids", 1, ("source raster", "FE84=7A", "FE84=40")),
              (-0.1, 1.1), (0, 1.0), [0, 0.25, 0.5, 0.75, 1], [0, 0.25, 0.5, 0.75, 1])

    draw_plot(image, draw, (52, 836, 918, 1192), "FE85: B1/B2 2px bar ROIs, pooled",
              "normalized luma", "sample fraction / bin",
              bar_series(fe85, 2, ("source raster", "FE85=00", "FE85=02", "FE85=40", "FE85=FF")),
              (-0.1, 1.1), (0, 1.0), [0, 0.25, 0.5, 0.75, 1], [0, 0.25, 0.5, 0.75, 1])
    draw_plot(image, draw, (950, 836, 1828, 1192), "FE85: C1 1px checker grid ROI",
              "normalized luma", "sample fraction / bin",
              histogram_series(fe85, "C1 grids", 1, ("source raster", "FE85=00", "FE85=02", "FE85=40", "FE85=FF")),
              (-0.1, 1.1), (0, 1.0), [0, 0.25, 0.5, 0.75, 1], [0, 0.25, 0.5, 0.75, 1])
    image.save(output, format="PNG", optimize=True)

def analyze_group(chart_path, capture_paths, frame_size, include_profiles):
    source = gray_image(chart_path)
    out_size = SIZE_OUT
    edges = read_chart_metadata(chart_path)["edge_rois"]
    rising = next(e for e in edges if "dark → light" in e["label"])
    secondary = edges[1] if len(edges) > 1 else edges[0]
    profiles = {}
    ringing = {}
    source_hists = {}
    capture_hists = {}

    for roi_name, pitches in ROI_SPECS.items():
        source_hists[roi_name] = {}
        for index, pitch in enumerate(pitches):
            ys, xs = roi_slice(roi_name, index, (source.shape[1], source.shape[0]))
            source_hists[roi_name][str(pitch)] = normalized_histogram(
                source[ys, xs], 16, 235)

    for label, path in capture_paths.items():
        frames = load_capture(path, *frame_size)
        if frames.shape[1:] != (out_size[1], out_size[0]):
            raise ValueError(f"Unexpected capture dimensions for {path}: {frames.shape[2]}x{frames.shape[1]}")
        if include_profiles:
            p = edge_profile(frames, source, rising, out_size)
            profiles[label] = p
            secondary_p = edge_profile(frames, source, secondary, out_size)
            ringing[label] = {
                "edge_A": {k: p[k] for k in ("polarity", "low_plateau_y", "high_plateau_y", "overshoot_codes", "undershoot_codes", "rows_used")},
                "edge_B_as_drawn": {k: secondary_p[k] for k in ("polarity", "low_plateau_y", "high_plateau_y", "overshoot_codes", "undershoot_codes", "rows_used")},
            }
        edge_data = edge_profile(frames, source, rising, out_size)
        capture_hists[label] = {}
        for roi_name, pitches in ROI_SPECS.items():
            capture_hists[label][roi_name] = {}
            for index, pitch in enumerate(pitches):
                ys, xs = roi_slice(roi_name, index, out_size)
                capture_hists[label][roi_name][str(pitch)] = normalized_histogram(
                    frames[:, ys, xs].ravel(),
                    edge_data["low_plateau_y"], edge_data["high_plateau_y"])

    source_profiles = {
        "edge_A": profile_from_chart(source, rising),
        "edge_B_as_drawn": profile_from_chart(source, secondary),
    }
    return {
        "chart": str(chart_path),
        "chart_size": [source.shape[1], source.shape[0]],
        "capture_size": list(out_size),
        "capture_modes": {label: str(path) for label, path in capture_paths.items()},
        "dark_to_light_profiles": {"source raster": source_profiles["edge_A"], **profiles},
        "secondary_source_edge_profile": source_profiles["edge_B_as_drawn"],
        "ringing_codes": ringing,
        "roi_histograms": {"source raster": source_hists, **capture_hists},
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    fe84_paths = {
        "FE84=7A": FE84_DIR / "fe84-7a-1280x720-matched.yuy2",
        "FE84=40": FE84_DIR / "fe84-40-1280x720-matched.yuy2",
    }
    fe85_paths = {
        f"FE85={value:02X}": FE85_DIR / f"fe85-{value:02x}-1280x720.yuy2"
        for value in FE85_VALUES
    }
    for path in [CHART_720, CHART_1080, *fe84_paths.values(), *fe85_paths.values()]:
        if not path.is_file():
            raise FileNotFoundError(path)

    fe84 = analyze_group(CHART_720, fe84_paths, SIZE_OUT, include_profiles=True)
    fe85_all = analyze_group(CHART_1080, fe85_paths, SIZE_OUT, include_profiles=True)
    selected = ("FE85=00", "FE85=02", "FE85=40", "FE85=FF")
    fe85 = dict(fe85_all)
    fe85["dark_to_light_profiles"] = {
        key: fe85_all["dark_to_light_profiles"][key]
        for key in ("source raster", *selected)
    }
    result = {
        "method": "Text-free rectangular ROI histograms of raw YUY2 luma, independent of edge polarity. B1 vertical bars, B2 horizontal bars, and C1 grid ROIs are normalized to measured black/white edge plateaus; source raster ROIs use nominal 16/235 levels. Edge-spread profiles use the chart's continuous slanted-edge geometry. This is not a direct HDMI framebuffer measurement.",
        "edge_note": "Both edge regions are dark-to-light in the chart raster. The second region label says light-to-dark, but its pixels are also dark-to-light; reverse-polarity ringing was not tested.",
        "FE84_matched_720": fe84,
        "FE85_scaled_1080_to_720": fe85,
    }
    json_path = output_dir / "roi-analysis.json"
    png_path = output_dir / "roi-histogram.png"
    json_path.write_text(json.dumps(result, indent=2) + "\n")
    draw_figure(result, png_path)

    def compact_fractions(group, labels):
        summary = {}
        for label in labels:
            summary[label] = {}
            for roi_name, pitch in (("B1 vertical bars", 2),
                                    ("B2 horizontal bars", 2),
                                    ("C1 grids", 1)):
                hist = group["roi_histograms"][label][roi_name][str(pitch)]
                summary[label][f"{roi_name}, pitch {pitch}"] = {
                    key: hist[key] for key in ("low_fraction", "mid_fraction", "high_fraction")
                }
        return summary

    print(json.dumps({
        "analysis": str(json_path),
        "figure": str(png_path),
        "FE84_ringing_codes": fe84["ringing_codes"],
        "FE84_roi_fractions": compact_fractions(fe84, ("source raster", "FE84=7A", "FE84=40")),
        "FE85_ringing_codes": fe85_all["ringing_codes"],
        "FE85_roi_fractions": compact_fractions(fe85, ("source raster", *selected)),
    }, indent=2))


if __name__ == "__main__":
    main()
