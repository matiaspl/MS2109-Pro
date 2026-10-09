# MS2109 calibrated startup and BT.709 declaration update

The attached MS2109 EEPROM now contains startup **brightness UI 110 (signed
−18), contrast 149, saturation 147, hue 0**, with **BT.709 matrix value 1**
in both high-speed MJPEG and YUY2 color descriptors. The full EEPROM
readback equals the built image, SHA256
`83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.
The qualified stereo/channel-order register is preserved. After the user's
USB reconnect, full EEPROM and loaded header/code checks confirmed the
1950-byte image, calibrated controls, both RAM color records and FE60=01.
The enumerated USB records also report 1/1/1. Fresh frame and host RGB
checks are recorded in the [post-reconnect report](2026-10-06_calibrated-startup-color-report.html).

Scope: the user's request to update calibrated startup controls and color
matrix in the existing patched firmware, on the attached 534d:2109 dongle.
The existing [scope](scope.html) covers its backup, targeted EEPROM patch,
RAM/ROM analysis and host capture verification. Report flavor: ordinary
firmware reverse engineering, `null`.

## What changed

| Field | Previous patched startup | New startup |
|---|---:|---:|
| Brightness, unsigned UI | 128 | 110 |
| Brightness, signed UVC | 0 | −18 |
| Contrast | 128 | 149 |
| Saturation | 128 | 147 |
| Hue | 0 | 0 |
| High-speed MJPEG/YUY2 matrix declaration | 4, SMPTE 170M/BT.601 | 1, BT.709 |
| Primaries/transfer declarations | 1/1 | 1/1 |
| Stereo PCM | 48 kHz / 2 ch / 16 bit | Preserved |
| FE60 source channel order | 01 | Preserved |

The picture controls come from the [24-setting live calibration](2026-10-06_automatic-color-calibration-report.html).
They produced original USB patch-median ranges Y 0–255 and Cb/Cr 1–254 at
1920×1080. These are full-span settings, rather than a neutral limited-range
pass-through. Their measured numeric matrix was already BT.709; this update
changes the declaration, not a hardware coefficient bank.

The startup hook writes `EE FF 95 00 00 00 93 00` to C6A0–C6A7 and
`EE 95 93 00` to FE90–FE93. Brightness is correctly sign-extended to −18.
Stage 1 follows the ROM control initialization and precedes USB interrupt
enabling. Matrix writes run at stage 1 and stage 2 so a rebuilt descriptor
can be corrected again. They change only C2A9 (MJPEG) and C440 (YUY2), after
checking the complete six-byte original record `06 24 0D 01 01 04`.
Already-corrected or unexpected descriptors are left untouched.

The byte value 1 means BT.709 in the
[UVC color-matching definitions](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/video.h).
Primaries and transfer are independent fields; they remain unchanged because
the numeric chart did not independently measure physical primaries or OETF.
JPEG coding tables were complete in the live captures, so no unverified
JFIF/Adobe/ICC header injection was added.

## Qualification and limits

Eight tests pass. An independent small 8051 interpreter executes all 256
stage values, verifies exact RAM/register writes, signed brightness and
return DPTR, and tests every descriptor guard byte, repeated execution,
full-speed-template non-corruption and checksum/hash rejection. The decoded
modified configuration still contains both formats and declares 1/1/1.
Stock callback, IRQ, video tables and audio code remain byte-exact, apart
from the existing common-hook entry. Rebuilding the previous neutral image
still produces its exact historical bytes.

The new EEPROM code length is 1950 bytes, the appended hook is 230 bytes at
D2B8, and 46 EEPROM bytes remain free. The installed previous image had
1810 code bytes. Its entire 2048-byte backup matched the qualified image
before writing. All 187 changed bytes were individually verified, followed
by complete readback. F002 was restored to 01, and the active audio routing
remained FE60=01.

The post-write read-only check independently confirmed the new EEPROM
image while detecting the old 1810-byte RAM image, old UI 128/128/128
controls and old matrix declarations. That is expected before reconnect;
it is not a cold-start verification. No USB reset or RAM hot-patch was used.

The later user-performed reconnect loaded the intended code. Read-only
checks before and after acquisition confirmed `EE FF 95 00 00 00 93 00`
at C6A0, `EE 95 93 00` at FE90, both records `06 24 0D 01 01 01`, and
FE60/F002=01. Both high-speed color declarations are visible through
libusb's active configuration descriptor, independently of RAM readback.
The first normal-driver capture required no picture-control writes.
The subsequent raw ramp repeat reapplied the same current values and
restored them; it is qualified separately from cold-start readback.

These remaining limits affect out-of-box behavior:

- ROM `GET_DEF` replies remain signed brightness −11, contrast 148,
  hue 0, saturation 180. An application that resets to those defaults can
  replace the calibrated startup controls. A request-handler override
  would need separate implementation and qualification.
- The high-speed RAM descriptors are corrected. The other-speed descriptor
  served directly from mask ROM remains unchanged; full-speed color
  reproduction was not calibrated.
- The UVC color descriptor has no quantization-range field. Applications
  must interpret the measured full-range samples correctly; this update
  cannot guarantee every YUY2/MJPEG decoder's matrix/range handling.
- The calibration covers the Mac's 1920×1080 HDMI source, with True Tone and
  Night Shift disabled. Other input modes and sources need their own check.
- Wider endpoints do not recover lost precision: the measured MJPEG gray
  ramp still contained 220 distinct patch values.
- Fresh AVFoundation RGB checks still use an inappropriate limited-range
  inverse for full-range YUY2 and a BT.601-style inverse for decoded
  MJPEG. Correct USB descriptors do not remove those host transforms.
- One initial direct USB capture differed from normal-driver samples
  despite unchanged saved source/profile and controls. Its cause remains
  unresolved; it is excluded from paired decoder attribution.

## Reproduce, activate and roll back

Run from the repository root. New output names preserve old images:

```sh
rtk proxy python3 tools/build_patch.py backups/ms2109-original.bin artifacts/new-calibrated-stereo-channel-order.bin --channel-order --calibrated-color --rom backups/ms2109-maskrom.bin
rtk proxy python3 -m unittest discover -s tests -v
```

The calibrated image is already written and its cold start is verified.
After a future USB reconnect, run this
read-only check outside the macOS shell sandbox with a fresh output name:

```sh
rtk proxy python3 tools/verify_color_startup.py --image artifacts/ms2109-calibrated-stereo-channel-order.bin --output artifacts/new-color-startup-check.json
```

The checker verifies the entire EEPROM, loaded header/code, current and
hardware controls, both RAM color descriptors and FE60. It exits nonzero
unless the calibrated startup is active. Frame captures qualify each
consumer's matrix/range handling separately.

The exact-image guarded rollback to the previously qualified image is:

```sh
rtk proxy python3 tools/flash_eeprom.py --expected-current artifacts/ms2109-calibrated-stereo-channel-order.bin --image artifacts/ms2109-neutral-stereo-channel-order.bin --readback artifacts/new-neutral-rollback-readback.bin --apply
```

Then reconnect USB to load the restored EEPROM. Writes are guarded by the
full expected image, checked byte by byte and rolled back on an error.
Power loss cannot make an EEPROM commit atomic; original and previous
qualified backups are retained.

## Evidence, findings and path

The machine-readable [evidence](../artifacts/color-firmware/20261006/evidence.json)
records source paths, hashes, commands and excerpts. All items were observed
on 2026-10-06; no external import/export tables exist in this raw 8051 dump.

| Evidence ID | Observation |
|---|---|
| E-rom | Exact ROM hash, no import/export metadata; stage locations and hard-coded default replies checked with radare2 |
| E-before | Complete EEPROM matched previous qualified image; live RAM records confirmed both matrices 4 and FE60=01 |
| E-calibration | Independent original YUY2/JPEG measurement selected the startup controls |
| E-tests | Eight offline tests, including all 256 stage values and complete descriptor guards |
| E-write | Exact target/readback equality after individually verified byte writes |
| E-post | Independent EEPROM/RAM check confirms persistence, preserved FE60 and pending power cycle |
| E-cold | After user reconnect, full EEPROM and loaded code match; all startup/control/descriptor checks pass |
| E-enumerated | Active USB configuration exposes matrix 1 for both high-speed video formats |
| E-frames | Fresh YUV and host RGB measurements, full RGB-ramp repeat and an explicitly retained unmatched raw capture |

F-controls, severity=n/a_re, category=other, confidence=high: the selected
startup bytes implement the measured controls and preserve audio. Status:
validated for build, EEPROM persistence and cold-start application.
Evidence: E-calibration, E-tests, E-write, E-post, E-cold.
Location: stage 1 at D2B8.

F-matrix, severity=n/a_re, category=other, confidence=high: guarded stage
writes produce 1/1/1 declarations for both high-speed formats without
altering primaries/transfer or frame records. Status: validated offline,
in running RAM and in the enumerated USB configuration. Host RGB conversion
limits remain measured and unresolved. Evidence: E-rom, E-before, E-tests,
E-cold, E-enumerated, E-frames. Location: RAM C2A4/C43B color matching records.

P-color, path_type=callflow: exact ROM/EEPROM identity (E-rom/E-before) →
measured control selection (E-calibration/F-controls) → guarded stage-1 and
stage-2 implementation (E-tests/F-matrix) → checked EEPROM commit (E-write)
→ independent persistence check (E-post) → user USB reconnect (E-cold)
→ enumerated color records (E-enumerated) → fresh capture/decoder checks
(E-frames). Residual limits are the application/default/range issues above.

Timeline: backed up the live qualified image, checked ROM boot/control paths,
built and tested the new profile, wrote and fully verified EEPROM, then
independently read the saved image and active RAM without resetting USB.
After the user's reconnect, read back running code and descriptors, then
captured both video paths and checked host RGB conversion and raw ramps.
No unrelated firmware, display settings, devices or services were changed.
