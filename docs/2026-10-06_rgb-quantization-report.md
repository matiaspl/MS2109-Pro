# MS2109 complete 8-bit RGB ramp quantization

Every input code **0–255** was tested on neutral gray, red, green and blue ramps: **1,024 patches** on the Mac's 1920×1080 HDMI TO USB extended display. This covers all channel levels, not all 16,777,216 RGB triplets. True Tone and Night Shift remained disabled, following the user's stated timeline.

The user requested **brightness 127 and contrast 127 on a 0–255 scale** as the neutral reference for this experiment. The probe measured that setting and the preceding 128/128 UI setting in original USB YUY2 and original USB MJPEG. The macOS host-decoded path was also measured at the preceding setting.

## Control mapping and measured endpoints

Live UVC queries return brightness **−128…127, step 1**, contrast **0…255, step 1**. Brightness uses a signed API value; the equivalent unsigned UI is `brightness_ui = brightness_signed + 128`. Thus the requested UI brightness **127** is signed **−1**. Contrast **127** is passed directly. The [libuvc API](https://github.com/libuvc/libuvc/blob/master/include/libuvc/libuvc.h) declares these controls as signed brightness and unsigned contrast; the actual ranges below were read from this connected device.

| Experiment | Brightness UI | Brightness UVC signed | Contrast | Original gray black/white Y | Original JPEG gray median levels |
|---|---:|---:|---:|---|---:|
| Preceding settings | 128 | 0 | 128 | **16 / 235** | **220** |
| Requested neutral reference | 127 | −1 | 127 | **14 / 232** | **219** |

Both original formats share those median endpoints. At 127/127 the full gray ramp shifts downward and its slope decreases slightly. The fitted YUY2 gray slope changes from **0.858979** to **0.852940**, while its fitted offset changes from **15.5466** to **13.8654**. These are measured control responses; a midpoint of the UI scale and calibrated video black/white endpoints are separate properties. The measured gray response at the preceding settings matches the ordinary limited-range 16–235 endpoints more closely.

UVC `GET_DEF` still reports the old ROM defaults: signed brightness −11 and contrast 148. Those defaults were observed only; they were not applied. [Live control query and active values](../artifacts/color-probe/20261006-quantization/usb/ui127/yuy2/usb-capture.json)

## Quantization across all channel levels

The table counts distinct **median Y/Cb/Cr triplets** among the 256 input codes on each ramp. It does not count RGB gamut colors or infer a general effective bit depth.

| Capture | Gray | Red | Green | Blue |
|---|---:|---:|---:|---:|
| Original YUY2, UI 128/128 | 220 | 169 | 228 | 145 |
| Original MJPEG, UI 128/128 | 220 | 149 | 220 | 120 |
| Original YUY2, UI 127/127 | 220 | 165 | 229 | 145 |
| Original MJPEG, UI 127/127 | 219 | 152 | 221 | 117 |
| macOS-decoded MJPEG path, UI 128/128 | 189 | 132 | 201 | 106 |

YUY2 patch medians can be fractional because a patch contains differing integer pixel values. For example, a Cr median of 238.5 is a statistic from 8-bit samples, not a physical half-code value. At 127/127, YUY2's gray ramp has 220 distinct median values but only **219 distinct raw integer Y codes** across those regions. The raw-code and median counts must remain separate.

### Spatial variation preserved by YUY2 and smoothed in JPEG

YUY2 contains stable spatial patterns with up to **2 codes** of variation inside a constant-color patch. The eight saved frames have zero temporal variation in their patch medians. The probes have not isolated which stage creates those spatial patterns, so this is an observed pattern consistent with dithering, not proof of a specific dithering implementation.

At UI 128/128, the gray ramp has:

| Statistic across 256 gray inputs | Original YUY2 | Original JPEG YCbCr |
|---|---:|---:|
| Distinct patch medians | 220 | 220 |
| Distinct patch means | 238 | 220 |
| Distinct per-patch pixel-code distribution signatures | 255 | 220 |
| Distinct integer Y codes in all sampled pixels | 221 | 220 |

The distribution signature records each component's pixel-code histogram, using the same 512-pixel sampling window per input. It describes this chart and does not establish how another renderer, patch position or consumer perceives each shade. JPEG decompression yields constant samples throughout every measured patch interior; the spatial distinctions visible in YUY2 have been smoothed away before the host's additional range conversion.

For a concrete example at UI 128/128, input gray **127** gives Y=125 everywhere. Input gray **128** in YUY2 has 256 samples at Y=124 and 256 at Y=126: mean and median 125, but a different distribution. The original JPEG gives Y=125 for both inputs. The median-only comparison would miss this difference. At input gray 2, YUY2 has 128 samples at Y=15 and 384 at Y=17, while JPEG is uniformly Y=17. [Complete per-input histograms](../artifacts/color-probe/20261006-quantization/analysis/histograms.json)

### Host MJPEG path loses more steps

At the preceding settings, the original JPEG gray ramp spans **16–235 with 220 levels**. The macOS-decoded packed buffer spans **30–218 with 189 levels**. Across all 1,024 patches, the extra full-to-limited conversion identified in the [original-frame comparison](2026-10-06_uncompressed-mjpeg-color-report.md) predicts the delivered values within **0.263 YUV codes RMS**, compared with **7.181** for unchanged samples.

```text
Y_host  = 16  + (219 / 255) × Y_jpeg
Cb_host = 128 + (224 / 255) × (Cb_jpeg − 128)
Cr_host = 128 + (224 / 255) × (Cr_jpeg − 128)
```

This full-ramp measurement confirms additional collapsed input steps. Reversing the range conversion fixes levels approximately, but cannot restore distinctions that already rounded to the same delivered code. The host-decoded path was not captured at 127/127 in this experiment; its 189-level count applies to UI 128/128.

## Matrix consistency

Original YUY2 and original JPEG patch medians differ by **0.087 YUV codes RMS** at UI 128/128 and **0.152** at UI 127/127. The baseline AVFoundation uncompressed samples match original USB YUY2 patch medians exactly across all 1,024 patches.

At UI 128/128 the direct 709 limited model has **0.717** YUV codes RMS error for YUY2 and **0.707** for JPEG, versus **6.816 / 6.813** for 601 limited. At UI 127/127 the same unadjusted 709 model has **1.649 / 1.620** error; the additional offset/gain comes from the changed controls. Changing the requested neutral reference does not overturn the measured 709 encoding or address the metadata and host range issues.

## Every input value and plots

Each CSV includes all 256 inputs on all four ramps, expected source RGB, median Y/Cb/Cr, and an explicit 709 limited RGB inverse before clipping:

- [Original YUY2, UI 127/127](../artifacts/color-probe/20261006-quantization/analysis/usb-ui127-yuy2.csv)
- [Original MJPEG, UI 127/127](../artifacts/color-probe/20261006-quantization/analysis/usb-ui127-mjpeg.csv)
- [Original YUY2, UI 128/128](../artifacts/color-probe/20261006-quantization/analysis/usb-current-yuy2.csv)
- [Original MJPEG, UI 128/128](../artifacts/color-probe/20261006-quantization/analysis/usb-current-mjpeg.csv)
- [macOS-decoded MJPEG, UI 128/128](../artifacts/color-probe/20261006-quantization/analysis/avf-current-decoded.csv)

[All-ramp plot](../artifacts/color-probe/20261006-quantization/analysis/ramps.svg) · [shadow-step zoom, inputs 0–32](../artifacts/color-probe/20261006-quantization/analysis/shadow-steps.svg) · [step counts, plateaus and numeric analysis](../artifacts/color-probe/20261006-quantization/analysis/analysis.json)

## Acquisition and restoration

The chart uses 32×32 patches, each 60 pixels wide and 33–34 pixels tall. Only the central **8×8 pixels** are sampled, far from the boundaries and JPEG/chroma filtering at color transitions. Eight frames per recording give **512 sampled pixels per input code**. The saved source render matches its display-profile references exactly. Source screenshot permission was unavailable; the reference remains the AppKit render before late compositor/HDMI changes.

The original USB captures ran at 1080p5 YUY2 and 1080p30 MJPEG after a three-second settling interval. Original JPEG payloads were decompressed by libjpeg-turbo to `JCS_YCbCr`, with no RGB matrix or range conversion. All 32 USB frames have valid dimensions and lengths/markers; all JPEGs decode without warnings. The normal macOS runs saved eight uncompressed and eight host-decoded frames.

The first administrator prompt was cancelled: it acquired no original USB frames and changed no controls. The user then explicitly authorized showing it again. Each temporary 127/127 test journaled the current controls, set/read back the requested values through UVC, then restored/read back the original values before releasing the driver. Both successful 127/127 recordings confirm `controls_restoration_ok=true`. Post-capture HID bytes match the original snapshot: `FE90–FE93=00808000`, `C6A0–C6A7=0000800000008000`. Hue and saturation were unchanged. A subsequent real AVFoundation acquisition saved three valid 1920×1080 YUY2 frames. [Before controls](../artifacts/color-probe/20261006-quantization/procamp-before.json) · [after controls](../artifacts/color-probe/20261006-quantization/procamp-after.json) · [restored capture](../artifacts/color-probe/20261006-quantization/driver-restored/capture.json)

No firmware, EEPROM, display profile, global display mode, True Tone or Night Shift setting was changed. The original grabber settings are restored; the requested neutral reference exists only in the test recordings and analysis.

## Reproduction

[probe_quantization.py](../tools/probe_quantization.py) generates the complete chart and analyzes saved frames. Hardware acquisition must run outside the macOS shell sandbox. Build the capture, presenter and administrator helpers as described in the [original-frame report](2026-10-06_uncompressed-mjpeg-color-report.md), using the updated sources.

```sh
mkdir artifacts/color-probe/new-quantization
python3 tools/probe_quantization.py chart artifacts/color-probe/new-quantization/pattern.json
"$probe_tmp/admin-wrapper" "$probe_tmp/capture" "$probe_tmp/presenter" "$PWD/artifacts/color-probe/new-quantization/pattern.json" "$PWD/artifacts/color-probe/new-quantization/usb" quantization
```

For file-only analysis, place the pattern at `RUN/pattern.json`, original captures at `RUN/usb/{current,ui127}/{mjpeg,yuy2}/`, and the presenter output at `RUN/usb-source/`. Optional normal macOS captures use `RUN/avf-current-{yuy2,decoded}/`. Then:

```sh
python3 tools/probe_quantization.py analyze RUN --output RUN/analysis
python3 tools/plot_quantization.py RUN/analysis/plot-data.json --output RUN/analysis/ramps.svg
python3 tools/plot_quantization.py RUN/analysis/plot-data.json --output RUN/analysis/shadow-steps.svg --zoom 0 32
```

Plot generation requires ReportLab. Analysis requires NumPy/Pillow plus the installed libjpeg-turbo headers/library. Output directories must be new; acquisitions and analyses refuse to overwrite existing recordings.

## Isolated brightness 128 / contrast 127 follow-up

The [subsequent isolated test](2026-10-06_brightness128-contrast127-report.md) keeps signed brightness at zero while changing contrast alone to 127. Both original formats produce gray endpoints **15–233**, confirming that UI **128/127 is not a null procamp transform**. Restoring UI 128/128 restores the 16–235 endpoints.
