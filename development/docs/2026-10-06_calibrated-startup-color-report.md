# Calibrated firmware after USB reconnect

The user's reconnect loaded the calibrated MS2109 firmware. Complete EEPROM
and running-code readbacks match image SHA256
`83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.
Startup controls are **brightness UI 110 / signed −18, contrast 149,
saturation 147, hue 0**. Both high-speed video formats enumerate BT.709
matrix value 1, with primaries/transfer 1/1. FE60 remains 01.

The numeric YUV buffers closely follow the calibrated target. Automatic
host RGB conversion still applies unsuitable matrix/range assumptions.
This qualifies the firmware's startup and the tested buffer paths; it does
not establish universal correct color reproduction in capture applications.

## Cold-start checks

The [initial readback](../artifacts/color-firmware/20261006/device-after-reconnect.json)
confirmed all of the following before the new captures:

- Complete EEPROM, loaded header and all 1950 code bytes match the image.
- Current controls C6A0–C6A7: `EE FF 95 00 00 00 93 00`.
- Hardware controls FE90–FE93: `EE 95 93 00`.
- Both RAM color records: `06 24 0D 01 01 01`.
- FE60=01 and F002=01.

The [active USB configuration](../artifacts/color-firmware/20261006/enumerated-color-descriptors.json)
independently exposes both formats with primaries/transfer/matrix 1/1/1.
The [final readback](../artifacts/color-firmware/20261006/device-after-steady-check.json)
confirms the same firmware, controls and routing after acquisition.
No further EEPROM or firmware writes were performed.

## Normal driver and automatic RGB conversion

Eight stable frames were acquired per path using the same 96-patch chart
on the 1920×1080 extended HDMI TO USB display. An independent repeat after
raw capture reproduced the original YUY2 patch medians exactly. A separate
observer then captured one unchanged chart through both YUV paths and both
automatic BGRA outputs, eight frames each.

| Path | Delivered YUV | Black/white Y | Best numeric model | Direct YUV RMSE | Automatic host RGB RMSE |
|---|---|---|---|---:|---:|
| Uncompressed, 5 fps | `yuvs` | 0 / 255 | BT.709 full | 0.800 | 8.549 |
| Decoded MJPEG, 30 fps | `2vuy`, active subtype `420v` | 16 / 235 | BT.709 limited | 0.740 | 7.266 |

Errors are code-value RMS residuals against the source reference, not
perceptual ΔE. Patch medians were temporally identical in these captures.
Explicit BT.709 inverses have RGB residuals 1.546 and 1.628 respectively.

The automatic uncompressed RGB output matches a clipped **BT.709 limited**
inverse of its full-range YUV buffer within **0.364 RGB codes RMS**. This
wrong range assumption clips shadows/highlights and expands contrast.
The automatic decoded-MJPEG RGB output matches a clipped **BT.601 limited**
inverse within **0.399 RGB codes RMS**. This wrong matrix changes colors.
These are numeric matches to the actual BGRA bytes, not deductions from
an attachment alone.

The uncompressed attachment still reports BT.709 primaries/matrix and
SMPTE 240M transfer, with QuickTime `nclc` (1,7,1). Decoded MJPEG still
attaches a Composite NTSC RGB space without an explicit YCbCr matrix in
the saved propagated dictionary. Correct USB declarations therefore do
not establish correct host color management.

Use an explicit **BT.709 full-range** inverse for the measured original
samples and native YUY2 buffer. Use **BT.709 limited-range** for the tested
AVFoundation decoded-MJPEG packed buffer. Its limited-range endpoints now
fit the reference; undoing that range conversion is unnecessary before a
BT.709 limited inverse. Every application still needs its actual input
buffer path checked.

[Shared-chart YUV analysis](../artifacts/color-probe/20261006-calibrated-startup-shared-chart/yuv-analysis/analysis.json)
· [actual RGB analysis and patch values](../artifacts/color-probe/20261006-calibrated-startup-shared-chart/rgb-analysis.json)
· [first native capture](../artifacts/color-probe/20261006-calibrated-startup-yuy2/native-yuv/analysis.json)
· [first decoded capture](../artifacts/color-probe/20261006-calibrated-startup-decoded/native-avf420v/analysis.json)

## Original payload and quantization repeat

A steady libuvc handle acquired three original YUY2 frames and three JPEG
frames of the automatic calibration chart: seven 256-step ramps
(gray, R, G, B, C, M, Y) and 128 mixed patches. It explicitly reapplied the
same current B110/C149/S147 values before recording and restored them
afterward. This repeat is separate from the initial cold-start readback
and normal-driver captures, which did not set picture controls.

| Format | Y median range | Cb median range | Cr median range | Target Y / Cb / Cr RMSE | Distinct gray medians |
|---|---|---|---|---|---:|
| Original YUY2 | 0–255 | 1–254 | 1–254 | 0.565 / 1.036 / 1.055 | 234 |
| Original MJPEG | 0–255 | 1–254 | 1–254 | 0.533 / 1.025 / 1.043 | 220 |

YUY2 patch medians exactly equal the original selected calibration sample
17. JPEG differs by 0.019 YUV codes RMS, with a maximum difference of
0.5. YUY2 has 220 rounded gray median codes and 255 distinct spatial
distribution signatures. JPEG has 36 collapsed adjacent gray steps.
Neither gray ramp has nonmonotonic steps or false clipping outside the
configured endpoint tolerance. Full coverage still does not mean 256
independent levels survived JPEG quantization.

The JPEG audit finds the referenced quantization/Huffman tables present.
libjpeg emits no warnings; the frames use 4:2:2 sampling and contain no
JFIF, Adobe or ICC marker. Ordinary Pillow RGB decoding has **8.733 RGB
codes RMS error** and matches a clipped BT.601/full inverse within 0.223.
An explicit BT.709/full inverse reduces this chart's residual to 1.754.
No JPEG payload or header was modified.

[Raw sample analysis](../artifacts/color-probe/20261006-calibrated-startup-steady/sample-000.json)
· [successful restoration journal](../artifacts/color-probe/20261006-calibrated-startup-steady/usb/session.json)
· [summary and comparison to sample 17](../artifacts/color-probe/20261006-calibrated-startup-summary.json)

The acquisition orchestrator had a reporting bug: after saving both
formats and their analysis, a progress print used the wrong JSON key and
exited 1. Its cleanup completed; the privileged server reports exit 0,
one completed sample, restored controls and a closed UVC handle. The
planned second repaint sample was not executed. This is retained in the
summary so the command's exit status is not presented as a clean run.

## Unmatched initial raw capture

The first direct USB attempt recorded eight frames of each format. Its
black/white endpoints were 0/255, but its midtones and colors differed
from normal-driver captures: YUY2 patch-median difference **7.367 YUV
codes RMS**. JPEG and YUY2 from that attempt agreed within 0.223. Saved
source images and ICC profiles were byte-identical to the normal captures,
and subsequent HID readbacks showed unchanged firmware and controls.

The normal-driver repeat and shared-chart observer remained identical to
the initial normal capture. The steady-handle calibration repeat then
reproduced the earlier selected calibration. The first raw discrepancy's
cause is **not isolated**. Different chart geometry, control reapplication
and driver claim conditions prevent treating the steady repeat as a
controlled explanation of that discrepancy.

That attempt is retained as evidence and excluded from paired raw-to-host
decoder attribution. The updated analyzer marks its saved-file replay
`paired_capture_samples_agree=false`; it does not label the difference as
a decoder range conversion.

[Unmatched capture replay](../artifacts/color-probe/20261006-calibrated-startup-usb-analysis-v2/analysis.json)

## Boundaries and reproduction

All USB/AVFoundation acquisition ran outside the macOS shell sandbox.
Analysis and previews used saved files. The source reference is the AppKit
render in the display ICC space, before late compositor/HDMI processing;
the on-wire HDMI format/range and physical primaries/OETF were not
independently measured. True Tone and Night Shift were user-disabled for
these checks. They were both enabled in the older baseline, before the
user's stated disablement.

ROM `GET_DEF` still returns −11/148/0/180, and the other-speed descriptor
is unchanged. Apps that reset controls can replace the calibrated startup.
The UVC color record has no range declaration. No fresh audio waveform
was acquired; preserved FE60 and audio descriptor/code readbacks do not
replace an acoustic/channel acceptance test.

Read-only startup verification, with a fresh output name:

```sh
rtk proxy python3 tools/verify_color_startup.py --image artifacts/ms2109-calibrated-stereo-channel-order.bin --output artifacts/new-startup-check.json
```

Normal YUV measurements, outside the sandbox:

```sh
rtk proxy python3 tools/probe_colors.py run --output artifacts/color-probe/new-calibrated-yuy2 --spaces native --frames 8 --transport yuv
rtk proxy python3 tools/probe_colors.py run --output artifacts/color-probe/new-calibrated-decoded --spaces native --frames 8 --transport avf420v
```

The chart helper additionally accepts `--pixel-format bgra` to save actual
host RGB bytes and `--observe-source DIRECTORY` to observe an existing
chart without opening a second window. The latter requires the matching
source metadata and unchanged display ICC profile. Acquisition commands
and source/binary hashes are retained with the shared-chart artifacts.
The USB analyzer accepts `--usb-range full`; its default remains limited
for historical neutral captures. Explicit full/limited inverse equivalence
was checked numerically, and the final helper compiled successfully.

The firmware image remains unchanged from the previously tested build.
Its eight offline tests are recorded in the firmware evidence package.
