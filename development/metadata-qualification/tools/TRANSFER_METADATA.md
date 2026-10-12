# Qualify MS2109 transfer metadata

Use saved patch statistics to compare EDID or USB transfer declarations against a verified live baseline. The tool never writes EEPROM or raw video frames. EEPROM candidates are offline artifacts requiring separate approval before flashing.

## Build capture helpers

Requires macOS, NumPy, Homebrew libuvc, libusb, and hidapi. Run from the repository root:

```sh
sh tools/build_transfer_helpers.sh
```

The chart must be displayed on the secondary `HDMI TO USB` display at 1920×1080 with scale factor 1. Capture uses 16×8 patches and samples their centers. Screen savers or unrelated images invalidate captures. The workflow uses the bundled `firmware/patterns/endpoint-pattern.json`. Both helpers draw its RGB codes as native AppKit rectangles in the active display color space, with the window bound to that same color space. Raster rendering is not supported. The sampler uses the direct Y/Cb/Cr top-to-bottom order.

## Save a live baseline

Use a new output directory for each experiment. Live USB EP0/libuvc work requires actual macOS administrator access; leaving the shell sandbox does not grant root privileges. Approve macOS authentication normally. AVFoundation camera access is a separate permission.

```sh
python3 tools/qualify_transfer_metadata.py snapshot --output artifacts/transfer-run
python3 tools/qualify_transfer_metadata.py prepare --output artifacts/transfer-run
python3 tools/qualify_transfer_metadata.py capture --output artifacts/transfer-run --label baseline
python3 tools/qualify_transfer_metadata.py native-metadata --output artifacts/transfer-run --label baseline
```

Snapshot checks silicon ID, reads EEPROM twice, and saves the actual source-visible EDID and USB configuration. It checks color records against active RAM and records other RAM/EP0 differences, including the existing MJPEG interval repair. All later live edits require the same EEPROM bytes. Native color attachments are separate evidence: AVFoundation can convert range and its pixel values are not the raw-libuvc acceptance reference. Native capture runs as the repository owner's logged-in user from a camera-declared app bundle; root remains responsible for procamp controls. Root camera authorization is not equivalent to the user's authorization.

## Measure EDID trials first

After snapshot, preparation, and baseline capture, `suite` runs the remaining RAM-only sequence in one administrator session:

```sh
python3 tools/qualify_transfer_metadata.py suite --output artifacts/transfer-run
```

It waits for each verified source EDID after physical HDMI reconnect, records its current gate in `suite-state.json`, skips previously measured conditions on resume, and restores baseline between trials. Reconnect gates time out after 15 minutes and initiate volatile restoration. Watch the state file to distinguish candidate reconnects from baseline reconnects. No EEPROM write is included. The individual commands below support diagnosis and manual operation.

```sh
python3 tools/qualify_transfer_metadata.py apply-edid --output artifacts/transfer-run --name gamma24
```

Reconnect HDMI only, leaving USB powered. Then:

```sh
python3 tools/qualify_transfer_metadata.py verify-edid --output artifacts/transfer-run --name gamma24
python3 tools/qualify_transfer_metadata.py capture --output artifacts/transfer-run --label gamma24 --edid gamma24
python3 tools/qualify_transfer_metadata.py native-metadata --output artifacts/transfer-run --label gamma24
```

Restore baseline before another trial; reconnect HDMI and verify its source readback. Repeat for `gamma28` and `srgb`. Gamma-only candidates change EDID gamma and the base-block checksum. The sRGB profile also changes chromaticities to sRGB/D65 and sets the sRGB flag. Timing and transport bytes remain identical. Applying a RAM EDID is not evidence that the source has read it: the explicit verification gate must pass before capture.

## Measure USB transfer trials

With baseline EDID verified:

```sh
python3 tools/qualify_transfer_metadata.py apply-transfer --output artifacts/transfer-run --name bt470m --reset
```

Inspect the saved readback. If reset discarded the edit, do not label a subsequent capture as that trial. If it survived, verify host recognition and run:

```sh
python3 tools/qualify_transfer_metadata.py capture --output artifacts/transfer-run --label bt470m --transfer bt470m
python3 tools/qualify_transfer_metadata.py native-metadata --output artifacts/transfer-run --label bt470m
python3 tools/qualify_transfer_metadata.py restore-transfer --output artifacts/transfer-run
```

Repeat for `bt470bg`. UVC values are BT.709=1, BT.470 M=2, BT.470 B/G=3. sRGB=7 is rejected for this device's UVC 1.0 declaration; do not substitute codec transfer enums or upgrade the UVC version just to enable it. USB patches preserve primaries, matrix, format and timing declarations.

The persistent USB candidates reuse the four retired ROM-trampoline slots verified by `builder/rom_overlay.py`; every original caller must already target ROM and all 16 bytes must be erased. A shared complete six-byte color-record guard preserves processor state after the existing common helper. Unrecognized layouts and images exceeding the 1996-byte overlay capacity are rejected. These candidates are not hardware-qualified until flashed and re-enumerated under separate approval.

## Acceptance and rollback

Restore baseline EDID and USB transfer fields, verify readbacks, then capture `baseline-repeat` for the final A–B–A gate:

```sh
python3 tools/qualify_transfer_metadata.py apply-edid --output artifacts/transfer-run --name baseline
# Reconnect HDMI, then verify before capture.
python3 tools/qualify_transfer_metadata.py verify-edid --output artifacts/transfer-run --name baseline
python3 tools/qualify_transfer_metadata.py restore-transfer --output artifacts/transfer-run
python3 tools/qualify_transfer_metadata.py capture --output artifacts/transfer-run --label baseline-repeat
python3 tools/qualify_transfer_metadata.py report --output artifacts/transfer-run
```

Acceptance requires luma affine-fit RMS error reduced by at least 50%, Cb/Cr error not increased, no new rail clipping, monotonic response, and no more than two codes of lost span per channel. Baseline-repeat primary samples must agree with the initial baseline within one code. Every capture uses two stable frames, B−17/C148/H0/S146, active-state verification before and after capture, chart/shape gates, and up to three retries. Previous procamp values are restored after capture. Native attachment captures also verify and restore procamp.

The report writes JSON and standalone SVG waveforms/residuals. It distinguishes absent/unmeasured conditions from unsuccessful corrections. No host-only appearance change qualifies as corrected raw YUY2.

Volatile EDID changes survive until overwritten or USB power is removed. A USB power cycle reloads the unchanged EEPROM baseline; verify source EDID after HDMI reconnect. For a separately approved persistent flash, use this run's `baseline-eeprom.bin` as the rollback image and require an exact current-image match before writing. Never use a historical image/hash as proof of current state.

## Definition references

- [Linux UVC enum mapping](https://github.com/torvalds/linux/blob/master/drivers/media/usb/uvc/uvc_driver.c): UVC transfer enums differ from codec enums; some host mappings substitute other curves.
- [USB-IF Video Class specifications](https://www.usb.org/documents?search=video+class): validate reserved values against the advertised class version.
- [libdisplay-info EDID parser](https://android.googlesource.com/platform/external/libdisplay-info/+/708565d2108d7bcf47fd6377d73b6cd6e69e8c99/edid.c): EDID gamma and sRGB flag decoding.

## Renderer correction

Earlier transfer/EDID experiments used an untagged PNG through NSImage. Their source rendering was color managed and does not establish the capture chip’s own transfer curve. Keep those artifacts as historical evidence; use `artifacts/native-patches-20261012` for the direct-rendering baseline. Requalify color and procamp candidates with native patches before promoting firmware. Archived provenance scripts describe earlier runs and are not the active capture path.

## Current release compatibility

The current release retains the original mask-ROM deep-color flags. RAM EDID delivery still uses the qualified F819 aperture and requires source readback after HDMI reconnect. The offline persistent color-profile builder requires the historical gate-aware 8-bit callback and deliberately rejects the current release after that callback was retired. Treat `prepare_srgb_firmware.py` as historical candidate preparation, not a supported patch for the current image. `recalibrate_srgb.py` is an archived, run-specific sweep with explicit artifact paths; inspect and provide its source-verified baseline before use. sRGB/D65 is not a qualified firmware fix.
