# MS2109 color firmware qualification

## Outcome

The current installed image remains unchanged at SHA256
`83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.
This is the selected option because it is the only image verified on the live
device. The offline v2 image keeps the same calibrated control values,
BT.709/full-span declarations, and FE60 setting; it only shares the guarded
matrix helper and uses 63 fewer code bytes. That saves EEPROM space but has no
demonstrated color-output gain over the installed image, so it is not selected
for flashing. The candidate is retained for offline review:

- `artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.bin`
- SHA256 `9de991c4f289c0d06b3997cf2b4775a088185871d8ac68eca6c72e90c38e8dfd`
- 1,887 code bytes; 109 bytes remain free in the existing 2 KiB EEPROM.
- Preserves startup brightness UI 110 (signed −18), contrast 149, saturation
  147, hue 0, the BT.709 matrix declarations, stereo descriptors, FE60=01,
  and the existing audio code. It shares one guarded matrix-patching routine
  between the two existing runtime patch points.

This candidate is **not flash-qualified**. It has not been written to the
device. It does not alter `GET_DEF`: the ROM handler still reports brightness
−11, contrast 148, hue 0, saturation 180. The requested calibrated defaults
are −18, 149, 0, 147. The ROM request code at `4DB4–4E13` prepares those replies
inside mask ROM and jumps directly to the EP0 response routine. The caller at
`6C6D–6C74` dispatches directly into that handler. The preserved USB interrupt
callback at `CC20` runs before that setup-request dispatch; it is not a
post-handler reply hook. No safe EEPROM interception point was established,
so the candidate does not fake a `GET_DEF` implementation.

The installed image already sets calibrated current controls in RAM and
hardware. A fresh post-capture readback confirms that the EEPROM and loaded
firmware still match SHA256
`83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`, with
current/hardware controls −18/149/147, both high-speed color records at
1/1/1, FE60=01, and F002=01. See
[`live-startup-after-reconnect.json`](../artifacts/color-firmware/20261006/qualification-live/live-startup-after-reconnect.json).
That readback does not qualify host RGB conversion.

## Signaling experiments

The original YUY2 USB GUID remains in place. The CoreVideo identifier `yuvf`
does not establish a USB GUID that Apple's UVC driver maps to full-range YUY2.
No supported alternate mapping was demonstrated, so no alias was added.
UVC's standard color-matching descriptor has matrix, primaries and transfer
fields but no quantization-range field. The descriptor correction therefore
cannot, by itself, guarantee a full-range interpretation.

For MJPEG, `tools/test_jpeg_icc_signal.c` creates a YCbCr input profile with
an A2B0 BT.709/full-range transform and CICP `(1,1,1,1)`, then inserts it as a
single ICC APP2 segment. The profile is 30,040 bytes. The insertion audit
confirms every original JPEG byte is preserved after removing that segment,
including coding tables, scan header and entropy data. Apple ImageIO and
FFmpeg decoded the original and tagged file to byte-identical RGB (0 RMS
change). libjpeg-turbo returned byte-identical YCbCr samples. The candidate
therefore does not correct any tested file-decoder output and was rejected.
No live AVFoundation test of a modified USB JPEG header was attempted because
firmware header ownership and bounded insertion are not established.

The completed outside-sandbox run is archived at
`artifacts/color-firmware/20261006/qualification-live/`. The chart was
1920x1080 on the `HDMI TO USB` extended display and its AppKit source render
matched the RGB reference exactly. True Tone was reported off. Night Shift's
private API reported off, but that API's effect-state field is unverified;
the user had disabled Night Shift and True Tone before this run.

The live YUY2 and MJPEG samples both retained full-range endpoints (Y 0–255,
Cb/Cr 1–254) and matched BT.709/full with per-channel RMSE 0.565/1.036/1.055
for YUY2 and 0.533/1.026/1.042 for MJPEG. Their median samples did not change
when the runner requested all getters versus GET_CUR only, reapplied the same
current controls, or reversed format order: YUY2 was identical to the baseline
trial and MJPEG differed by only 0.007 codes RMS. Every raw session reported
control restoration success. GET_DEF returned brightness −11 and contrast
148 while active values remained −18 and 149.

The AVFoundation YUV frame also matched BT.709/full (0.565/1.036/1.055), but
automatic BGRA output remained 7.752 RGB-code RMS from the reference. Of the
tested decodes, BT.709/limited most closely reproduced the automatic BGRA
bytes (0.381 RMS), while BT.709/full matched the reference at 1.378 RMS and
was 7.634 RMS from automatic BGRA. This identifies the host range conversion
as the immediate mismatch: full-range samples are being converted as though
they were limited range. The 2.5-code host gate still fails.

The AVFoundation YUV attachments named BT.709 primaries and matrix but
`SMPTE_240M_1995` transfer. The active firmware's enumerated UVC records are
1/1/1, so CoreVideo's transfer attachment does not match the advertised
BT.709 transfer. Apple describes the 240M value as a distinct transfer
function and recommends the 709 value for most video buffers
([Core Video transfer-function constants](https://developer.apple.com/documentation/corevideo/image-buffer-transfer-function-constants)).
That metadata discrepancy is a useful next signaling lead; the measured
range result is firmer evidence for the BGRA error than the attachment alone.

The current 1080p rates remained 5 fps for YUY2 and 30 fps for MJPEG in the
raw capture trials. AVFoundation's 1080p YUY2 YUV and BGRA outputs ran at
5.00 fps. This is a baseline measurement on the installed image, not a
post-flash comparison for the offline v2 candidate. The earlier 7.266-code
BGRA result is preserved in its original artifact; it was taken in a
different capture run.

Three outside-sandbox reconnect cycles now pass the capture-integrity gate:
all eight immediate frames per format were saved, GET_CUR was the only
control request, brightness/contrast remained −18/149, and the target display
profile was stable during each capture. The chart now uses a status-level
window only on the verified target; when the target disappears, its screen
change handler lowers and orders out the window. The three cycles observed the
target disappear and return. This fixes the chart remaining above windows on
the Mac's main screen and also keeps the menu bar from covering the chart on
the capture display. Older reconnect captures with the earlier chart setup are
retained but excluded from the selected qualification metrics.

The YUY2 startup result still fails: the first frame RMSE by channel was
34.7/28.3/31.9, 61.4/79.8/68.7, and 79.4/91.4/76.5 codes for the three
cycles. In the third cycle, `frame-001` through `frame-004` were also
corrupted; `frame-005` through `frame-007` then matched the steady result at
0.565/1.036/1.055. Every captured MJPEG frame in all three cycles stayed near
0.533/1.026/1.044. The initial YUY2 frames are
full-sized raw payloads delivered by libuvc, but this test cannot determine
whether their corruption originates in device startup or the host capture
path. The startup consistency gate therefore fails, and no firmware startup
change is justified yet. Per-frame metrics are in
[`qualification-live/report.md`](../artifacts/color-firmware/20261006/qualification-live/report.md).

A fresh 8-second stereo capture also passed without changing FE60 or the audio
route. Live RAM readback remained FE60=01 with a two-channel, 48 kHz audio
descriptor; `HDMI TO USB` was the Mac's 48 kHz default output. The captured
left channel had a continuous 995.7 Hz tone and no silent windows. The right
channel had the same tone with 22.1% silent windows, matching the source's
right-channel gaps. Peak correlation remains at −1 sample (0.980 versus 0.972
at zero lag), so the known one-sample offset remains unresolved. The WAV and
readback are recorded in `qualification-live/stereo-current-fe60.*`.

The existing raw USB calibration samples measured YUV RMSE by channel of
0.565/1.036/1.055 for YUY2 and 0.533/1.025/1.043 for MJPEG against the
BT.709/full targets. The gray ramp retained 220 distinct MJPEG patch values.
These pass the sample-fidelity limits, but do not correct the automatic BGRA
path.

## Repeatable qualification tools

`tools/qualify_color_path.py` builds one native helper and runs one guarded
capture session. The completed run records a pre-chart USB claim and
before/after macOS state, then captures original MJPEG/YUY2 payloads using all
getters, GET_CUR only, same-value control reapplication, and reversed format
order. Each raw session logs libuvc-level request fields, readbacks, payload
lengths and restoration status. The chart remains visible during paired
payload trials. After UVC returns, the helper captures AVFoundation packed
YUV and BGRA, plus display/profile state. The request log is not a USB bus
trace; libuvc resolves the control entity ID. Geometry-aware analysis and a
SHA-256 manifest are included.

Run outside the macOS shell sandbox:

```sh
rtk proxy python3 tools/qualify_color_path.py \
  --output artifacts/color-firmware/20261006/qualification-next
