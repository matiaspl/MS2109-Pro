# MS2109 automatic range calibration

Measured 24 settings; original controls restored: **True**.

The search scores coverage, BT.709 numeric fidelity, early clipping and collapsed endpoint steps. Both original USB transports are measured; the worse transport sets the loss.

## Luma with original saturation

Brightness UI **110** (signed UVC -18), contrast **149**, saturation **128**, hue 0.

| Transport | Gray Y | Cb | Cr | Gray median levels | Early clipped gray inputs | Target Y/Cb/Cr RMSE |
|---|---|---|---|---:|---:|---|
| yuy2 | 0…255 | 16…238.5 | 16…238.5 | 234 | 0 | 0.565 / 0.985 / 0.987 |
| mjpeg | 0…255 | 16…238.5 | 16…239 | 220 | 0 | 0.533 / 0.978 / 0.971 |

## Full YCbCr target

Brightness UI **110** (signed UVC -18), contrast **149**, saturation **147**, hue 0.

| Transport | Gray Y | Cb | Cr | Gray median levels | Early clipped gray inputs | Target Y/Cb/Cr RMSE |
|---|---|---|---|---:|---:|---|
| yuy2 | 0…255 | 1…254 | 1…254 | 234 | 0 | 0.565 / 1.036 / 1.055 |
| mjpeg | 0…255 | 1…254 | 1…254 | 220 | 0 | 0.533 / 1.026 / 1.043 |

Saturation 147, 148, 149 gave the same chroma endpoints as the winner. Increasing saturation within that group did not expand coverage. This is evidence of a ceiling within the measured neighborhood, not proof of a global hardware clamp.

Calibrated luma produced 220 distinct MJPEG gray patch values. YUY2 had 234 distinct gray medians, 220 rounded median codes and 255 spatial-distribution signatures. Endpoint coverage and input-code precision are separate measurements.

Three fresh normal-driver AVFoundation frames were captured after releasing USB. Patch-median RMSE against the original YUY2 baseline: **0.000000**.

## Color declarations and JPEG headers

Baseline numeric models, best first: BT.709 limited: 0.860 YUV codes RMS; BT.2020 limited: 2.997 YUV codes RMS; BT.601 limited: 7.281 YUV codes RMS.

The original JPEG frames contain the quantization and Huffman tables referenced by their scan. The tool reports marker inventories without modifying frames.

The baseline matrix/range model is measured numerically. Physical primaries and transfer are not identified by this test. JFIF's color model does not provide a BT.709 matrix declaration ([ITU-T T.871](https://www.itu.int/rec/T-REC-T.871-201105-I/en)). FFmpeg's MJPEG decoder starts with BT.601-family color assumptions ([source](https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/mjpegdec.c)). Consumer range/matrix handling must be tested independently of firmware descriptor edits.

## Validation boundaries

- Best among measured candidates in a local search; not all 256 cubed control settings.
- RGB reference is the AppKit source render before compositor/HDMI; HDMI wire codes and physical primaries/OETF are not measured.
- Seven 256-code ramps plus 128 mixed patches; not all 16.7 million RGB triplets.
- Stretching a quantized signal cannot restore lost input precision.
- Original USB samples only; AVFoundation's MJPEG decode/range conversion is a separate path.

No firmware writes; recommended controls were not left applied. Raw frames, readbacks, source chart/profile, source snapshots and SHA-256 hashes accompany this result.
