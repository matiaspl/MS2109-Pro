#!/usr/bin/env python3
"""Build offline FE85 native-mode summaries and separate SVG plots."""
import argparse
import hashlib
import html
import json
from pathlib import Path

import numpy as np

from analyze_scaler_roi import roi_slice


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/scaler-f9a0"
FINE_DIR = ART / "native-fe85-1080-fine-20261007"
COARSE_DIR = ART / "native-fe85-1080-sweep-20261007"
SESSION = ART / "chart-session-fe85-native-20261007b"
SIZE = (1920, 1080)
FRAME_BYTES = SIZE[0] * SIZE[1] * 2
CHART_ROIS = (("B1 vertical bars", 4), ("C1 grids", 4))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_y(path):
    raw = Path(path).read_bytes()
    if not raw or len(raw) % FRAME_BYTES:
        raise ValueError(f"Invalid native YUY2 payload: {path}")
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, SIZE[1], SIZE[0], 2)[..., 0].copy()
    return raw, frames


def shifted_mae(measured, reference, dx):
    """Compare measured to a reference shifted by dx columns; positive dx is rightward."""
    if dx > 0:
        left, right = measured[:, :, dx:], reference[None, :, :-dx]
    elif dx < 0:
        left, right = measured[:, :, :dx], reference[None, :, -dx:]
    else:
        left, right = measured, reference[None, ...]
    return float(np.abs(left.astype(np.int16) - right.astype(np.int16)).mean())


def phase_diagnostic(frames, source, roi_name, pitch):
    ys, xs = roi_slice(roi_name, 4, SIZE)
    measured = frames[:, ys, xs]
    reference = source[ys, xs]
    scores = {str(dx): round(shifted_mae(measured, reference, dx), 6)
              for dx in range(-2, 3)}
    minimum = min(scores.values())
    best = [int(dx) for dx, value in scores.items() if value <= minimum + 1e-9]
    return {
        "roi": roi_name,
        "pitch_px": pitch,
        "mae_by_reference_shift_px": scores,
        "best_reference_shifts_px": best,
        "minimum_absolute_shift_px": min(abs(dx) for dx in best),
        "zero_shift_mae": scores["0"],
        "best_shift_mae": round(minimum, 6),
    }


