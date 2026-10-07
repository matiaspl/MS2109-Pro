# MS2109 FE84/FE85 scaler and native 1080p ROI report

> Analysis date: 2026-10-07
> Target: one connected MS2109 USB capture device
> Analysis type: authorized, RAM-only hardware characterization

## Executive summary

The selected FE85 byte sweep changed horizontal-detail response in the 1920×1080 HDMI input to 1280×720 YUY2 capture path, while the vertical-detail response and uniform-field Y values stayed nearly fixed. A second test used a 1280×720 source chart and 1280×720 capture. A range-aware reanalysis of saved native 1920×1080-to-1920×1080 captures found that FE84=`0x40` matches the AppKit source render after a full-range RGB gray to limited-range Y conversion: `Y = 16 + floor(219 × RGB/255)`. The model is within one Y code across the full frame outside a small top-right overlay window. At the boot value `0x7A`, high-frequency patterns clip and edge A measures +40/−30 codes, supporting an FE84-dependent detail/ringing effect beyond the range conversion. The AppKit render is not a measured HDMI framebuffer, so the fit does not locate the conversion stage or establish the HDMI link range. The native test used neutral procamp controls, unlike the earlier startup-procamp identity comparison; treat them as separate states. The evidence supports FE85 as a probable horizontal-scale high byte and FE84 as an active scale/filter parameter. The ROI histograms show orientation-dependent bar response and high-frequency pattern averaging, while edge profiles quantify value-dependent ringing; they do not identify the internal scaler architecture or establish a comb-filter function. All temporary writes were restored, the monitored registers matched their initial values, and EEPROM SHA-256 remained unchanged.

## Scope and setup

The scope was the user's connected MS2109 unit, USB control/capture path, and HDMI chart source, consistent with the ongoing [project scope](scope.md). The user authorized continuation of the requested FE85 and matched-mode tests. The probes changed only RAM registers FE85 and FE84 through the device's HID B6 control path. They did not write EEPROM or firmware. The chart was verified on the target HDMI display before accepting captures. FE85 used 1920×1080 chart input and 1280×720 YUY2 capture; the matched test used a 1280×720 chart and 1280×720 YUY2 capture.

The FE85 sweep accepted three frames per value at `00, 01, 02, 03, 04, 08, 10, 20, 40, 80, FF`. The matched-mode run accepted eight frames each at FE84=`7A` and `40`. Captures were chart-correlated and flat-field checks were applied. The results describe this device, firmware/EEPROM state, chart, host presentation path and capture mode.

## Findings

### F-001 — FE85 affects horizontal-detail response

- Severity: n/a (register characterization)
- Status: candidate
- Confidence: medium
- Evidence: E-001, E-004
- Location: FE85; see [register table](ms2109-reference/registers.md)

Across the selected sweep, X-varying 8 px stripe contrast moved from 0.237379 at FE85=`00` to 0.194132 at `FF`; the value at `02`/`03` was 0.203299. Y-varying 8 px stripe contrast stayed between 0.085164 and 0.085340, and flat-field Y remained black 16, gray 117, white 232. This direction-specific change is consistent with the static/cross-family evidence that FE84/FE85 form a horizontal-scale pair. The test did not exhaust all byte values or decode the coefficient arithmetic.

### F-002 — FE84 changes fine-detail response; source-to-capture identity remains unresolved