```

Replay analysis on an existing capture bundle without touching USB:

```sh
python3 tools/reanalyze_color_capture.py \
  artifacts/color-firmware/20261006/qualification-live
```

The completed run is summarized in
[`qualification-live/report.md`](../artifacts/color-firmware/20261006/qualification-live/report.md)
with raw payloads, AVFoundation frames, control request logs, display state,
analysis, and hashes. It did not write firmware. Its source-display screenshot
was unavailable, so the saved chart image is the AppKit render rather than a
compositor/HDMI measurement.

The unmatched earlier raw capture is now narrowed: getter selection, same-
value reapplication, and format order do not reproduce it. A separate test
captured MJPEG then YUY2 on the same persistent UVC handle; both retained the
same full-range medians, with controls still at −18/149 and no SET_CUR calls.
The three-cycle capture gate passed, but the YUY2 startup consistency gate
failed as described above. The automatic BGRA gate also fails at 7.752 RMS.
The fresh stereo fixture confirms channel order and preserves the known
one-sample offset limitation. These limits keep v2 unqualified for flashing.

The persistent-handle test can be repeated against an existing bundle with:

```sh
rtk proxy python3 tools/qualify_same_handle.py \
  artifacts/color-firmware/20261006/qualification-live
```

The three-cycle reconnect check can also be run against a bundle with:

```sh
rtk proxy python3 tools/qualify_reconnect_cycles.py \
  artifacts/color-firmware/20261006/qualification-live