def svg_plot(title, y_label, values, key_fn, y_max, caption):
    width, height = 1040, 390
    left, right, top, bottom = 90, 28, 56, 86
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(values)
    x = lambda i: left + (i / max(n - 1, 1)) * plot_w
    y = lambda value: top + plot_h - (value / y_max) * plot_h
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
           f'<title id="title">{html.escape(title)}</title>',
           f'<desc id="desc">{html.escape(caption)}</desc>',
           '<rect x="0" y="0" width="100%" height="100%" fill="#fff"/>',
           f'<text x="{left}" y="28" fill="#17202a" font-family="sans-serif" font-size="20" font-weight="600">{html.escape(title)}</text>']
    for tick in np.linspace(0, y_max, 5):
        yy = y(float(tick))
        out.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{width-right}" y2="{yy:.2f}" stroke="#d8dee8" stroke-width="1"/>')
        out.append(f'<text x="{left-12}" y="{yy+5:.2f}" text-anchor="end" fill="#3f4b5b" font-family="sans-serif" font-size="13">{tick:g}</text>')
    tick_indices = sorted(set([0, 4, 8, 12, 16, 20, 24, 28, 32] + list(range(33, n))))
    for index in tick_indices:
        if index >= n:
            continue
        xx = x(index)
        out.append(f'<line x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{height-bottom}" stroke="#edf0f3" stroke-width="1"/>')
        out.append(f'<text x="{xx:.2f}" y="{height-bottom+23}" text-anchor="middle" fill="#3f4b5b" font-family="monospace" font-size="12">{values[index]["FE85"]}</text>')
    out.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#677381" stroke-width="1"/>')
    out.append(f'<text x="{left + plot_w/2:.2f}" y="{height-16}" text-anchor="middle" fill="#263238" font-family="sans-serif" font-size="14">FE85 byte (categorical test order)</text>')
    out.append(f'<text x="20" y="{top + plot_h/2:.2f}" transform="rotate(-90 20 {top + plot_h/2:.2f})" text-anchor="middle" fill="#263238" font-family="sans-serif" font-size="14">{html.escape(y_label)}</text>')
    points = [(x(i), y(float(key_fn(item))), item) for i, item in enumerate(values)]
    out.append('<polyline points="' + ' '.join(f'{px:.2f},{py:.2f}' for px, py, _ in points) + '" fill="none" stroke="#2364aa" stroke-width="2.2"/>')
    for px, py, item in points:
        val = float(key_fn(item))
        marker_title = f'FE85=0x{item["FE85"]}; FE85 bit 1={int(item["bit1_set"])}; {y_label}={val:g}'
        if item["bit1_set"]:
            shape = f'<path d="M {px:.2f} {py-5:.2f} L {px+5:.2f} {py+4:.2f} L {px-5:.2f} {py+4:.2f} Z" fill="#b23a48" stroke="#fff" stroke-width="1"><title>{html.escape(marker_title)}</title></path>'
        else:
            shape = f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4.4" fill="#2364aa" stroke="#fff" stroke-width="1"><title>{html.escape(marker_title)}</title></circle>'
        out.append(shape)
    out.append(f'<text x="{width-right-210}" y="{top+17}" fill="#2364aa" font-family="sans-serif" font-size="12">○ bit 1 clear</text>')
    out.append(f'<text x="{width-right-105}" y="{top+17}" fill="#b23a48" font-family="sans-serif" font-size="12">△ set</text>')
    out.append('</svg>')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"refusing to overwrite non-empty directory: {args.output_dir}")

    fine_path = FINE_DIR / "result.json"
    coarse_path = COARSE_DIR / "result.json"
    fine, coarse = json.loads(fine_path.read_text()), json.loads(coarse_path.read_text())
    if not fine.get("eeprom_unchanged") or not coarse.get("eeprom_unchanged"):
        raise RuntimeError("A source sweep does not record unchanged EEPROM")
    if fine.get("FE84_target") != "40" or coarse.get("FE84_target") != "40":
        raise RuntimeError("Source sweep was not run with FE84=40")
    source_render_path = SESSION / "source-render.png"
    source_render_bytes = source_render_path.read_bytes()
    from PIL import Image
    source = np.asarray(Image.open(source_render_path).convert("L"), dtype=np.uint8)
    if source.shape != SIZE[::-1]:
        raise ValueError("Expected a 1920x1080 source-render image")

    by_value = {}
    for directory, result in ((COARSE_DIR, coarse), (FINE_DIR, fine)):
        for state in result["states"]:
            value = state["FE85"]
            path = directory / f"fe85-{value}-1920x1080.yuy2"
            raw, frames = load_y(path)
            if sha(raw) != state["raw_sha256"]:
                raise RuntimeError(f"Capture hash mismatch for FE85={value}")
            b1 = phase_diagnostic(frames, source, "B1 vertical bars", 2)
            c1 = phase_diagnostic(frames, source, "C1 grids", 1)
            item = {
                "FE85": value,
                "bit1_set": bool(int(value, 16) & 0x02),
                "capture": str(path.relative_to(ROOT)),
                "raw_sha256": state["raw_sha256"],
                "reference_model_scores": state["reference_model_scores"],
                "rois": state["rois"],
                "flat_fields": state["flat_fields"],
                "edge_A": state["edge_A"],
                "phase": {"B1_vertical_bars_2px": b1, "C1_grid_1px": c1},
                "repeat_count": state["frame_count"],
            }
            by_value[value] = item

    states = sorted(by_value.values(), key=lambda item: int(item["FE85"], 16))
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    level_direct = svg_plot(
        "Direct AppKit code reference", "full-frame MAE (Y codes)", states,
        lambda item: item["reference_model_scores"]["direct_full_range_codes"]["outside_top_right_20x20_overlay"]["mae_y_codes"],
        10,
        "Mean absolute error outside the top-right overlay against the AppKit source render interpreted directly as captured Y.")
    level_limited = svg_plot(
        "Full-to-limited Y reference", "full-frame MAE (Y codes)", states,
        lambda item: item["reference_model_scores"]["full_to_limited_y"]["outside_top_right_20x20_overlay"]["mae_y_codes"],
        20,
        "Mean absolute error outside the top-right overlay against Y = 16 + floor(219 × RGB / 255).")
    b1_plot = svg_plot(
        "B1 vertical bars, 2 px pitch", "ROI MAE (Y codes)", states,
        lambda item: item["rois"]["B1 vertical bars"]["2"]["vs_reference_models"]["direct_full_range_codes"]["mae_y_codes"],
        120,
        "Pixelwise error in the 2-pixel vertical-bar ROI against direct AppKit codes. A one-pixel phase shift flips alternating bars.")
    c1_plot = svg_plot(
        "C1 one-pixel grid", "ROI MAE (Y codes)", states,
        lambda item: item["rois"]["C1 grids"]["1"]["vs_reference_models"]["direct_full_range_codes"]["mae_y_codes"],
        240,
        "Pixelwise error in the one-pixel grid ROI against direct AppKit codes. A one-pixel phase shift changes the checkerboard phase.")

    for filename, svg in (("fe85-level-direct.svg", level_direct),
                          ("fe85-level-limited.svg", level_limited),
                          ("fe85-b1-bars.svg", b1_plot),
                          ("fe85-c1-grid.svg", c1_plot)):
        (output / filename).write_text(svg + "\n")

    initial_state = fine["before"]
    flat00 = by_value["00"]["flat_fields"]
    flat_rows = []
    for key, value in flat00.items():
        flat_rows.append({
            "source_render_direct_y": value["expected_direct_y"],
            "full_to_limited_y": value["expected_limited_y"],
            "captured_mean_y_at_FE85_00": value["measured"]["mean_y"],
            "captured_std_y_at_FE85_00": value["measured"]["std_y"],
        })
    no_phase_values = [item["FE85"] for item in states
                       if item["bit1_set"] is False and
                       item["phase"]["B1_vertical_bars_2px"]["minimum_absolute_shift_px"] == 0 and
                       item["phase"]["C1_grid_1px"]["minimum_absolute_shift_px"] == 0]
    phase_values = [item["FE85"] for item in states if item["bit1_set"]]
    data = {
        "test": "FE85 native 1920x1080-to-1920x1080 with FE84=40",
        "source_render": str(source_render_path.relative_to(ROOT)),
        "source_render_sha256": sha(source_render_bytes),
        "fine_sweep_result": {"path": str(fine_path.relative_to(ROOT)), "sha256": sha(fine_path.read_bytes())},
        "coarse_sweep_result": {"path": str(coarse_path.relative_to(ROOT)), "sha256": sha(coarse_path.read_bytes())},
        "EEPROM_SHA256": fine["eeprom_before_sha256"],
        "EEPROM_unchanged": fine["eeprom_unchanged"] and coarse["eeprom_unchanged"],
        "before": initial_state,
        "restored": fine.get("restored"),
        "tested_values": [item["FE85"] for item in states],
        "native_phase_aligned_FE85_values": no_phase_values,
        "FE85_bit1_set_values": phase_values,
        "flat_field_comparison_at_FE85_00": flat_rows,
        "range_model_finding": {
            "direct_full_range_codes": by_value["00"]["reference_model_scores"]["direct_full_range_codes"]["outside_top_right_20x20_overlay"],
            "full_to_limited_y": by_value["00"]["reference_model_scores"]["full_to_limited_y"]["outside_top_right_20x20_overlay"],
            "interpretation": "The fresh FE85=00 run fits direct AppKit codes. The older saved FE84=40 run fits the full-to-limited model. Keep capture range mode attached to each comparison; AppKit is not an HDMI framebuffer reference.",
        },
        "recommendation": {
            "FE84": "40",
            "FE85": "00",
            "status": "reference candidate, not unique optimum",
            "reason": "FE85=00 has zero pixelwise B1 2px ROI error, minimum C1 1px grid error among phase-aligned values, and matches the ROM-cleared bit-1 state. FE85=20 reduces full-frame direct-code MAE by only about 0.016 Y code while slightly worsening those detail ROIs.",
        },
        "states": states,
    }
    json_path = output / "native-fe85-1080-analysis.json"
    json_path.write_text(json.dumps(data, indent=2) + "\n")

    svg_names = ["fe85-level-direct.svg", "fe85-level-limited.svg",
                 "fe85-b1-bars.svg", "fe85-c1-grid.svg"]
    figures = []
    for filename, caption in zip(svg_names, (
        "Direct code fit. A low value indicates a closer full-frame match under the direct-code interpretation.",
        "Limited-range fit. Kept separate because this model is not equivalent to direct code matching.",
        "A one-pixel phase reversal creates a large error in alternating 2px bars.",
        "A one-pixel shift changes the phase of this 1px checkerboard.",
    )):
        svg = (output / filename).read_text()
        figures.append(f'<figure><figcaption>{html.escape(caption)}</figcaption>{svg}</figure>')

    direct = data["range_model_finding"]["direct_full_range_codes"]
    limited = data["range_model_finding"]["full_to_limited_y"]
    html_doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MS2109 FE85 native 1080p sweep</title>
