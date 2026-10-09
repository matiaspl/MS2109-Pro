# MS2109-Pro firmware and reverse-engineering reference

This repository documents a 2 KiB EEPROM overlay for the MS2109, the built-in ROM paths it relies on, and the qualification evidence for one HDMI capture dongle. The ROM is not modified; the EEPROM image keeps the built-in initialization and USB handling, then applies a small set of measured corrections.

## Changes from the built-in firmware

- **USB video/audio names:** stored in EEPROM header records and read by the ROM at startup. The current builder supports `--video-name` and `--audio-name`; both names were verified as `MS2109-Pro` after reconnect. The experimental product-string response-buffer repair has been removed from the builder.
- **Video color:** sets startup controls (brightness UI 110 / signed −18, contrast 149, saturation 148, hue 0) and corrects the high-speed MJPEG/YUY2 color descriptors to BT.709 matrix value 1 while preserving the existing primaries and transfer values.
- **Stereo routing:** sets `FE60=01`, which corrected the tested left/right channel order.
- **Existing firmware paths:** retains the configured EDID and ROM-driven HID programming transport. It does not add the proposed UVC Sharpness control, bypass the scaler, or fix the measured one-sample audio offset.

The earlier stage-2 product-string candidate and its qualification records remain in `artifacts/ms2109-pro-name/20261007/` as historical evidence. New images from this builder do not include that response-buffer repair.

The measurements apply to one device and its tested signal path; they do not establish that every MS2109 board needs the same color calibration. Large raw capture frames and recordings are excluded from Git to keep clones practical; compact reports, plots and analysis data remain available where included.

Independent chip documentation: [MS2109 programmer reference](docs/ms2109-reference/README.html) — memory/boot, callbacks, ROM services, registers, and reproducible offline evidence.

The [procamp-defaults v4 image](artifacts/sharpness-firmware/20261008-procamp-defaults/ms2109-procamp-defaults-v4-ms2109-pro-candidate.bin) is installed and cold-boot verified. Its EEPROM and loaded RAM overlay match SHA-256 `a42bfa5919cf164a2a1b4edb4152b156fe65db5c58e55da9d53ef1c0bb52a3eb`; startup RAM, USB names, and all four `GET_DEF` values match brightness −18, contrast 149, hue 0, and saturation 148. See the [updated firmware report](docs/2026-10-08_ms2109-procamp-defaults-coldboot-report.html), [v4 installation record](artifacts/sharpness-firmware/20261008-procamp-defaults/v4-installation.json), [RAM-only GET_DEF test](artifacts/sharpness-firmware/20261008-procamp-defaults/procamp-get-def-ram-v4.json), and [cold-boot qualification](artifacts/sharpness-firmware/20261008-procamp-defaults/cold-boot-qualification-v4.json).

Explore the address spaces in the [interactive MS2109 address map](docs/ms2109-address-map.html). It separates CODE, XDATA, IRAM, SFR, and EEPROM and links mapped regions to the source evidence.


