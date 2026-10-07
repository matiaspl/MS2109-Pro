# MS2109 live color probe

Measured 2026-10-05–06, Europe/Warsaw. The probe displays a 96-patch chart on the Mac's **HDMI TO USB extended display, 1920×1080**, and acquires the attached **usb video, 534d:2109** device. Acquisition ran outside the macOS shell sandbox.

The baseline establishes two separate effects: **neutral gray acquires a yellow cast**, and the **decoded 1080p path adds another full-to-limited level conversion relative to native YUY2**. The user confirms that **both True Tone and Night Shift were enabled throughout this baseline**. Both were disabled only when the user subsequently said "disabled night shift and true tone". The later repeat with both disabled identifies BT.709 limited-range samples; see the follow-up report linked below.

## Measured evidence

| Property | Native capture | Decoded capture |
|---|---|---|
| AVFoundation active device format | `yuvs`, 1920×1080 at 5 fps | `420v`, 1920×1080 at approximately 30 fps |
| Delivered/saved pixel format | `yuvs`, packed YUY2 | `2vuy`, packed UYVY |
| Frames used | 8 | 8 |
| Intended black, measured Y/Cb/Cr | **16 / 128 / 128** | **30 / 128 / 128** |
| Intended white, measured Y/Cb/Cr | **215 / 104 / 139** | **201 / 107 / 138** |
| Red, measured Y/Cb/Cr | 60 / 103 / 233 | 68 / 106 / 220 |
| Green, measured Y/Cb/Cr | 170 / 43 / 68 | 162 / 53 / 75 |
| Blue, measured Y/Cb/Cr | 53 / 194 / 121 | 62 / 186 / 122 |

Native results: [capture metadata](../artifacts/color-probe/run-20261006-verified/native-yuv/capture.json), [measured CSV](../artifacts/color-probe/run-20261006-verified/native-yuv/patches.csv), [analysis](../artifacts/color-probe/run-20261006-verified/native-yuv/analysis.json). Decoded results: [metadata](../artifacts/color-probe/run-20261006-decoded/native-avf420v/capture.json), [CSV](../artifacts/color-probe/run-20261006-decoded/native-avf420v/patches.csv), [analysis](../artifacts/color-probe/run-20261006-decoded/native-avf420v/analysis.json).

### F-white-point: colored neutral gray

Status: measured. Confidence: high for sample values; attribution to an individual Mac adjustment remains unisolated. Evidence: E-native, E-macos-state.

Both 601 and 709 leave neutral gray at Cb=Cr=128. The measured white has Cb=104 and Cr=139, so changing only the inverse matrix cannot restore neutral white. With an explicit 709 limited-range inverse it becomes approximately RGB **251 / 231 / 181**, a substantial blue deficit.

The user confirms **both True Tone and Night Shift were enabled** during these captures. The read-only CoreBrightness query reports True Tone enabled but its `BlueReductionEnabled` field reports zero even during this known enabled baseline. Mapping a private API dictionary field does not validate whether its flag reflects the active visual effect. The earlier claim that Night Shift was off was therefore unsupported; these readings are retained as API observations and must not override the user's state timeline. Strength 0.5 / 4100 K are configured settings. The cast is consistent with white-point processing while both adjustments were enabled; the captures do not isolate their individual contributions. No white-point setting was changed by the probe.

### F-levels: another range compression in the decoded path

Status: measured relationship between acquisition paths. Confidence: high. Evidence: E-native, E-decoded, E-transport-fit.

Across all 96 identical native-profile patches, the decoded values match this transformation of the native values:

```text
Ydecoded  ≈ 16 + (219/255) · Ynative
Cbdecoded ≈ 128 + (224/255) · (Cbnative − 128)
Crdecoded ≈ 128 + (224/255) · (Crnative − 128)
```

The predicted relationship has **0.294 YUV code values RMS error**, compared with **5.453** for identical values. Independently fitted slopes are 0.859025 for Y and 0.878278 / 0.878213 for Cb / Cr, closely matching 219/255 and 224/255. [Paired samples and fitted coefficients](../artifacts/color-probe/transport-comparison.json) preserve the calculation.

This raises black from 16 to approximately 30 and reduces the luma/chroma excursion again. A consumer that interprets the delivered packed buffer as ordinary limited-range video can therefore show lifted blacks and reduced contrast/saturation. This is an end-to-end finding: the probe has not retained the compressed USB JPEG payload, so it does not localize the extra conversion to the chip's JPEG samples or the host decoder. The `420v` active format is an AVFoundation delivered format; it is not a raw USB MJPEG recording.

### F-metadata: the host's color declaration differs between paths

Status: observed. Confidence: high for returned attachments; no proof of a corresponding pixel transform. Evidence: E-native, E-decoded, E-rom-report.

For the final native capture, AVFoundation attaches **ITU_R_709_2 primaries and matrix**, **SMPTE_240M_1995 transfer**, and a QuickTime `nclc` profile `(1,7,1)`. The decoded capture instead has a **Composite NTSC** RGB color-space attachment and no explicit YCbCr-matrix attachment in the saved propagated dictionary.

The [offline ROM analysis](2026-10-05_reverse-ms2109-color-report.md) found UVC declarations of 709 primaries/transfer and a 601 matrix. The actual AVFoundation declarations consequently cannot be assumed to reproduce the saved UVC bytes. The probe saves numeric YUV before any RGB inverse and compares explicit matrices; it does not use these ICC attachments to produce its diagnostic previews.

### F-matrix: clean matrix identification is still pending

Status: unresolved in this historical baseline; resolved for the later neutral-source repeat. Evidence: E-native, E-srgb, E-macos-state.