- Severity: n/a (signal-path characterization)
- Status: observed
- Confidence: medium for the relative contrast change; pixel identity unresolved
- Evidence: E-002, E-003, E-005
- Location: FE84; see [scaler investigation](ms2109-reference/scaler-and-sharpness.md#fe85-sweep-and-matched-720p-result)

With equal 1280×720 input and capture rasters, FE84=`40` reduced X-varying stripe contrast against `7A` at each tested pitch. At 2 px, the measured contrast was 0.1112 at `40` versus 0.2094 at `7A`; Y-varying response was effectively unchanged. These measurements use stripe regions without text labels. The earlier whole-frame score—77.50% (`7A`) and 78.65% (`40`) of captured Y samples within one code of the reference—compares against the presenter's AppKit render, not a measured HDMI framebuffer. It also includes antialiased text and display-profile conversion, so it cannot establish a source-to-capture pixel mismatch. The stripe result establishes a relative FE84 response change in this test; it does not prove that `40` is universally neutral or non-neutral.

No tested evidence isolates a comb filter or proves an internal 720→1080→720 conversion. These observations characterize output response only.

### F-003 — ROI histograms show orientation-dependent detail response and high-frequency averaging

- Severity: n/a (signal-path characterization)
- Status: observed
- Confidence: medium for relative output response; no direct HDMI framebuffer reference
- Evidence: E-006, with captures E-001 and E-002
- Location: FE84 / FE85; see [ROI analysis](ms2109-reference/scaler-and-sharpness.md#roi-histograms-aliasing-and-edge-ringing)

At matched 1280×720, the B1 pitch-2 vertical-bar ROI has source histogram modes near normalized luma 0.51/1.00; the captured modes move to about 0.54/0.88 at FE84=`7A` and 0.62/0.80 at `40`. The B2 horizontal-bar ROI changes little between those settings. The C1 one-pixel grid is in the normalized mid band for 96.59% of samples at `7A` and 100% at `40`, while the source is evenly split between low and high. This identifies strong averaging of that Nyquist pattern and a stronger FE84 effect on detail varying across X.

On the 1080p-to-720p path, the pitch-2 B1/B2 bar histogram collapses toward a blended luma near 0.75 and the one-pixel grid is entirely mid-band at the plotted FE85 values, consistent with high-frequency averaging during downscaling. Edge A overshoot/undershoot is +22.31/13.77 codes at FE85=`00`, +0.40/1.28 at `02` and +0.68/0.46 at `FF`. Lower ringing at `02`/`FF` comes with reduced horizontal stripe contrast. At matched 720p, FE84=`7A` has +23/16 codes and `40` has +2.17/13.73 codes. The chart's second edge raster is also dark-to-light despite its label, so the edge-ring result covers only one polarity. These captures characterize output response, not source-to-capture identity; the offline ROI analysis made no device writes.

### F-004 — Test state was restored

- Severity: n/a
- Status: observed
- Confidence: high
- Evidence: E-001, E-002
- Location: monitored RAM registers and EEPROM image

Both result records show the original values after the tests: FE80=`01`, FE84=`7A`, FE85=`00`, F9A0=`00`, F92C=`20`, FEBA=`00`. EEPROM SHA-256 remained `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`; no firmware write was performed.

### F-005 — Full-RGB to limited-Y range mapping explains the native FE84=`0x40` comparison

- Severity: n/a (signal-path characterization)
- Status: observed; native-mode range model
- Confidence: high for code-value agreement; physical conversion stage unresolved
- Evidence: E-007
- Location: FE84; see [native 1080 ROI analysis](ms2109-reference/scaler-and-sharpness.md#native-1080p-to-1080p-roi-response-under-neutral-uvc-controls)

For 1920×1080 chart input and 1920×1080 YUY2 capture, the saved AppKit source render contains gray RGB codes 17/117/232. The model `Y = 16 + floor(219 × RGB/255)` predicts limited-range Y codes 30/116/215. At FE84=`40`, all analyzed B1/C1 ROI histograms and edge A match that mapped reference exactly. Across the full frame, 99.997541% of samples are within one code; outside a conservative 20×20 top-right overlay area, 100% are within one code and the maximum error is one. At FE84=`7A`, only 90.070421% of full-frame samples are within one code of the model; C1 clips to 0/255 and edge A measures +40/−30 codes. The evidence supports the user's full/limited-level explanation for the prior code-value discrepancy and shows an additional FE84-dependent detail/ringing response. The source is still an AppKit render rather than a measured HDMI framebuffer, so this does not locate the RGB-to-Y range conversion stage or prove the HDMI link range. The separate startup-procamp identity run remains a different control state.

## Evidence

| Evidence ID | Observation and source | SHA-256 | Reproduction command |
|---|---|---|---|
| E-001 | FE85 result JSON and per-value raw YUY2 captures: [`artifacts/scaler-f9a0/fe85-scaled-resume-20261007/`](../artifacts/scaler-f9a0/fe85-scaled-resume-20261007/) | Result JSON: `6fdc27196bccfad76509ef28a34ea9eb82e65a17666387ff64e978dd7619ad92` | `python3 tools/probe_fe85_scaled_y.py --chart-session artifacts/scaler-f9a0/chart-session-bidirectional-1080-resume-20261007 --output "/private/tmp/ms2109-fe85-$(uuidgen)"` |
| E-002 | Matched 720p FE84 result JSON and raw YUY2 captures: [`artifacts/scaler-f9a0/fe84-matched-720-20261007/`](../artifacts/scaler-f9a0/fe84-matched-720-20261007/) | Result JSON: `b022efcb7b0f6beeb84bb17c8c9ae035106faf7eb3ce22fc1fc0b39eed253cdf` | `python3 tools/probe_fe84_matched_720.py --chart-session artifacts/scaler-f9a0/chart-session-bidirectional-720-stable-20261007 --output "/private/tmp/ms2109-fe84-$(uuidgen)"` |
| E-003 | Both result JSON files record pre/post RAM reads, register restoration, unchanged EEPROM hash and `firmware_written: false` | Recorded in E-001 and E-002 | Inspect the `registers_before`, `registers_after`, EEPROM hashes, `eeprom_unchanged` and `firmware_written` fields in each JSON file |
| E-004 | Static FE84/FE85 naming and initialization cross-check: the MS2107 source places `vin_hscale_hi` at FE85, clears bit 1, and writes FE84=`7A`; the MS2109 ROM trace is documented in the scaler reference | MS2109 ROM snapshot `backups/ms2109-maskrom.bin`: `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`; related-family source `upstream/macrosilicon_firmware/ms2107/eeprom/eeprom_fw.c`: `0dad9a0a013f5e9c28e361c5bc6f495bc6dd6b32ab4b0fe96482af37f11ad4cc` | `python3 tools/build_programmer_reference.py`; then `rg -n "vin_hscale_hi|vin_hscale_lo" upstream/macrosilicon_firmware/ms2107/eeprom/eeprom_fw.c` and inspect the MS2109 setup path in [the scaler reference](ms2109-reference/scaler-and-sharpness.md#evidence-path) |
| E-005 | Matched-mode display metadata records `source_screenshot_available=false`; the saved `source-render.png` is the AppKit-rendered chart, not a measured HDMI/compositor framebuffer | `bb25d06ff3919646c9c40295fddb0246896d1f606536a39c00fe4c8ac522aba5` | `python3 -c 'import json; p="artifacts/scaler-f9a0/chart-session-bidirectional-720-stable-20261007/display-ready.json"; print(json.load(open(p))["source_screenshot_available"])'` |
| E-006 | Offline B1/B2/C1 ROI histograms and edge profiles from saved raw YUY2 captures: [plot](../artifacts/scaler-f9a0/roi-histogram-20261007/roi-histogram.png), [JSON](../artifacts/scaler-f9a0/roi-histogram-20261007/roi-analysis.json) | JSON SHA-256: `783514e5dd7937161a48695d69aad97951a5c814f120a8a9ad8626a91d17438e`; PNG SHA-256: `e6702ba5af5940947dde179a5b305bbcea1862307a984fc4d1eefbc419a81444` | `python3 tools/analyze_scaler_roi.py --output-dir artifacts/scaler-f9a0/roi-histogram-rerun-20261007` (offline; reads saved chart/captures) |
| E-007 | Range-aware native 1080p dashboard and separated B1/C1/edge plots: [interactive HTML](../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-roi-dashboard.html), [B1 SVG](../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-bars.svg), [C1 SVG](../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-grids.svg), [edge SVG](../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-edge.svg), [JSON](../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-roi.json), [AppKit source render](../artifacts/scaler-f9a0/chart-session-20261007-001220-51789/source-render.png) | HTML: `afc08bee277435dfdcf2dfc185e75eee88fcf091e15b7cff733501d7239ace21`; JSON: `cb857442c061ec44c80350001203411838bd85fd0935a01c4d85cc14977f69e5`; source render: `46006d710cab7c1dd7b941a12bb2e1db9e73b48c64486956b7dcbcc8757ecc1b` | `python3 tools/analyze_native_1080_roi.py --output-dir artifacts/scaler-f9a0/native-1080-roi-rerun-20261007` (offline; reads saved raw frames and AppKit render) |


## Path

### P-001 — Measure a candidate scaler register with a chart-gated RAM probe

- Path type: callflow / measurement
- Start: user-authorized connected MS2109 unit with known register and EEPROM baseline
- Goal: characterize FE85 and compare FE84 at matched 720p dimensions without persistent changes
- Steps:
  1. Verify chart session, capture mode, expected live register values and EEPROM hash before testing — evidence E-001 and E-002.
  2. Write one candidate byte through HID B6, read it back, wait for settling, capture raw YUY2, and reject frames that fail chart correlation — evidence E-001 and E-002.
  3. Measure direction-specific stripe contrast, text-free B1/B2/C1 ROI histograms and edge response from raw luma — evidence E-001, E-002 and E-006.
  4. Restore the starting register values, reread the monitored state, and compare the EEPROM hash — evidence E-003.
- Residual risks: the matched-mode source reference is not a measured HDMI framebuffer; the relative stripe measurement does not prove absolute pass-through fidelity or define FE84's full semantics; selected FE85 values do not define the whole register; internal scaling and comb-filter semantics remain unresolved.

### P-002 — Analyze native-size saved captures with independent ROI plots

- Path type: offline measurement / visualization
- Start: saved 1920×1080 YUY2 captures from the FE84 native sweep and the generated grayscale chart PNG
- Goal: compare each FE84 value's raw-luma distribution and edge response without traces obscuring one another
- Steps:
  1. Validate each saved sweep's dimensions, frame count, RAM/UVC control metadata, and no-persistent-write flags.
  2. Convert the saved grayscale AppKit RGB source render to limited-range Y with `16 + floor(219 × RGB/255)`; retain the original PNG RGB histogram only as separate raw-source data.
  3. Pool all Y samples within each text-free B1 and C1 rectangle, retaining absolute 8-bit bins and separate pitches; compute full-frame agreement and the slanted-edge A profile.
  4. Emit an interactive HTML/SVG dashboard plus independent static SVG plots — evidence E-007.
- Residual risks: the AppKit render is not a captured HDMI framebuffer, so this cannot identify where the range conversion occurs or prove the link's quantization range; this native chart has no B2 horizontal-bar ROI.

## Timeline

- 2026-10-07: completed the selected FE85 sweep with horizontal and vertical stripes; validated chart correlation and flat fields; restored FE85.
- 2026-10-07: held the external display at 1280×720 and compared FE84=`7A` and `40` against a same-size chart; restored FE84.
- 2026-10-07: verified the recorded register state and unchanged EEPROM; updated the programmer reference with the measured results.
- 2026-10-07: computed full luma histograms for text-free B1, B2 and C1 ROIs plus edge response from saved raw captures; made no device writes.
- 2026-10-07: reanalyzed saved native 1920×1080 captures against an AppKit RGB-to-limited-Y model; FE84=`40` matches the full-frame luma within one code outside the top-right overlay window. Updated the dashboard with the range-converted reference; no device writes were made during this analysis.

## Reproduction limits and next step

The live probe scripts require the connected device, the matching EEPROM baseline, the correct test chart displayed full-screen, AVFoundation access to the capture endpoint, and a fresh output directory. They refuse unexpected device state or failed chart correlation. Re-running them performs live RAM writes, even though each run restores the starting value. The new native ROI analyzer and its graph outputs are offline and read the saved chart and captures only. A definitive pixel-path comparison needs a directly observed HDMI raster reference or a trusted hardware pattern generator; the existing GIMP view is consistent with a visual 1:1 match but is not itself a raw HDMI reference. Then repeat a small set of FE84/FE85 values across both 1080p and 720p input modes.