<style>
body{{margin:0;padding:24px clamp(16px,4vw,56px);font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17202a;background:#fff}}
main{{max-width:1200px;margin:0 auto}}h1{{margin:0 0 8px;font-size:clamp(24px,3vw,34px)}}h2{{margin:28px 0 8px;font-size:21px}}p{{max-width:1000px}}.note{{border-left:4px solid #2364aa;padding:10px 14px;background:#f3f6fa}}.plots{{display:grid;grid-template-columns:1fr;gap:22px}}figure{{margin:0}}figcaption{{margin:0 0 6px;color:#3f4b5b}}svg{{display:block;width:100%;height:auto}}table{{border-collapse:collapse;margin:10px 0 22px}}th,td{{padding:7px 12px;border-bottom:1px solid #d8dee8;text-align:left;font-variant-numeric:tabular-nums}}code{{font-family:ui-monospace,SFMono-Regular,monospace}}@media(min-width:1000px){{.plots{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<h1>FE85 at native 1080p → 1080p, with FE84=0x40</h1>
<p class="note"><strong>Best reference candidate: FE85=0x00.</strong> It preserves the chart phase in the 2px bars and 1px grid. The measured direct-code full-frame MAE is {direct['mae_y_codes']:.3f} Y codes; the limited-range model gives {limited['mae_y_codes']:.3f}. The 0x20 full-frame score is lower by only about 0.016 code, while its detail ROIs are slightly less exact, so this does not establish a unique optimum.</p>
<p>Across 0x00–0x20, FE85 bit 1 set produced a repeatable one-pixel phase change in both high-frequency ROIs. The ROM clears that bit during video setup. The two level models remain separate: this fresh run fits direct AppKit codes, while the earlier saved FE84=0x40 run fit full-to-limited Y.</p>
<p>Markers: ○ FE85 bit 1 clear; △ FE85 bit 1 set. Each plot uses the same categorical candidate order: every byte 0x00–0x20, followed by 0x40, 0x80 and 0xFF.</p>
<div class="plots">{''.join(figures)}</div>
<h2>Flat-field levels at FE85=0x00</h2><table><thead><tr><th>Direct source-render Y</th><th>Full→limited model Y</th><th>Captured mean Y</th><th>Captured σ</th></tr></thead><tbody>{''.join(f'<tr><td>{row["source_render_direct_y"]}</td><td>{row["full_to_limited_y"]}</td><td>{row["captured_mean_y_at_FE85_00"]:.3f}</td><td>{row["captured_std_y_at_FE85_00"]:.3f}</td></tr>' for row in flat_rows)}</tbody></table>
<p>All writes were RAM-only. FE84/FE85, procamp controls and UVC shadows were restored; EEPROM SHA-256 remained {data["EEPROM_SHA256"]}.</p>
</main></body></html>'''
    html_path = output / "native-fe85-1080-dashboard.html"
    html_path.write_text(html_doc)
    print(json.dumps({"dashboard": str(html_path), "data": str(json_path),
                      "tested_values": len(states), "phase_values": phase_values,
                      "native_phase_aligned": no_phase_values,
                      "FE85_00_direct_mae": direct["mae_y_codes"],
                      "FE85_00_limited_mae": limited["mae_y_codes"]}, indent=2))


if __name__ == "__main__":
    main()