Device-specific extension of [A-Dunstan/ms2109_stereo_patch](https://github.com/A-Dunstan/ms2109_stereo_patch), built from the connected dongle's verified EEPROM backup.

The calibrated baseline image, `artifacts/ms2109-calibrated-stereo-channel-order.bin`, sets
startup **brightness UI 110 (signed UVC −18), contrast 149, saturation 147,
hue 0** in both current-value RAM and hardware registers. It corrects the
high-speed MJPEG and YUY2 color descriptors to **BT.709 matrix value 1**, with
primaries/transfer preserved at 1/1. It retains **48 kHz, 2 channels, 16-bit
PCM** and the qualified FE60=01 channel-order correction.

This image was written on 2026-10-06 and the complete EEPROM readback matched
SHA256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.
After the user's USB reconnect, complete EEPROM and loaded-code checks
confirmed the new firmware, calibrated startup controls, both BT.709
records, and FE60=01. The enumerated USB descriptors also report 1/1/1.
The measured control settings target full-range samples: **Y 0–255 and
Cb/Cr 1–254** at 1920×1080. UVC has no full-range declaration in its color
descriptor, so consumer range handling still matters. See the
[firmware update report](docs/2026-10-06_reverse-ms2109-calibrated-color-report.html).

An opt-in v2 image at
`artifacts/color-firmware/20261006/ms2109-calibrated-color-v2.bin` shares the
guarded descriptor routine and leaves 109 EEPROM bytes free. It is an offline
candidate, not installed. macOS still reports the old ROM `GET_DEF` values,
and no full-range host signaling fix has passed qualification. See the
[color firmware qualification report](docs/2026-10-06-color-firmware-qualification.html).

Fresh captures confirmed BT.709 full-range YUY2 and BT.709 limited-range
host-decoded MJPEG buffers. A steady-handle raw RGB-ramp repeat reproduced
the selected calibration, with the same current controls reapplied.
AVFoundation's automatic RGB conversions still misinterpret the samples:
YUY2 uses a limited-range inverse, while MJPEG uses a BT.601-style inverse.
Use an explicit BT.709/full inverse for original samples, or BT.709/limited
for the tested decoded MJPEG buffer. An earlier direct USB capture had a
separate unresolved midtone discrepancy. See the
[post-reconnect checks](docs/2026-10-06_calibrated-startup-color-report.html)
for measurements and qualification limits.

That earlier calibrated-color profile leaves UVC `GET_DEF` at ROM constants
−11/148/0/180; an application using that separate image can reset controls to
those values. The installed v4 profile reports its configured defaults. The
other-speed color descriptor served from mask ROM is unchanged. This patch does
not fix the extra initial audio sample, add JPEG markers, or implement
scaler/sharpening bypass.

## Previous neutral profile

The previous image, `artifacts/ms2109-neutral-stereo-channel-order.bin`,
sets FE60 to 01 hex. A controlled Mac HDMI test verified continuous left and
gapped right with this register value. The EEPROM was written and fully
verified against SHA256 `bd7edac83659f9d20d0b308469a618df58f773ace820c98fc169384ddb8063e2`.
After the user's power cycle, full EEPROM readback and FE60=01 were verified.
A fresh Mac HDMI capture confirmed continuous left and gapped right.
The one-sample offset
remains; this is a persistent channel-order correction, not full alignment.

This connected dongle was flashed and reconnected on 2026-10-05: live registers confirmed the neutral settings, and macOS captured 48 kHz stereo. A supplied continuous-left/gapped-right tone confirmed reversed channels. On this macOS/AVFoundation path, dropping one initial 16-bit word restored order and moved peak interchannel correlation to zero lag. This is a recording/host correction; firmware alignment remains unchanged.

After a future successful flash, unplug/replug the dongle to load the EEPROM and let macOS enumerate the new descriptor. Keep the original backup.

Firmware alignment investigation: endpoint packet-size changes, FIFO reads/insertion, and an audio rate-control toggle did not correct the supplied tone. A DMA-gated insertion stalled/garbled audio; restoring RAM and flushing was insufficient. A subsequent physical power cycle restored the clean original tone and the qualified startup patch. These candidates are rejected and are not in the EEPROM image. Detailed evidence is in the report.

The follow-up [sample-offset report](docs/2026-10-06_sample-offset-ms2109-report.html) pins and size-audits the public MS2109 firmware source. Two guarded RAM-only EP2 reset attempts were rejected: the first monitor was behind the mailbox idle return; the corrected monitor executed, but the captured offset remained −1 sample. Its telemetry was an occurrence flag, not an exact count, and did not establish first-packet timing. The temporary hook was restored, and a full read-only check confirmed the calibrated EEPROM and loaded code were unchanged. No firmware alignment fix is validated.

The [firmware-options reassessment](docs/2026-10-06_sample-offset-firmware-options.html) verifies optional hooks at `CC10` and `CC20`. Offline instruction-level testing found and fixed a leaked return address in the temporary CC10 `SET_INTERFACE` helper. Signal-backed traces and a deterministic wideband HDMI fixture now measure the stream: baseline lag is −1 sample, and the EP2 reset occurrence flag is set without changing that lag. The temporary hooks were restored; a full read-only check confirms EEPROM and loaded code still match the calibrated image. No firmware alignment fix is validated and no EEPROM write occurred. See `tools/generate_audio_prbs_reference.py`, `tests/test_audio_usb_hook_execution.py`, and the detailed report.

`tools/capture_audio_usb.c` captures raw endpoint 82 packet lengths and PCM before CoreAudio framing. On macOS, it temporarily detaches the dongle's driver (potentially re-enumerating the whole dongle), then reattaches it on exit. This requires root or a USB capture entitlement; the current agent process has neither. It performs no firmware writes. Built with `cc -Wall -Wextra -Werror -I/opt/homebrew/include/libusb-1.0 tools/capture_audio_usb.c -L/opt/homebrew/lib -lusb-1.0 -o tools/capture_audio_usb`. The user's sudo retry captured 4096 packets with zero failures and reproduced the order/offset fault before CoreAudio. Use a fresh output prefix because existing files are refused:

```sh
sudo ./tools/capture_audio_usb artifacts/audio-usb-start
```

## Files

- `backups/ms2109-original.bin`: two identical complete reads of the original 2048-byte EEPROM.
- `backups/ms2109-maskrom.bin`: ROM addresses 0000–CBFF, read using a temporary RAM hook; original hooks restored.
- `artifacts/ms2109-neutral-stereo.bin`: checksum-validated patch image.
- `artifacts/ms2109-neutral-stereo.json`: original/target hashes and exact byte changes.
- `artifacts/ms2109-flashed-readback.bin`: full EEPROM readback, when flashing succeeds.
- `docs/2026-10-05_reverse-ms2109-report.md`: analysis, validation and limitations.

## Rebuild and inspect

Run from this directory. Python 3 and macOS HIDAPI (`/opt/homebrew/lib/libhidapi.dylib`) are used; the offline builder and tests use only Python's standard library.

```sh
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/new-neutral-stereo.bin
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/new-neutral-stereo-channel-order.bin --channel-order
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/new-calibrated-stereo-channel-order.bin --channel-order --calibrated-color --rom backups/ms2109-maskrom.bin
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/new-calibrated-color-v2.bin --channel-order --calibrated-color-v2 --rom backups/ms2109-maskrom.bin
python3 -m unittest discover -s tests -v
python3 tools/ms2109_hid.py inspect
```

The builder refuses other firmware hashes, corrupt checksums, unexpected entry code, insufficient erased space, and existing output names. The calibrated profile additionally requires the exact saved ROM hash. Historical neutral builds remain byte-for-byte reproducible.

## Flash or restore

Dry run by default. `--apply` writes only after reading the entire EEPROM and comparing it to `--expected-current`. Each byte and the complete resulting image are verified. A write error triggers restoration of modified bytes. Power loss during EEPROM commit cannot be made atomic; the original image permits external-programmer recovery if needed. Use `--readback NEW_PATH` to preserve each full readback separately.

```sh
python3 tools/flash_eeprom.py --expected-current backups/ms2109-original.bin --image artifacts/ms2109-neutral-stereo.bin --apply
```

The calibrated image is already committed; rerunning a flash against its
previous-image backup will correctly refuse. After USB reconnect, verify
the loaded code, controls and descriptors without writing device state:

```sh
python3 tools/verify_color_startup.py --image artifacts/ms2109-calibrated-stereo-channel-order.bin --output artifacts/new-color-startup-check.json
```

To restore the previous qualified neutral/channel-order image from the
calibrated EEPROM, the exact-image guarded command is:

```sh
python3 tools/flash_eeprom.py --expected-current artifacts/ms2109-calibrated-stereo-channel-order.bin --image artifacts/ms2109-neutral-stereo-channel-order.bin --readback artifacts/new-neutral-rollback-readback.bin --apply
```

To restore the original, first preserve the patched readback separately, then:

```sh
python3 tools/flash_eeprom.py --expected-current artifacts/ms2109-calibrated-stereo-channel-order.bin --image backups/ms2109-original.bin --readback artifacts/new-original-restored-readback.bin --apply
```

Unplug/replug after restoring too. Do not rerun the ROM dump helper after patching: its temporary buffer overlaps the appended hook. The historical dump helper explicitly refuses this image.

## Historical audio sample alignment before FE60 correction

The following measurements and host helpers describe the earlier FE60=10
image. Their combined swap/delay correction must not be applied unchanged
to the channel-order image, which already swaps the source selections.

The extra initial **16-bit sample** rotates the interleaved channel sequence by half a stereo frame. Signed/unsigned changes, floats, 32-bit samples or changing endianness do not remove that word. Linux ALSA already drops two bytes once per stream and retains partial frames; do not apply another correction on Linux.

`tools/align_pcm.py` performs that correction on raw, uncorrected S16_LE stereo data before framing: it drops the first two bytes once and preserves frame continuity across arbitrary input chunks.

```sh
python3 tools/align_pcm.py < uncorrected.s16le > aligned.s16le
```

This helper is **not** installed as a CoreAudio driver or OBS filter. macOS APIs can trim/reframe samples before delivering audio, so its synthetic tests do not qualify blindly applying it to AVFoundation recordings. A known HDMI left/right test and a simultaneous pulse in both channels are needed to measure the actual host-delivered order and offset.

For scaling, first use an HDMI input and negotiated capture mode with the same dimensions. This avoids requesting a resize, but does not prove hardware scaler bypass. No unverified register writes are provided.

The user confirmed reversed channel order after the descriptor patch. A host-side
channel swap alone can be applied with FFmpeg's `pan=stereo|c0=c1|c1=c0`, but it
does not repair the one-sample timing error. The raw alignment helper repairs
both effects of the extra initial word, if that word is still present at its input.
The later FE60 change was qualified against an independently generated Mac
HDMI reference; see the report for its separate evidence.

## Measured macOS correction

With the supplied continuous-left/gapped-right signal, raw channel 0 contained
gaps, while raw channel 1 was continuous. Peak tone correlation occurred at
`ch0[n] ~ ch1[n-1]`. Thus the measured correction is:

```text
corrected_left[n]  = raw_right[n]
corrected_right[n] = raw_left[n+1]
```

This is the same half-frame rotation as dropping one 16-bit word from the
interleaved stream. It restores both order and the measured relative timing.
The corrected capture has continuous audio on the left and gaps on the right,
with peak correlation at zero lag. This is consistent with the known defect;
absolute source phase was not independently measured.

```sh
python3 tools/correct_wav.py input.wav corrected.wav
python3 tools/analyze_audio.py corrected.wav --output analysis.json
```

The WAV correction uses Python's standard library. Analysis requires NumPy.
Input must be uncorrected 48 kHz stereo S16 PCM. Do not apply this twice or
after Linux ALSA's built-in correction. A final unmatched half-frame is dropped.
These tools do not install a system driver or modify live OBS audio.

A verified causal filter for the measured macOS path is:

```text
pan=stereo|c0=c1|c1=c0,adelay=1S|0S
```

It swaps the channels, then delays corrected left by exactly one sample (about
20.83 microseconds at 48 kHz). Corrected right is undelayed. Applied to the live
test recording, this puts continuous tone on left and gaps on right, and moves
peak interchannel correlation to zero lag. This is equivalent to the one-word
rotation up to a shared one-sample latency. `S` denotes samples, not seconds.

Example capture to a corrected WAV (requires the connected dongle):

```sh
ffmpeg -f avfoundation -i ':usb video' -af 'pan=stereo|c0=c1|c1=c0,adelay=1S|0S' -c:a pcm_s16le corrected.wav
```

Routing that corrected stream into another application requires a suitable
filter/plugin or virtual audio input. This command alone does not change the
system's MS2109 audio device.

## Color probe

The calibration run at brightness UI 110, contrast 149 and saturation 147 measured **full-range YUY2 and MJPEG samples** (Y 0–255, Cb/Cr patch medians 1–254) at 1920×1080. The latest paired qualification found the same samples across GET_CUR-only/all-getter, control-reapply and format-order trials, narrowing the earlier unmatched capture; its specific cause remains unresolved. Automatic AVFoundation BGRA is 7.752 RGB-code RMS from the reference and fits a BT.709 limited-range decode within 0.381 codes RMS, even though the USB samples are full range. True Tone was off for this run; the private Night Shift effect state could not be verified. See the [live qualification report](docs/2026-10-06-color-firmware-qualification.html) for remaining gates.

```sh
python3 tools/probe_colors.py run --output artifacts/color-probe/new-measurement
```

Run hardware acquisition outside the macOS shell sandbox. The probe displays its chart on the 1920×1080 HDMI TO USB extended screen, saves raw YUV and color metadata, reads the existing picture controls, and leaves global display settings and firmware unchanged.

For paired raw payloads, controls, request logs, display/profile state, AVFoundation YUV/BGRA frames and hashes, use:

```sh
rtk proxy python3 tools/qualify_color_path.py --output artifacts/color-firmware/20261006/qualification-next
```

Use `--transport avf420v` to check the host-decoded MJPEG path. Original USB acquisition uses [capture_video_uvc.c](tools/capture_video_uvc.c) with a one-time macOS administrator prompt from [run_capture_video_uvc_admin.m](tools/run_capture_video_uvc_admin.m). Build and analysis commands are in the comparison report. Original JPEG samples are decoded to YCbCr by [decode_jpeg_ycbcr.c](tools/decode_jpeg_ycbcr.c), without an RGB matrix or range conversion.

The [complete RGB ramp quantization report](docs/2026-10-06_rgb-quantization-report.html) measures every 0–255 channel level, with the requested brightness/contrast UI 127/127 reference and the previous 128/128 UI settings. It includes per-input CSVs, pixel-code histograms and plots. Signed UVC brightness −1 represents UI 127; that setting produced gray endpoints 14–232. All temporary controls were restored after capture.

The [isolated 128/127 test](docs/2026-10-06_brightness128-contrast127-report.html) confirms that contrast 127 reduces luma even with zero brightness offset: gray endpoints become **15–233**, while Cb/Cr stay unchanged. The tested UI 128/128 settings preserve 16–235.

## Automatic range calibration

[calibrate_colors.py](tools/calibrate_colors.py) measures a local brightness,
contrast and saturation search in **both original USB YUY2 and MJPEG**. It
displays seven complete 256-code ramps plus 128 mixed colors, checks clipping
and numeric BT.709 fidelity, and writes `result.json`, `candidates.csv`,
per-patch CSVs and `report.md`. It captures three frames per transport per
setting, audits JPEG coding tables, restores the starting controls after
every sample and checks the normal AVFoundation driver afterward. It does
not write firmware or leave the recommendation applied.

The [qualified run](artifacts/color-probe/20261006-auto-calibration-v2/report.html)
measured 24 settings. The best coverage/fidelity balance was **brightness UI
110** (signed UVC −18), **contrast 149**, **saturation 147**, **hue 0**: Y spans
0–255 and Cb/Cr patch medians span 1–254 in both formats. MJPEG still has only
220 distinct gray patch values. Saturation 148/149 did not expand chroma
endpoints. These settings target full-range consumers; matrix/range handling
must match the measured samples.

Run from the repository root, outside the macOS shell sandbox, with the
1920×1080 extended HDMI TO USB display connected and True Tone/Night Shift
disabled. Dependencies are NumPy/Pillow, Xcode command-line tools, and
Homebrew libuvc/libjpeg-turbo. Starting controls must yield the known BT.709
limited baseline (qualified at UI B/C/S 128/128/128, hue 0). A single native
administrator prompt grants temporary USB access. Use a new output directory.

```sh
/opt/homebrew/bin/python3 tools/calibrate_colors.py run --output artifacts/color-probe/new-calibration
```

To recompute statistics and recommendations from the preserved raw frames
without opening hardware or presenting a chart:

```sh
/opt/homebrew/bin/python3 tools/calibrate_colors.py analyze artifacts/color-probe/20261006-auto-calibration-v2 --redecode
/opt/homebrew/bin/python3 tools/test_calibrate_colors.py
```

[plot_calibration.py](tools/plot_calibration.py) exports SVG/PDF comparisons
using ReportLab. The run retains original capture sources and executable
hashes; later file-only analysis revisions have separate source snapshots.

Latest register findings: [FE8E/FE8F procamp bypass characterization](docs/2026-10-08_ms2109-procamp-bypass-findings.html), with saved measurements, captured images, and explicit unresolved mappings.