| Candidate | Native-profile direct YUV RMSE | sRGB direct YUV RMSE |
|---|---:|---:|
| 601 limited | 13.178 | 11.916 |
| 709 limited | **12.716** | 11.936 |
| 2020 limited | 12.972 | 12.016 |
| 601 full | 17.174 | 15.467 |
| 709 full | 17.475 | 16.392 |
| 2020 full | 17.548 | 16.258 |

These residuals are too large, and the 601/709 separation too small, to establish a clean isolated matrix choice with white-point processing active. The analyzer also reports a constrained model with separate source RGB gains and a held-out subset. It deliberately does not rank matrices by an arbitrary 3×3 affine fit, because that fit can absorb the difference between any invertible standard matrices.

## Source control and validation

The borderless chart window is verified on the external display at frame `{-1920,0,1920,1080}`, with scale 1. The built-in display remains the main display. The chart contains a 32-step gray ramp, primaries and secondaries at four levels, mixed/skin colors, and reproducible pseudorandom RGB triplets. Only the center 40×40 pixels of each 160×135 patch enter the measurements.

Two rendering modes distinguish application color management: `native` tags the patches with the active **HDMI TO USB** ICC profile; `srgb` tags them with sRGB and predicts the ColorSync conversion to that display profile. The saved AppKit render matches the native references exactly, and the sRGB-to-display references within **0.288 RGB codes RMS**. The source-render PNG is a reference before late compositor/HDMI processing. Screen Recording permission was absent, so no ScreenCaptureKit framebuffer screenshot was acquired. The on-wire HDMI RGB/YCbCr format and range were not independently read.

The median of each patch was stable across all eight frames: maximum temporal median span **0 codes**. The largest spatial 95th-minus-5th percentile interior spread in the native acquisition was **2 codes**. The analyzer rejects incomplete recordings, unsupported channel packing, inconsistent source renders, black/stale frames, and captured content that fails to match the chart.

Current picture controls remained **brightness 0, contrast 128, saturation 128, hue 0**. Before/after HID reads match exactly. The probe reads those values through the existing HID helper; it does not call its register-writing methods. No firmware, EEPROM, picture controls, global display mode, profile, or white-point setting was changed. Capture-session format negotiation is temporary.

An early AVFoundation startup replaced the requested format; subsequent runs retain the device configuration lock and verify actual format and duration. A later acquisition with CoreBrightness status queries inside the capture process produced black buffers. Those recordings were rejected. Status observation now runs in a separate short-lived process, and the completed wrapper passed native and decoded acquisitions. The underlying cause of those black buffers was not isolated. Endpoint color equations and both UYVY/YUY2 packing orders were independently checked against known reference values.

## Reproduce

Use the same connected HDMI display and grabber. Temporarily turn off **True Tone and Night Shift** for the next measurement. Select fresh output directories; the acquisition command refuses to overwrite an existing directory.

From `/Users/mstarzak/Documents/ChatGPT/ms2901-patches`, outside the shell sandbox:

```sh
python3 tools/probe_colors.py run --output artifacts/color-probe/clean-yuy2
python3 tools/probe_colors.py run --output artifacts/color-probe/clean-decoded --spaces native --transport avf420v
python3 tools/probe_colors.py compare artifacts/color-probe/clean-yuy2/native-yuv artifacts/color-probe/clean-decoded/native-avf420v --output artifacts/color-probe/clean-transport-comparison.json
```

Requirements: macOS with Xcode command-line tools, Python with NumPy and Pillow, and the workspace's existing HIDAPI dependency for the picture-control snapshot. The wrapper compiles [the native acquisition helper](../tools/color_probe_macos.m) into a temporary directory. [The analyzer/wrapper](../tools/probe_colors.py) saves source/profile references, eight raw packed frames per pass, attachments, measured CSV/JSON tables, six explicit inverse previews, a report, and SHA256 manifests.

Offline re-analysis never opens the device:

```sh
python3 tools/probe_colors.py analyze artifacts/color-probe/run-20261006-verified/native-yuv artifacts/color-probe/run-20261006-verified/srgb-yuv --output artifacts/color-probe/run-20261006-verified
```

[Gray-ramp plot](../artifacts/color-probe/gray-ramp.svg) and [source/native/decoded comparison](../artifacts/color-probe/source-native-decoded.png) present the measurements. The image uses an explicit 709 limited inverse for both captures as a diagnostic comparison; it does not establish that this is the correct final display transform.

## Evidence index

- E-native: `artifacts/color-probe/run-20261006-verified/native-yuv/` raw frames, metadata, source render/profile, CSV and analysis.
- E-srgb: `artifacts/color-probe/run-20261006-verified/srgb-yuv/` equivalent sRGB-source pass.
- E-decoded: `artifacts/color-probe/run-20261006-decoded/native-avf420v/` decoded-path recording.
- E-macos-state: `macos_color_state` and `macos_color_state_end` in each final capture JSON, with private API type encoding and raw status bytes; before/after picture controls in each run's root.
- E-transport-fit: `artifacts/color-probe/transport-comparison.json`.
- E-rom-report: earlier offline report linked above.
- E-integrity: per-run `sha256.json`, plus `artifacts/color-probe/sha256.json` for the report and source artifacts.

Matrix/range definitions: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). Configuration-lock sequence: [FFmpeg AVFoundation source](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m). macOS APIs were checked against the locally installed Xcode SDK headers.

## Neutral-source follow-up

The [uncompressed/MJPEG follow-up](2026-10-06_uncompressed-mjpeg-color-report.md) records the repeat after the user disabled True Tone and Night Shift. It supersedes this baseline matrix uncertainty and documents the corrected Night Shift status interpretation.
