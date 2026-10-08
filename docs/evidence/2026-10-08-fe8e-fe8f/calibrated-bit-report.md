# MS2109 FE8E/FE8F color-patch probe

Capture date: 2026-10-08T11:45:19.120969+00:00

Paired raw MJPEG and YUY2 captures used one persistent UVC handle. After each format started, the capture process used its active libusb handle for HID feature reports, read the mode baseline, toggled one volatile XDATA bit, and sampled it during frames. Each chart contains 256-step gray, red, green, blue, cyan, magenta and yellow ramps plus 128 mixed-color patches.

EEPROM SHA-256 before/after: 2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5 / 2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5. Unchanged: **True**. EEPROM writes: **0**.

FE80-FE8F before/after: 01 00 00 00 7A 00 01 00 11 00 00 00 00 00 00 00 / 01 00 00 00 7A 00 01 00 11 00 00 00 00 00 00 00. FE8E/FE8F restored to pre-run bytes: **True**.

## Measured response

| RAM bit | YUY2 gray ΔY | MJPEG gray ΔY | YUY2 gray slope Δ | MJPEG gray slope Δ | YUY2 chroma RMS | MJPEG chroma RMS | frame windows covered |
|---|---:|---:|---:|---:|---:|---:|:---:|
| FE8E.0 | 18.000 | 18.000 | -0.014941 | -0.014902 | 0.054 | 0.096 | True |
| FE8E.4 | -20.000 | -20.000 | -0.141738 | -0.141797 | 0.054 | 0.090 | True |
| FE8F.0 | 0.000 | 0.000 | 0.000000 | 0.000000 | 7.230 | 7.231 | True |
| FE8F.4 | 0.000 | 0.000 | 0.000000 | 0.000000 | 0.593 | 0.610 | True |

## Likely behavior from the patch response

| RAM bit | Gray ΔY at codes 0 / 32 / 128 / 255 | Y slope ratio vs baseline | Mean Cb/Cr axis gain | YUY2 / MJPEG agreement |
|---|---|---:|---:|:---:|
| FE8E.0 | 18.0 / 18.0 / 18.0 / 0.0 | 0.9851 | 1.0000 | True |
| FE8E.4 | 0.0 / -7.0 / -20.0 / -38.0 | 0.8583 | 1.0000 | True |
| FE8F.0 | 0.0 / 0.0 / 0.0 / 0.0 | 1.0000 | 0.8702 | True |
| FE8F.4 | 0.0 / 0.0 / 0.0 / 0.0 | 1.0000 | 1.0080 | True |

FE8E.0 adds about 18 luma codes until white clips, with virtually no chroma change; that behaves like a brightness or black-level offset. FE8E.4 increasingly lowers luma as input code rises (slope ratio about 0.858), with no measurable chroma mapping change; that behaves like contrast/gain. FE8F.0 leaves luma and neutral grays unchanged while scaling both chroma axes to about 0.870 of baseline with negligible cross-axis coupling; this is consistent with a saturation/chroma-gain control, not a hue rotation. FE8F.4 produces only about a 0.8% chroma gain, near one-code changes. The YUY2 and MJPEG fits agree closely. These are observed effects of the tested bits; register names and full byte semantics remain unproven.

## Interpreting the effect

A nearly constant gray-ramp ΔY with little slope change is consistent with a luma offset or black-level path. A changed gray-ramp slope points toward gain, contrast, or nonlinear luma mapping. Chroma changes that vary across color groups are consistent with a saturation, matrix, or channel-mix path. These are behavioral interpretations only; FE8E/FE8F field names remain unresolved.

A bit counts as active for a format only when every saved frame timestamp is bracketed by register samples retaining the readback value. Mode-by-mode FE80-FE8F snapshots and raw measurements remain in analysis.json.

## Evidence

- color-patch-format-previews.png: captured YUY2/MJPEG images decoded through the same BT.709 full-range preview transform.
- fe8e-fe8f-color-response.png: measured gray-ramp curves and color-patch chroma changes relative to baseline.
- analysis.json: register hook events, sampled values, per-format patch medians, temporal spread, and frame coverage.
- analysis/*-patches.csv: measured Y/Cb/Cr values and per-patch deltas.
- trials/*/raw/same-handle/{mjpeg,yuy2}/frame-*: original USB payloads.
- register-recovery.json: RAM restoration journal.

The preview transform provides one consistent view of the captured YCbCr values. It does not identify the hardware matrix or quantization range.
