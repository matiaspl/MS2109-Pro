# MS2109 automatic range calibration

The tool measured 24 brightness/contrast/saturation combinations on the
attached MS2109 at 1920×1080. The best measured balance was **UI brightness
110 (signed −18), contrast 149, saturation 147, hue 0**. Original USB YUY2
and JPEG YCbCr both gave patch-median ranges **Y 0–255, Cb 1–254, Cr 1–254**.
The starting controls, UI 128/128/128 and hue 0, were restored. Three fresh
AVFoundation frames matched the original YUY2 baseline patch medians exactly.

The complete generated [report](report.html),
[result JSON](result.json),
[candidate table](candidates.csv)
and [plots](ramps.svg)
preserve the measured settings and tradeoffs.

## Findings

| Setting, unsigned UI B/C/S | Gray Y | Cb/Cr patch-median coverage | Consequence |
|---|---|---|---|
| 128/128/128 | 16–235 | 16–238.5 YUY2; JPEG Cr max 239 | Original limited baseline |
| 113/128/128 | 1–220 | Same as baseline | A 15-step brightness drop shifts endpoints without widening the span |
| 110/149/128 | 0–255 | Same as baseline | Full-span luma, limited chroma |
| 110/149/147 | 0–255 | 1–254 in both formats | Best measured balance for a full YCbCr target |
| 110/149/148 or 149 | 0–255 | 1–254 in both formats | Same chroma coverage, more numerical error and longer endpoint plateaus |
| 110/150/147 | 0–255 | 1–254 in both formats | More clipping and worse luma fidelity |

The tool fitted a local control response from the neutral baseline, a
15-step brightness shift, and an eight-step contrast increase. Brightness
changed gray by one Y code per step. The model predicted B≈110.95/C≈149.11;
the measured neighborhood selected B110/C149. Saturation was tested from
143 through 149, followed by four luma refinements with the selected S147.
The worse of the two transport scores sets each candidate's loss. The
loss includes endpoint deficits, BT.709 numeric RMSE, early clipping and
collapsed endpoint steps; it is recorded alongside the raw measurements.

At the selected settings, YUY2 Y/Cb/Cr RMSE against full-range BT.709 was
0.565/1.036/1.055 codes. MJPEG was 0.533/1.026/1.043. Their patch medians
differed by 0.128 YUV codes RMS. No gray input above the scoring tolerance
was prematurely clipped; one non-gray patch component met the early-clipping
criterion. Maximum temporal patch-median variation was 0 YUY2 and 0.5 JPEG.

Range is distinct from precision. YUY2 had 234 distinct gray medians, 220
rounded median codes and 255 spatial-distribution signatures. MJPEG had
220 distinct gray patch values and 36 unchanged adjacent input pairs.
The range expansion therefore does not provide 256 independently resolved
JPEG gray values. Saturation 147–149 reaching the same 1–254 endpoints
suggests a ceiling in this neighborhood; a global hardware clamp remains
unverified.

## Metadata and headers

The baseline remained closest to BT.709 limited: 0.860 YUV codes RMS versus
2.997 for BT.2020 limited and 7.281 for BT.601 limited. This supports correcting
the UVC matrix declaration to BT.709 for this source/mode. It does not identify
physical primaries or an OETF independently. The prior live UVC descriptors
declared primaries/transfer/matrix 1/1/4, and the color descriptor has no
quantization-range field; see the earlier color and transport reports.

Every captured JPEG decoded without warnings and contained the DQT and DHT
tables referenced by its SOF0/SOS records. Its samples are 4:2:2. No JFIF,
Adobe or ICC marker was present. Missing coding tables are therefore not the
color failure here. A JFIF marker has no selectable BT.709 matrix field
([ITU-T T.871](https://www.itu.int/rec/T-REC-T.871-201105-I/en)); FFmpeg initializes
its MJPEG decoder with BT.470BG/BT.601-family color assumptions
([decoder source](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/mjpegdec.c)).
Matrix and range need an explicitly verified consumer or container path.
No descriptor/header patch was flashed during calibration.

## Tool and validation

- `tools/calibrate_colors.py`: chart, search, direct YCbCr analysis, scoring,
  result/report output and file-only replay.
- `tools/calibrate_uvc_server.c`: fixed-device, bounded privileged acquisition;
  original controls restored after each sample and at session completion.
- `tools/run_capture_video_uvc_admin.m`: one native authentication prompt,
  unprivileged chart presentation, rights destroyed on completion.
- `tools/test_calibrate_colors.py`: five file-only checks for clipped-ramp
  rejection, mixed/full chroma scoring, response prediction, chart extrema,
  and missing JPEG Huffman-table detection.
- `tools/plot_calibration.py`: ReportLab SVG/PDF plots.

The first run stopped after one complete baseline sample because the Python
analyzer attempted to save a CSV in a root-owned raw-frame directory. Its
session journal confirms successful restoration and closure. The corrected
tool saves analysis in the user-owned run directory. The second run completed
24 candidates, with three frames per format: **144 original USB frames**.
All response journals verify starting-control restoration. The normal UVC
driver then captured three fresh frames; baseline patch-median RMSE was 0.
File-only redecoding of all 144 raw payloads reproduced the recommendations.

Acquisition ran outside the macOS shell sandbox. No EEPROM/firmware writes
or global display-setting changes were made. True Tone and Night Shift were
disabled by the user before this calibration; both had been enabled during
the older baseline. The source reference is the AppKit chart render before
late compositor/HDMI processing. HDMI wire codes, physical primaries and
transfer were not independently measured. Seven ramps and 128 mixed colors
do not exhaust all 16.7 million RGB triplets or all control combinations.

The run contains source-render reference, ICC profile, inventories, original
payloads, control readbacks, capture/analysis source snapshots, executable
hashes and a final SHA-256 manifest. The hardware sources under `sources`
describe acquisition; `analysis-sources` records the subsequent file-only
analysis/report/plot revisions.
