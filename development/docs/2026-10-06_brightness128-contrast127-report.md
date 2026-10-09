# Brightness 128 / contrast 127: isolated procamp test

**Brightness UI 128 / contrast 127 is not a null procamp transform on this grabber.** Both original USB formats shift gray black from **16 to 15** and gray white from **235 to 233**, relative to brightness UI 128 / contrast 128. Among the tested settings, **128/128** preserves the expected limited-range endpoints most closely.

The user requested this isolated test after the [complete RGB quantization experiment](2026-10-06_rgb-quantization-report.md). The same 1,024-patch chart tests every 0–255 code on gray, red, green and blue ramps. True Tone and Night Shift remain disabled according to the user's stated timeline. The external HDMI TO USB screen is still 1920×1080, extended, with its existing profile.

## Measured response

The live brightness range is signed −128…127, so UI 128 is **signed zero**. Readbacks verify signed brightness 0 in both the fresh baseline and test. Only contrast differs: **128 versus 127**.

| UI brightness / contrast | Signed brightness | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr | Fitted gray slope, YUY2 |
|---|---:|---|---|---:|
| 128 / 128, fresh baseline | 0 | 16 / 128 / 128 | 235 / 128 / 128 | 0.858979 |
| **128 / 127, requested test** | 0 | **15 / 128 / 128** | **233 / 128 / 128** | **0.852940** |
| 127 / 127, previous experiment | −1 | 14 / 128 / 128 | 232 / 128 / 128 | 0.852940 |

The original JPEG samples give the same endpoints; their fitted test slope is 0.853013. Across all 1,024 patches, reducing contrast to 127 changes **only Y**: median differences range from **−2 to 0** codes. Both Cb/Cr medians and their full pixel-code histograms remain exactly unchanged.

YUY2's luma difference has **1.229 codes RMS**; JPEG's has **1.203**. Only 41/1,024 YUY2 patches and 80/1,024 JPEG patches have unchanged medians. This is a repeatable response throughout the ramps, rather than an endpoint-only result. The fresh 128/128 baseline matches the previous run's patch medians exactly in both formats.

The response is approximately a truncated luma gain of `floor(Y_baseline × 127 / 128)`: that model has 0.218 Y-code RMS error for YUY2 and 0.308 for JPEG. This is a numerical model of the samples, not a claim that the internal hardware arithmetic has been identified.

Comparing the new 128/127 recording with the previous 127/127 recording isolates brightness as well: raising brightness UI 127→128 adds **exactly one Y code** to every measured patch median, with Cb/Cr unchanged, in both formats.

## Evidence

- [Control comparison and verification](../artifacts/color-probe/20261006-b128-c127/analysis/control-comparison.json)
- [Every-code YUY2 comparison](../artifacts/color-probe/20261006-b128-c127/analysis/compare-yuy2.csv)
- [Every-code JPEG comparison](../artifacts/color-probe/20261006-b128-c127/analysis/compare-mjpeg.csv)
- [Raw per-input pixel histograms](../artifacts/color-probe/20261006-b128-c127/analysis/histograms.json)
- [Complete ramp analysis](../artifacts/color-probe/20261006-b128-c127/analysis/analysis.json)
- [Full-ramp plot](../artifacts/color-probe/20261006-b128-c127/analysis/ramps.svg) and [shadow-step zoom](../artifacts/color-probe/20261006-b128-c127/analysis/shadow-steps.svg)

The four USB recordings each preserve eight original 1920×1080 frames: current/test controls in MJPEG and YUY2. JPEG is decoded to YCbCr without an RGB matrix or range conversion. The central 8×8 pixels of each patch provide 512 samples per input. All source renders match their references exactly, all frame lengths/dimensions and JPEG markers validate, and JPEG decoding reports no warnings. Acquisition ran outside the macOS shell sandbox.

## Restoration and boundaries

Each temporary test restores and reads back signed brightness 0 / contrast 128 before releasing the UVC driver. Post-capture HID bytes match the initial snapshot exactly: `C6A0–C6A7=0000800000008000`, `FE90–FE93=00808000`. A subsequent real AVFoundation recording saves three valid YUY2 frames; its patch medians match the fresh USB baseline exactly. [Test controls and restoration](../artifacts/color-probe/20261006-b128-c127/usb/ui128c127/yuy2/usb-capture.json) · [HID after](../artifacts/color-probe/20261006-b128-c127/procamp-after.json) · [restored capture](../artifacts/color-probe/20261006-b128-c127/driver-restored/capture.json)

No firmware, EEPROM or global display setting was changed. Source and executable hashes for this capture are retained with the run. The reference remains an AppKit source render before late compositor/HDMI processing. These results establish the procamp response for the current 1080p source; the RGB-to-YCbCr representation, quantization, JPEG effects and previously measured host range conversion are separate from a null procamp adjustment.

To repeat, build the updated helpers as in the [original-frame report](2026-10-06_uncompressed-mjpeg-color-report.md), use the full-ramp manifest, and pass **`contrast127`** to the administrator wrapper. This captures current controls and the 128/127 test in both USB formats, with automatic restoration. The underlying capture helper accepts **`--b128-c127`** for a single recording.
