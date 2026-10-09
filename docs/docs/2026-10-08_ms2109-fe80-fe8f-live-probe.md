# MS2109 FE80–FE8F live scaler-register probe

**Date:** 8 October 2026  
**Target:** attached MS2109, enumerated as `MS2109-Pro`  
**Method:** reversible XDATA RAM writes during continuous YUY2 capture; no firmware or EEPROM writes

## Summary

The FE80–FE8F block is not a width/height pair. The ROM explicitly updates selected mode bits, and the live chart tests show that several fields change detail response or luma mapping without changing the measured image bounds. FE84 and FE85 are horizontal resampling/phase candidates. FE80 bit 0 also changes horizontal detail. FE8E bits 0 and 4 change the captured luma transfer; FE8F bit 0 changes levels in the 720p output path, while bit 4 had no clear effect in these tests. The other bytes remain unresolved after one-bit probes.

No candidate changed the corner-marker geometry beyond 1 pixel in either tested path: 1920×1080 input to 1920×1080 capture, or the same 1080p input to 1280×720 capture. This rules out a large viewport-size or offset change from the tested values in those modes. It does not cover other input timings or display modes.

## Test setup and recovery

The test used a full-frame 1920×1080 grayscale chart with slanted edges, horizontal and vertical line pairs, grids, and flat fields. A separate 1920×1080 corner chart measured image scale, offset, and overflow. Captures ran at 10 fps in YUY2 while the stream stayed open. Each RAM candidate was read back, captured, and restored before the next value.

The stable boot block before and after the probes was:

~~~text
FE80–FE8F  01 00 00 00 7A 00 01 00 11 00 00 00 00 00 00 00
~~~

The 2 KiB EEPROM was read twice before and after. Both reads matched; its SHA-256 remained `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`. Every capture session verified restoration of the FE80–FE8F block. No collateral changes in the block were observed.

## Findings

| Field tested | Live result | Assessment |
|---|---|---|
| FE80.0, `01→00` | Lowered B1 X-varying line-pair contrast at both capture sizes; flat-field levels stayed fixed. Its native B1 response nearly matched FE84=`40`. | Active horizontal-detail/mode-path flag candidate. Exact role is unresolved. |
| FE81.0, `00→01` | A 9-frame repeat produced small B1 changes near the baseline capture variation. | Unresolved; only bit 0 was tested. |
| FE82.0, FE83.0, FE86.0–FE8D.0 | Toggling bit 0 produced no clear response above capture variation in the tested chart and modes. FE88 was tested `11→10`. | Unresolved bytes; this does not clear the untested bits or other timings. |
| FE84, `7A→40` | Reduced X-varying contrast across all measured line-pair pitches at native and scaled capture; Y-varying response stayed effectively unchanged. | Active horizontal resampling/detail parameter candidate. Not a width/height value or decoded sharpness gain. |
| FE85.1, `00→02` | Changed high-frequency horizontal pattern response. The 2-pixel native B1 pattern changed phase; corner-marker scale and offset remained stable. | Horizontal phase/resampling candidate; not an input-size field. Exact arithmetic remains unresolved. |
| FE8E.0, `00→01` | Raised flat-field Y by about 18 codes at native 1080p and 12 codes in 720p capture. | Active luma-offset/mode flag candidate. The silicon field name is unknown. |
| FE8E.4, `00→10` | Compressed grayscale levels and reduced contrast in both tested paths. | Active luma-transfer flag candidate; encoding is unknown. |
| FE8F.0, `00→01` | Changed flat-field levels in the 720p output path; no clear native 1080p response. | Mode-dependent video flag candidate. |
| FE8F.4, `00→10` | No clear pattern or level change in either tested path. | Purpose remains unresolved. |

The firmware audit shows that ROM updates FE8E and FE8F bits 0 and 4 from the same internal mode flag. This run toggled those bits individually to isolate their effects; it did not test the combined paired states. The other otherwise-unreferenced bytes were tested at bit 0 only, not by walking every bit.

### Horizontal response

The 9-frame native baseline B1 Michelson contrasts at source periods 32/16/8/4/2 pixels were `0.3480 / 0.3659 / 0.4024 / 0.4761 / 0.5938`. At FE80=`00` they were `0.3307 / 0.3327 / 0.3367 / 0.3448 / 0.3571`; at FE84=`40` they were `0.3307 / 0.3327 / 0.3367 / 0.3448 / 0.3554`. Their averaged native Y frames differed by 0.705 codes mean absolute; at 1280×720 the difference was 0.058 codes. This shows very similar measured horizontal response, not proof that FE80.0 and FE84 are aliases or share an internal function.

### Corner geometry

At 1920×1080, baseline and each tested candidate (FE80=`00`, FE84=`40`, FE85=`02`, FE8E=`01`/`10`, FE8F=`01`) retained all four markers with fitted horizontal and vertical scale `1.0`, offset `0`, and no predicted overflow.

At 1280×720 capture from the 1920×1080 input, the same candidates retained all four markers with fitted scale `1.0`; fitted offsets were 0.75–1.0 pixels and the largest predicted right/bottom overflow was 1 pixel. The analyzer accepts up to 2 pixels for marker and raster rounding. This pattern therefore showed the expected 1080→720 resize, with no material register-induced viewport shift.

## Evidence files

- Full native and scaled bit probes: [native result](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/native-1080/result.json), [scaled result](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/scaled-1080-to-720/result.json)
- Nine-frame FE80/FE81/FE84 repeats: [native](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/repeat-native/result.json), [scaled](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/repeat-scaled/result.json)
- Corner-marker qualification: [native](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/corner-geometry-native/result.json), [scaled](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/corner-geometry-scaled/result.json)
- Raw captures and chart-session readiness records are in the same `scaler-fe80-8f` artifact directory.
- Reproduction tools: [register sweep](../tools/probe_scaler_register_block.py), [corner probe](../tools/probe_scaler_corner_registers.py)

### Claim-focused visual evidence

- [Horizontal-detail response](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/visual-evidence/detail-response.png) shows matched P4/P2 crops and the nine-frame B1 contrast measurements for baseline, FE80.0, and FE84.
- [FE85.1 phase response](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/visual-evidence/fe85-phase-response.png) shows the native P2 crop and measured sign reversal. This is from the three-frame sweep, not the nine-frame repeat.
- [Flat-field luma levels](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/visual-evidence/luma-levels.png) shows captured black, gray, and white patches with measured mean Y codes for FE8E and FE8F probes.
- [Corner geometry](../artifacts/ms2109-repair/20261008/scaler-fe80-8f/visual-evidence/corner-geometry.png) compares full captures at native and scaled output; the fit values are printed below the captures.
- Re-render the figures with [the evidence renderer](../tools/render_scaler_visual_evidence.py).

The captured values are end-to-end display, HDMI, device, and YUY2 results referenced to the presenter's AppKit source render. They identify relative register responses; they do not isolate an internal silicon stage or define a universal transfer function. The existing static analysis remains at [the FE-range audit](2026-10-08_reverse-ms2109-fe-register-audit-report.html), and the ongoing scaler notes are in [scaler and sharpness](ms2109-reference/scaler-and-sharpness.html).
