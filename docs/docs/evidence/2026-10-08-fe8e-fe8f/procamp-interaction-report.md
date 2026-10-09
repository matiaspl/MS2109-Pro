# FE8E and UVC procamp interaction probe

Run started: 2026-10-08T17:21:49.750431+00:00

The Mac-generated 1080p chart was presented through HDMI while the MS2109 produced raw YUY2 and MJPEG captures. Each candidate control was SET_CUR while the corresponding FE8E value was live, checked with GET_CUR, and then captured with that same FE8E state active during streaming. FE8F stayed at 0x00.

EEPROM SHA-256 before/after: `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5` / `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`. Unchanged: **True**. EEPROM writes: **0**.

FE8E/FE8F initial/restored: `0000` / `0000`. Controls restored: **True**. Procamp RAM restored: **True**.

## Chart and range check

The saved preview initially used a full-range YCbCr decode. The MS2109 stream uses limited-range BT.709, so that preview made the colors look wrong. The corrected preview and contact sheets use limited-range BT.709. At native resolution the chart contains 1,920 32×32 patches; each contact-sheet tile scales them to about 5×5 pixels.

The neutral FE8E=`00` capture matches the expected display RGB at the patch centers:

| Format | Patch centers | Limited BT.709 YCbCr RMSE | Decoded RGB RMSE |
|---|---:|---:|---:|
| YUY2 | 1920 | 0.768 | 1.638 |
| MJPEG | 1920 | 0.744 | 1.576 |

## Patch presence across the sweep

A fit on alternating patch centers predicts the held-out centers with 0.42–1.81 YCbCr-code RMSE across the other 19 conditions in both formats. FE8E=`10` contrast 160 is the outlier (27.95 YUY2, 27.89 MJPEG); those frames do not contain the expected patch chart.

## Capture stability

The acceptance threshold was a maximum temporal patch span of 2 Y/Cb/Cr codes. These captures exceeded it and their effect estimates should be treated as lower-confidence:

| FE8E | Profile | Format | Max temporal span (codes) |
|---:|---|---|---:|
| `10` | contrast_160 | YUY2 | 143.0000 |
| `10` | contrast_160 | MJPEG | 4.5000 |

The FE8E=`10`, contrast 160 capture also visibly contains non-chart geometric content in the saved stream; one YUY2 frame shows the expected chart only as a smaller inset. Treat both contrast measurements at this state as invalid. See `fe8e10-contrast-yuy2-mjpeg-frames.png`.

## Measured change from neutral

Each value below compares a one-control change with the neutral control capture at the same FE8E state. Brightness is median gray-ramp ΔY; contrast is gray-ramp slope ratio; hue is fitted Cb/Cr rotation; saturation is fitted chroma gain.

| FE8E | Control | YUY2 effect | MJPEG effect |
|---:|---|---:|---:|
| `00` | brightness gray ΔY | 32.0 | 32.0 |
| `00` | contrast slope ratio | 1.182483 | 1.182171 |
| `00` | hue rotation ° | -45.0522 | -45.05 |
| `00` | saturation chroma gain | 1.242528 | 1.242571 |
| `01` | brightness gray ΔY | 0.0 | 0.0 |
| `01` | contrast slope ratio | 1.182483 | 1.182171 |
| `01` | hue rotation ° | -45.0525 | -45.0464 |
| `01` | saturation chroma gain | 1.242528 | 1.242571 |
| `10` | brightness gray ΔY | 32.0 | 32.0 |
| `10` | contrast slope ratio | invalid: source unstable | invalid: source unstable |
| `10` | hue rotation ° | -45.0525 | -45.05 |
| `10` | saturation chroma gain | 1.242528 | 1.242587 |
| `11` | brightness gray ΔY | 0.0 | 0.0 |
| `11` | contrast slope ratio | 1.0 | 1.0 |
| `11` | hue rotation ° | -45.0522 | -45.0464 |
| `11` | saturation chroma gain | 1.242528 | 1.242571 |

## Interpretation

These results do not show the whole procamp being disabled: hue and saturation changes remain visible at every FE8E state. Brightness +32 shifted the gray median by 32 Y codes at FE8E=`00`/`10`, but by 0 at `01`/`11`, which correlates with FE8E bit 0. Contrast changed the gray-ramp slope by about 18% at `00`/`01`; it showed no change at `11`. The `10` contrast capture is invalid, so a bit-4 contrast gate remains a hypothesis that needs a clean repeat.

## Evidence

- `yuy2-interaction-contact-sheet.png` and `mjpeg-interaction-contact-sheet.png` summarize all 20 captures; the FE8E=`10` contrast capture is invalid as noted above.
- `fe00-neutral-yuy2-limited-preview.png` and `fe00-neutral-mjpeg-limited-preview.png` show full-resolution previews decoded as limited-range BT.709.
- `fe00-neutral-color-patch-detail.png` enlarges a native-resolution crop so the small patch grid can be inspected.
- `fe8e10-contrast-yuy2-mjpeg-frames.png` shows every frame from the unstable contrast condition in both formats.
- `procamp-effect-by-fe8e.png` plots each control's measured response at the four FE8E values.
- `measurements.json` contains per-patch samples and fitted response values.
- `trials/` contains original USB payloads, control requests, display snapshots, register readbacks, and runner logs.
- `register-recovery.json` contains the pre-run snapshot and recovery command.

No FE8E meaning is assigned by this interaction test. A near-zero output delta means the control had little visible effect under this input and output path; SET_CUR/GET_CUR success alone does not prove an image effect.

## Targeted repeat of the invalid FE8E=10 contrast capture (fe8e10-contrast-regenerated-r2)

A later, single-condition repeat is documented in [`fe8e10-contrast-regenerated-r2/report.md`](fe8e10-contrast-regenerated-r2/report.md). It passed captured-patch alignment and temporal-stability checks. Recovery status: `restored`; EEPROM unchanged: `True`.