```

The read-only stereo check replays the existing left/right fixture through the
current HDMI output and captures the dongle audio input (`MS2109-Pro`). It
requires FE60=01 and a 48 kHz two-channel descriptor and does not change either:

```sh
rtk proxy python3 tools/qualify_stereo_audio.py \
  --output artifacts/color-firmware/20261006/qualification-live/stereo-current-fe60.wav
```

Keep the 1920×1080 HDMI source connected. For each on-screen prompt, unplug
and reconnect the grabber, wait for macOS to recognize it, then start capture.
The chart uses a status-level window on the verified target so it covers the
menu bar and preserves the chart's full patch geometry. When that display is
disconnected, the chart is ordered out and lowered to normal level so it
cannot remain on top of the Mac's main screen. It returns to the target display
when macOS reports it again. The chart redraws and saves a fresh patch
reference if the reattached display ICC data changes. Before each format
capture, the runner waits for a stable display
profile and screen placement, snapshots that format's chart reference, and
checks the display stayed unchanged for all eight frames. It captures the
first eight frames delivered after stream start in YUY2 and MJPEG, records
GET_CUR values, and rejects any logged control write. It does not change
brightness, contrast, hue, saturation, or firmware. These are the first
frames captured after re-enumeration, not a USB-bus trace of the very first
frame transmitted by the device.

## EEPROM audit and rollback

`artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.json` records
the byte changes; the candidate SHA is above. The original EEPROM and mask ROM
remain at `backups/ms2109-original.bin` and `backups/ms2109-maskrom.bin`.
If this candidate is ever flashed and must be rolled back to the currently
qualified image, use the guarded writer with full readback:

```sh
python3 tools/flash_eeprom.py \
  --expected-current artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.bin \
  --image artifacts/ms2109-calibrated-stereo-channel-order.bin \
  --readback artifacts/color-firmware/20261006/v2-rollback-readback.bin \
  --apply
```

The command is documented only; it has not been run. The new candidate stays
unflashed until the remaining signaling, `GET_DEF`, reconnect, audio and host
RGB gates pass.
