#!/usr/bin/env python3
"""Generate a fixed grayscale scaler/ringing target for the MS2109 live test."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1920, 1080
DEFAULT_OUT = Path("artifacts/scaler-f9a0/test-chart-1920x1080.png")
BLACK, WHITE, MID = (16, 16, 16), (235, 235, 235), (128, 128, 128)


def font(size=24):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT,
                        help="new PNG path; a JSON manifest is written beside it")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    args = parser.parse_args()
    out = args.output
    meta = out.with_suffix(".json")
    width, height = args.width, args.height
    if width < 640 or height < 360 or width * 9 != height * 16:
        parser.error("--width/--height must be a 16:9 raster of at least 640x360")
    sx, sy = width / DEFAULT_WIDTH, height / DEFAULT_HEIGHT
    X = lambda v: int(round(v * sx))
    Y = lambda v: int(round(v * sy))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() or meta.exists():
        raise SystemExit(f"Refusing to overwrite {out} or {meta}")
    image = Image.new("RGB", (width, height), MID)
    d = ImageDraw.Draw(image)
    f = font(max(12, X(24)))
    small = font(max(10, X(18)))
    d.rectangle((0, 0, width - 1, Y(74)), fill=(32, 32, 32))
    d.text((X(32), Y(21)), f"MS2109 scaler / ringing target   |   {width} × {height}   |   grayscale 16–235", font=f, fill=WHITE)

    # Slanted hard edges. The 0.1 px/row slope provides subpixel edge phases.
    # Each ROI includes a long uniform black and white plateau for edge overshoot.
    rois = []
    for box, base, edge_color, x0, slope, direction, label in (
        ((48, 112, 900, 1016), BLACK, WHITE, 468, 0.10, "dark-to-light", "A  Slanted edge: dark → light"),
        ((1018, 112, 1872, 200), WHITE, BLACK, 1450, -0.10, "light-to-dark", "B  Slanted edge: light → dark"),
    ):
        x1, y1, x2, y2 = box
        x1, y1, x2, y2 = X(x1), Y(y1), X(x2), Y(y2)
        origin_x, slope_px_per_row = X(x0), slope * sx / sy
        d.rectangle((x1, y1, x2, y2), fill=base)
        if direction == "dark-to-light":
            points = [(origin_x + slope_px_per_row * (y1 - Y(112)), y1), (x2, y1), (x2, y2), (origin_x + slope_px_per_row * (y2 - Y(112)), y2)]
        else:
            points = [(x1, y1), (origin_x + slope_px_per_row * (y1 - Y(112)), y1), (origin_x + slope_px_per_row * (y2 - Y(112)), y2), (x1, y2)]
        d.polygon(points, fill=edge_color)
        d.rectangle((x1, y1, x2, y2), outline=(200, 200, 200), width=max(1, X(2)))
        d.text((x1 + X(16), y1 + Y(14)), label, font=small, fill=WHITE if base == BLACK else BLACK)
        rois.append({"label": label, "bounds_xyxy": [x1, y1, x2, y2], "edge_origin_x": origin_x, "edge_slope_px_per_row": slope_px_per_row})

    # Resolution wedges: alternating 16/8/4/2/1 source-pixel vertical and
    # horizontal bars, in separated cells so frequency response is comparable.
    d.text((X(1040), Y(170)), "B1  Vertical line pairs (source pixels)", font=small, fill=BLACK)
    for i, period in enumerate((32, 16, 8, 4, 2)):
        x = X(1040 + i * 158)
        patch_width = X(140)
        y0, y2 = Y(220), Y(400)
        d.rectangle((x, y0, x + patch_width, y2), fill=MID)
        for xx in range(x, x + patch_width):
            if ((xx - x) // max(1, period // 2)) % 2 == 0:
                d.line((xx, y0 + Y(8), xx, y2 - Y(8)), fill=WHITE, width=1)
        d.text((x + X(4), y2 + Y(3)), f"P{period}", font=small, fill=BLACK)

    # Horizontal line pairs sample vertical resampling independently of B1.
    # This row occupies the right-column space previously used by a redundant
    # third slanted edge; the other two edge polarities remain represented.
    d.text((X(1040), Y(432)), "B2  Horizontal line pairs (source pixels)", font=small, fill=BLACK)
    for i, period in enumerate((32, 16, 8, 4, 2)):
        x = X(1040 + i * 158)
        patch_width = X(140)
        y0, y2 = Y(458), Y(554)
        d.rectangle((x, y0, x + patch_width, y2), fill=MID)
        for yy in range(y0, y2):
            if ((yy - y0) // max(1, period // 2)) % 2 == 0:
                d.line((x + X(8), yy, x + X(132), yy), fill=WHITE, width=1)
        d.text((x + X(4), y2 + Y(3)), f"P{period}", font=small, fill=BLACK)

    # Square grids with controlled cell pitch and one-source-pixel strokes.
    d.text((X(1040), Y(666)), "C1  One-pixel grid patches   |   cell pitch in source pixels", font=small, fill=BLACK)
    for i, pitch in enumerate((16, 8, 4, 2, 1)):
        x = X(1040 + i * 158)
        y0, y2, x2 = Y(704), Y(958), x + X(140)
        d.rectangle((x, y0, x2, y2), fill=BLACK)
        if pitch == 1:
            # 1-pixel checkerboard (2-pixel full cycle) is the Nyquist patch.
            for yy in range(y0, y2):
                for xx in range(x, x2):
                    if (xx + yy) & 1:
                        image.putpixel((xx, yy), WHITE)
        else:
            for xx in range(x, x2 + 1, pitch):
                d.line((xx, y0, xx, y2), fill=WHITE, width=1)
            for yy in range(y0, y2 + 1, pitch):
                d.line((x, yy, x2, yy), fill=WHITE, width=1)
        d.text((x + X(4), y2 + Y(5)), "1px checker" if pitch == 1 else f"{pitch}px", font=small, fill=BLACK)

    # Large, flat reference fields for checking setup stability and exact luma.
    flat_fields = []
    for x0, x1, name, color in (
        (1018, 1270, "black", BLACK), (1318, 1570, "gray", MID),
        (1618, 1870, "white", WHITE),
    ):
        box = (X(x0), Y(986), X(x1), Y(1057))
        d.rectangle(box, fill=color, outline=(32, 32, 32), width=max(1, X(1)))
        d.text((box[0] + X(8), box[1] + Y(8)), name, font=small,
               fill=WHITE if color == BLACK else BLACK)
        flat_fields.append({"name": name, "bounds_xyxy": list(box), "rgb": list(color)})

    # Registration guides; do not use the one-pixel border as the edge ROI.
    d.rectangle((X(16), Y(88), width - X(17), height - Y(17)), outline=(240, 240, 240), width=max(1, X(2)))
    d.line((X(960), Y(88), X(960), height - Y(18)), fill=(96, 96, 96), width=1)
    image.save(out, format="PNG", optimize=False)
    meta.write_text(json.dumps({
        "image": str(out), "width": width, "height": height,
        "levels_rgb": {"black": BLACK, "white": WHITE, "mid": MID},
        "edge_rois": rois,
        "frequency_patches": [32, 16, 8, 4, 2, 1],
        "line_pair_patches": {"vertical": [32, 16, 8, 4, 2], "horizontal": [32, 16, 8, 4, 2]},
        "flat_fields": flat_fields,
        "note": "Exact geometry is recorded here. Display at native raster dimensions without browser scaling or image interpolation for strongest measurement.",
    }, indent=2) + "\n")
    print(json.dumps({"image": str(out), "metadata": str(meta), "size": image.size}, indent=2))


if __name__ == "__main__":
    main()
