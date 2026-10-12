# MS2109-Pro

Firmware for the MS2109 HDMI-to-USB capture device, exposed as a standard UVC camera and stereo USB audio input.

## Current release

The 2026-10-12 release uses **B−17/C148/H0/S146** at startup and retains the original mask-ROM EDID, including deep-color capabilities. It passed cold-boot EEPROM readback, startup-control, source-EDID, USB-descriptor and native-patch raw YUY2 validation on the tested device.

| Original behavior | Firmware change | Tested result |
| --- | --- | --- |
| The 1080p MJPEG descriptor offered 60 fps. | Replaces that interval with a duplicate 30 fps entry. | 30, 25, 20 and 10 fps advertised; default 30 fps. |
| High-speed video descriptors declared BT.601; measured output matched BT.709. | Declares BT.709 primaries, transfer and matrix for YUY2/MJPEG. | Hosts that apply the descriptor can select the measured matrix. Range still requires host configuration. |
| Neutral procamp produced a limited channel span. | Loads the native-patch calibrated startup values below. | Raw Y/Cb/Cr each span 1–254 with sub-code straight-line RMS. |
| The tested source's audio channel order did not match USB left/right. | Retains the qualified stereo routing fix and 48 kHz audio declaration. | Source left routes to USB left and right to USB right; a measured one-sample offset remains unresolved. |
| Generic USB video/audio names. | Uses `MS2109-Pro` product and interface names. | Names verified after USB power cycling. |

## Quick start

1. Connect an HDMI source, then connect the device by USB.
2. Select **MS2109-Pro** as the camera and audio input in your capture application.
3. Select a supported capture format and frame rate.
4. Configure the downstream path for **BT.709 full range** where available.
5. Check bars or native gradients with scopes before recording.

YUY2 is uncompressed 4:2:2; MJPEG is compressed JPEG video. MJPEG decoders can use their own matrix and range assumptions despite the UVC descriptor. At 1080p MJPEG, applications can list 30 fps twice because the fixed-size descriptor retains a duplicate interval. Other modes remain as inherited from the device.

## Picture controls

| Control | Startup value |
| --- | ---: |
| Brightness | 111 in a 0–255 UI; signed UVC −17 |
| Contrast | 148 |
| Saturation | 146 |
| Hue | 0 |

Standard UVC GET/SET control handling remains in mask ROM. No Sharpness control or scaler change is added.

## Measured color response

Two stable raw YUY2 frames of direct display-native RGB gradients produced:

| Channel | Straight-line RMS, codes | Minimum–maximum |
| --- | ---: | ---: |
| Y | 0.4027 | 1–254 |
| Cb | 0.4461 | 1–254 |
| Cr | 0.4461 | 1–254 |

No monotonicity failures or extra endpoint rail samples were observed. These RMS values are residuals from a straight-line fit, not absolute error against every ideal output code. Earlier PNG/NSImage rendering introduced curvature; those results do not establish a transfer-curve defect in the capture chip.

See [native calibration](docs/native-patch-calibration.md), [deep-color comparison](docs/deep-color-edid.md), and [cold-boot readback](docs/deep-color-cold-boot.json). Measurements cover the tested device, source and gradients, not every RGB triplet, HDMI encoding or host application.

## Audio and practical limits

Audio is advertised as stereo, 16-bit, 48 kHz. Channel routing was qualified with a continuous-left/gapped-right HDMI source. The latest cold boot verified descriptors; it did not repeat audio waveforms or timing measurements.

- UVC metadata here has no full/limited-range field. Configure and verify the host range separately.
- Full-range expansion cannot recover precision lost to quantization or JPEG compression.
- Actual HDMI transport bit depth and input encoding were not independently measured.
- A one-sample audio timing offset remains unresolved. As a workaround turn your head 2 degrees to compensate for the ~2 microsecond delay :)

## Firmware and build

| File | Size | SHA-256 |
| --- | ---: | --- |
| [EEPROM image](firmware/ms2109-pro.bin) | 2,048 bytes | `7a8379955877f550f2a9048e86afd3bd6bb0d5b7c265197ffc55401e9442c33a` |

Use the image only with a matched MS2109 device. Save and verify a full live EEPROM backup before programming. Disconnect/reconnect USB after a verified write to load the new firmware.

The builder requires Python 3.10 or later and no third-party packages:

```sh
python3 builder/build_release.py /tmp/ms2109-pro-rebuilt.bin
shasum -a 256 /tmp/ms2109-pro-rebuilt.bin
cmp firmware/ms2109-pro.bin /tmp/ms2109-pro-rebuilt.bin
```

It refuses existing output paths, verifies the pinned qualified baseline, applies guarded same-length startup changes, retires the 8-bit EDID callback in place, and validates capacity, checksums and the final hash. The overlay uses 1,939 of 1,996 available bytes. Exact release changes are in [the manifest](firmware/ms2109-pro.json).

Experimental metadata, procamp and capture tools are maintained on [the experiments branch](https://github.com/matiaspl/MS2109-Pro/tree/experiments/development/metadata-qualification). They use reversible live qualification and offline candidate preparation; they are not additional release fixes.
