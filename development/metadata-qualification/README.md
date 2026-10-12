# MS2109 metadata qualification tools

Run commands from this directory. The tools draw direct AppKit patches on the 1920×1080 HDMI TO USB display and analyze raw libuvc YUY2 frames in memory. Native AVFoundation captures can collect sample-buffer color attachments. No desktop capture or raw bitmap storage is used.

## Start a new comparison

Requires macOS, clang, Python with NumPy, and Homebrew libuvc/libusb/hidapi. Build only:

```sh
sh tools/build_transfer_helpers.sh
```

Then follow [the qualification procedure](tools/TRANSFER_METADATA.md). Live EP0/capture access requires administrator authentication and physical HDMI reconnects; each condition is rejected unless its active state and chart are verified. The default fixed procamp is B−17/C148/H0/S146. Restore the saved baseline after trials.

## Included scripts

| Tool | Purpose |
| --- | --- |
| `tools/qualify_transfer_metadata.py` | Snapshot, guarded RAM EDID/USB edits, active readbacks, stable captures, JSON statistics and SVG waveforms. Never writes EEPROM. |
| `builder/transfer_metadata.py` | Validate UVC enums and EDID fields; prepare guarded offline candidates and byte diffs. |
| `builder/release_builder.py` | Experimental descriptor builder with an explicit transfer-characteristic option; defaults remain unchanged. |
| `tools/source_display_metadata.m` | Read source display mode, ICC profile and LUT metadata without screen pixels. |
| `builder/prepare_srgb_firmware.py` | Historical offline sRGB/D65 candidate preparation; requires the retired gate-aware callback. |
| `tools/recalibrate_srgb.py` | Archived run-specific procamp sweep; artifact paths require its historical verified setup. |

The supporting assembler/layout modules and pinned mask ROM are bundled for reproducible offline work. The archived EEPROM is a historical input, never evidence of current live state. Tests are included as source; publication did not run a new test suite or access the device.

## Qualified findings

Direct native patch drawing achieved raw Y RMS 0.4027 and Cb/Cr RMS 0.4461 codes, spans 1–254. Earlier PNG/NSImage charts introduced curvature and do not prove a device transfer defect. Restoring the original deep-color EDID flags produced identical sampled values in an A–B–A comparison. The release then passed cold-boot validation. See [native rendering](docs/native-patch-calibration.md) and [deep-color readbacks](docs/deep-color-cold-boot.json). Actual HDMI wire bit depth remains unmeasured. sRGB/D65 was not promoted.

The persistent EDID candidate path intentionally rejects the current release without the historical callback. USB transfer enum sRGB=7 is rejected for UVC 1.0. EEPROM flashing is outside the live qualification tool.
