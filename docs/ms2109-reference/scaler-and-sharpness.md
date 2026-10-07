# Scaler and sharpness controls

**7 October firmware update:** the [compact standard-UVC Sharpness candidate](../2026-10-07_ms2109-compact-sharpness-report.md) fits a 2 KiB EEPROM (1,994 code bytes). It maps host values 0–127 directly to FE84, defaults to 64, holds FE85 at zero, and stores the current setting at overlay byte `CC1A`. RAM qualification passed all GET/SET probes and captured 1080p/720p streams; type 7 advertises Sharpness, while the active type-2 descriptor path remains unresolved. A controlled USB reset cleared the RAM candidate and reloaded the original EEPROM. See the [live qualification report](../2026-10-07_ms2109-compact-sharpness-ram-qualification.md). The underlying register meaning remains uncertain.

6 October 2026. Offline review of the pinned MS2109 mask ROM, factory overlay, descriptor data, and local related-family source, followed by explicitly requested RAM-only live probes. No EEPROM bytes were changed.

## Findings

The strongest scaler lead is **XDATA F9A0 bit 0**. The ROM has a getter at `6F35` that reads `F9A0` through the shared XDATA read helper `700A` and returns bit 0 in carry. Its helper at `6F6D` passes mask `01` and address `F9A0` to `7018`. `7018` copies the mask into the replacement bits before tail-calling `65CD`, so it **sets** the selected bit while preserving other bits. The mode/configuration loop at `2BE5–2C44` calls this setter, then the getter, and branches on that bit. A second caller at `374F–375A` also sets then reads the bit in a related path. This establishes a firmware-used enable/status bit in mode handling; it does not establish a safe scaler bypass control.

The label `scaler_enable` appears for `F9A0` in the local MS2107 source, including its video-reset handler. That gives the MS2109 interpretation a credible cross-family lead. The MS2109 ROM contains no symbol or comment, however, and the two families may differ. Treat “scaler enable” as **probable, not verified**. The reviewed MS2109 ROM path only sets bit 0; it supplies no corresponding clear operation. There is no basis yet for clearing bit 0 or assuming a changed value bypasses scaling cleanly.

The strongest parameter lead is the **FE84/FE85 pair**. In the MS2109 ROM mode-configuration path, `6F3F–6FB4`, the caller supplies `R7=7A`; helper `7011` writes that byte directly to FE84. The same path uses `6A74–6A89` to conditionally set FE80 bit 0, then clear FE85 bit 1 with mask `02`. This is a masked clear (`697C → 000E → 65CD`), not a write of the value `02`. The live post-boot reads match: `FE84=7A`, `FE85=00`, and `FE80=01`.

The related MS2107 firmware declares these exact addresses as `vin_hscale_lo` and `vin_hscale_hi`, and its video-mode handler does `vin_hscale_hi &= 0xFD; vin_hscale_lo = 0x7A`. The matching values and operations make FE84/FE85 **probable horizontal-scale low/high bytes** on MS2109. That is substantially stronger than the F9A0 cross-family lead. Controlled MS2109 tests now show that FE84 changes high-frequency response at 720p, supporting an active scale/filter role; they do not establish exact horizontal-scale arithmetic or prove a user-facing sharpness control. These registers look like scale/filter parameters, not a conventional sharpness gain control.

No sharpness “gauge” or level was identified in the MS2109's advertised controls or reviewed firmware paths. Its Processing Unit advertises brightness, contrast, hue and saturation (`bmControls=0x000F`); it does not advertise sharpness. This only rules out a standard exposed UVC sharpness control in the active descriptor. A private register or fixed internal sharpening stage could still exist.

## Candidate toggle assessment

| Candidate | Evidence | Assessment |
|---|---|---|
| F9A0 bit 0 | MS2109 getter/set-bit pair and mode-path callers; MS2107 labels the address as scaler enable | Probable scaler-enable bit; semantics cross-family and not fully bench-verified |
| FE84 / FE85 | MS2109 video setup writes; MS2107 names these horizontal-scale low/high bytes | Scale/timing candidates; not sharpness controls |
| F6B0, F65C, F65E, F600, F6BE, F6BF | No MOV DPTR immediate or R6:R7 address setup in the pinned MS2109 ROM; no such addresses in the saved EEPROM code | Previously mentioned MS2130 leads do not transfer as MS2109 evidence; computed accesses remain a theoretical limitation |
| UVC sharpness | No sharpness bit in the active Processing Unit bitmap | No standard OS sharpness slider can be expected from this descriptor |

The raw ROM does contain little-endian bytes `B0 F6` and `5C F6` inside the image, but not as reviewed XDATA-address loads. Raw byte matches are not evidence of register accesses. Searching for the standard `MOV DPTR,#addr` sequence and explicit R6:R7 setup found no access to the listed F6xx candidates. The search cannot exclude an indirect table-driven access whose address is computed elsewhere.

## Evidence path

```text
video-mode handling (2BE5–2C44; 374F–375A)
  → set F9A0 bit 0 using mask 01 (6F6D → 7018 → 65CD)
  → read F9A0 bit 0 (6F35 → 700A)
  → branch on returned bit

video configuration
  → FE84 = caller value (6FA3 → 7011; caller supplies 7A)
  → clear FE85 bit 1 with mask 02 (6A83 → 697C → 000E → 65CD)
```

The ROM's `65CD` helper uses R6:R7 as the XDATA address and R5 as a mask; for F9A0, `7018` supplies replacement bits `01`, so other bits are preserved and bit 0 is set. The helper-mediated access therefore does not appear in the generated immediate-DPTR candidate table.

## Live probe

The first run's luma calculations used a too-narrow integer type and overflowed; those metrics are invalid. A USB power-cycle then restored `F9A0=00`, confirmed by live readback, with `F92C=20`, `FEBA=00`, and the EEPROM SHA-256 still `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.

The corrected repeat captured the active HDMI picture at 1280×720 YUY2 with `F9A0=00`, set it to `01`, confirmed readback, and captured again. The measured luma mean (146.188), standard deviation (101.716), average horizontal luma step (6.553), average vertical step (5.435), and sampled RGB color count (2700) matched at reported precision. The raw frame hashes differed, and the source was a live desktop; raw frames were discarded, so this is not proof of pixel identity. It does show no measurable change in these image statistics at this output mode. Thus F9A0 remains an unverified scaler-enable candidate, not a confirmed scaler toggle.

After the corrected capture, writing the saved `F9A0=00` again read back `01`. The EEPROM SHA-256 was unchanged, and `F92C`/`FEBA` remained at their original values. This is consistent with a set-only bit or firmware reassertion; the current evidence cannot distinguish them. After the second USB power-cycle, readback returned `F9A0=00`; `F92C=20`, `FEBA=00`, and the EEPROM SHA-256 remained unchanged. A fresh nonuniform 1280×720 capture succeeded, with all three register values and the EEPROM hash unchanged afterward. Recovery metrics are in `artifacts/scaler-f9a0/live-05/recovery.json`; corrected set-test metrics are in `artifacts/scaler-f9a0/live-03/result.json`.

### Grid-chart retest

To make ringing visible and measurable, `tools/generate_scaler_test_chart.py` generated a 1920×1080 grayscale target with slanted edges, line-pair patches (32–2 source-pixel pitches), and fine grids. The displayed Preview chart was captured through the dongle in 1920×1080 at 5 fps and 1280×720 at the device-supported 10 fps. In both dimensions, frames with `F9A0=00` and `F9A0=01` were compared. The native 1080p RGB frames were byte-for-byte identical. At 720p, 134 pixels differed only in the small mouse-pointer rectangle (`x=44..61, y=37..48`); the slanted-edge and grid regions had matching statistics. On the 1080p capture, a luma profile across each slanted edge measured a +3-code peak above the 252-code white plateau and no undershoot below the 0-code dark plateau. This is a property of the full display/capture path, not attributable to F9A0; it was unchanged in the F9A0=01 capture. Thus the tested F9A0 bit produced no observed change in edge ringing or grid resolution for this source and these capture modes. This does not rule out effects in another timing or processing path.

The attempt to write `F9A0=00` after the test again read back `01`. Readback during capture remained `01`; `F92C=20`, `FEBA=00`, and the EEPROM SHA-256 remained unchanged. After the user power-cycled USB, an initial enumeration check raced with reconnect and failed. A later read-only retry succeeded: `F9A0=00`, `F92C=20`, `FEBA=00`, and the EEPROM SHA-256 still matched. A fresh 1920×1080 capture showed the grid chart again. Evidence (including PNG frames and lossless capture files) is in `artifacts/scaler-f9a0/grid-01/`; the register snapshots and comparison summary are in `grid-f9a0-result.json`, and post-cycle state is in `post-power-cycle.json`.

The saved native-size capture also quantifies the user's observed one-pixel effect. Relative to the generated source chart, the decoded 1080p vertical-patch Michelson contrast rises from 0.295 to 0.378, 0.395, 0.426, 0.496, and 0.640 at stripe periods 32, 16, 8, 4, and 2 pixels. The 2-pixel patch's nominal gray trough (source luma 128) averages 56, while its white line reaches 255. The same result appears with F9A0 at 00 and 01. This is consistent with strong frequency-dependent edge enhancement/overshoot in the end-to-end chain, especially over gray, and aligns with the visual report. It does not isolate the MS2109 from the Mac display/HDMI path or the YUY2-to-RGB conversion. Reproduce with `tools/analyze_scaler_chart.py`; results are in `artifacts/scaler-f9a0/grid-01/spatial-response.json`.

### Present the chart on the HDMI target

`tools/show_scaler_chart.py` now uses the same AppKit presenter as the color-patch workflow. It renders the 1920×1080 raster 1:1, borderless, on the uniquely matched `HDMI TO USB` extended display. It writes `display-ready.json` only after confirming the target display and source raster, and stops if either check fails. Run it from the repository root; press Ctrl-C to close the chart early:

```sh
python3 tools/show_scaler_chart.py --seconds 3600
```

The chart remains on the HDMI output while register tests run. Pass that session directory to the guarded probe below; it checks the presenter's readiness record and verifies the captured frame resembles the chart before any register write.

### FE84 response test

Live boot values were `FE80=01`, `FE84=7A`, `FE85=00`, and `F9A0=00`. The first FE84 capture attempt did not write anything because QuickTime held the AVFoundation stream. After the preview was stopped, RAM-only captures were made at 1080p and 720p. FE84 was restored to `7A` after each test; FE85 stayed `00`, and the EEPROM hash remained unchanged.

At 1080p, `FE84=7A→7B` produced no edge-crossing shift and effectively unchanged stripe contrast. In the scaled 720p path, the 7A baseline was captured twice and the full RGB frames were byte-identical. At `7B`, Michelson contrast rose slightly in the 8-pixel and 4-pixel source stripe patches (0.25018→0.25196 and 0.11481→0.11646). A larger reversible step, `7A→80`, raised them further to 0.25532 and 0.11862, while 32/16-pixel patches moved by only about 0.001 and detected edge crossings remained at the same integer pixel. The checkerboard and 2-pixel source patch alias to flat gray at 720p and are not informative there.

The first negative-step attempt (`7A→74`) was invalid because the displayed source changed away from the test chart; its captures were deleted and no result was used. After implementing the full-screen presenter, a chart-gated repeat captured two 720p baselines, required at least 0.85 image correlation with the chart, and allowed only small baseline variation before writing. The baselines correlated at 0.9388; they differed in 0.149% of pixels, with a 0.0026 mean absolute RGB delta.

The quality gate now treats any change in a large uniform field as a failed setup. Across 20 frames from each baseline, early/settled candidate, and restored capture, the gray field (1240×7 px) remained exactly RGB 118/118/118, the black plateau (170×440 px) remained 0/0/0, and the white plateau (130×440 px) remained 252/252/252. All three fields had zero nonmatching pixel samples across all five recordings. The small whole-frame differences above were outside these flat-field ROIs, in chart detail such as labels, borders, and line patterns; they are not accepted as variation inside a uniform field. `tools/probe_fe84_negative.py` now checks every decoded frame and aborts before scoring or writing if any flat-field pixel differs from baseline.

At `FE84=74`, the 4-pixel patch contrast fell from 0.114809 to 0.110174 and the 8-pixel patch fell from 0.250177 to 0.245873. The 32- and 16-pixel changes were smaller; the 2-pixel patch remained aliased to gray. The edge crossing did not move at integer-pixel precision. Early and settled captures, separated by several seconds, had the same measured stripe contrasts; their full-frame difference was sparse (1,380 pixels; 0.0026 mean absolute RGB delta). Restoring `FE84=7A` returned the measured stripe values to baseline. Live readback confirmed FE84=7A, FE85=00, FE80=01, F9A0=00, F92C=20 and FEBA=00; the EEPROM hash remained `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.

The symmetric response to raising and lowering FE84, together with unchanged edge positions, supports a scale-dependent filter/coefficient interpretation. The lack of early-to-settled contrast drift provides no evidence for a delayed auto-calibration response over this interval. It does not rule out phase detection that settles faster than the first capture or calibration triggered by a mode change, signal loss, or power cycle. Exact coefficient semantics remain open. Evidence and analysis are in `artifacts/scaler-f9a0/fe84-negative-20261007-001657/`; reproduce the response and strict flat-field checks with `tools/analyze_fe84_negative.py`.

This repeatable, frequency-dependent response makes FE84 a live scaler/filter coefficient candidate and links it to the user's visible gray-area ringing. However, the unchanged edge positions and one tested input/mode do not establish the exact coefficient encoding or prove FE84 is a sharpening-gain control. Reproduce the patch statistics with `tools/analyze_fe84_scale_probe.py`; the JSON summaries are `fe84-step-test.json`, `fe84-step-720-test.json`, `fe84-80-test.json`, and `fe84-spatial-response.json` in the grid evidence directory.

### Native 1080 luma-identity probe

The acceptance comparison is now native 1920×1080 YUY2 Y samples against the presenter’s 1:1 AppKit source render. It does not compare RGB-decoded video, and it does not score captures at a different output size. Eight raw AVFoundation-delivered YUY2 frames were captured for each stage. The source chart and target display profile are recorded in `artifacts/scaler-f9a0/chart-session-20261007-001220-51789/`.

At the current startup procamp (`FE90–FE91=EE 95`, brightness −18 / contrast 149), baseline `FE84=7A` increased luma contrast with spatial frequency: Michelson contrast was 0.347 at 32 pixels, 0.404 at 8 pixels, 0.478 at 4 pixels, and 0.599 at 2 pixels. With a temporary RAM-only `FE84=40`, the 32-, 16-, 8-, 4-, and 2-pixel patches all captured as Y=232/117, exactly matching their AppKit-rendered source levels at the same coordinates. Their contrast was 0.329513 at every period. This is the first tested FE84 value that meets the native chart’s pixel-phase and frequency-response target.

Across each of the eight complete frames, BT.709 luma from the source render and captured Y differed by at most one code on 99.99749% of pixels. The 52 larger residuals occupy an 8×8 area near the top-right corner (bbox `[1908,4,1916,12]`); this region is absent from the cached AppKit source render and appears to be a late system overlay such as the pointer. Outside the conservative 20×12 top-right overlay area, every captured Y sample in all eight frames was within one code of the source-render luma. In large flat chart fields and the five frequency patches, the measured levels matched exactly.

The FE84 sweep under neutral UVC procamp 0/128 also brackets the response: `40` gave 0.299 contrast at all five periods (source: 0.294766); `30` and `20` softened the fine patterns, while `60` and higher retained increasing high-frequency boost. Under the existing startup procamp, `40` matched the source-render luma exactly in the stripe regions. This shows a useful native-mode operating point, but does not establish the register’s arithmetic or prove the same byte is appropriate for scaled outputs. `FE84=40` was restored to `7A` after every probe; brightness, contrast, UVC shadows and the EEPROM image were also restored/verified. The EEPROM SHA-256 remained `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`.

Reproduce the guarded RAM-only sweep with the chart visible on `HDMI TO USB`:

```sh
python3 tools/probe_native_luma_identity.py \
  --output artifacts/scaler-f9a0/native-luma-identity-rerun \
  --fe84-current-values 40 --fe84-values 40 60 74 7a 80
```

The script refuses an unexpected EEPROM or initial control state, records raw YUY2 frames, writes only RAM, restores FE84/procamp/UVC-shadow values in `finally`, then verifies the EEPROM hash. The measured result is in `artifacts/scaler-f9a0/native-luma-identity-fe84-current-20261007/result.json`; the FE84 candidate’s raw payload SHA-256 is `c6fc7c67d22a614348b9bc85f97d40fd2e6fb29b93ec8c6882b9d277b57c0965`.

Treat `FE84=40` as a **validated native-1080 candidate**, not a persistent fix yet. No EEPROM write was made. Before making it persistent, test the coefficient on deliberately downscaled and upscaled modes, then determine whether ROM mode setup can select `40` only for exact 1920×1080 input/output. The current mode path writes `7A` directly, and FE84 remains a probable horizontal-scale/filter byte rather than a decoded sharpness control.

### Native 1080p-to-1080p ROI response under neutral UVC controls

A separate saved sweep measured 1920×1080 input to 1920×1080 YUY2 capture with RAM controls `00809300` and UVC shadow state `0000800000009300`. It samples FE84=`20, 30, 40, 60, 68, 70, 74, 7A, 80`; eight frames per value were pooled. The first comparison used the generated PNG's RGB codes directly against captured Y codes. That mixed two code spaces.

The saved AppKit source render is grayscale RGB with representative values 17, 117, and 232. Mapping those codes to nominal limited-range Y with `Y = 16 + floor(219 × RGB/255)` predicts 30, 116, and 215. In this saved FE84=`40` session, that mapped reference matches every tested B1/C1 ROI histogram and edge A exactly; outside a conservative 20×20 top-right overlay window, every full-frame sample is within one code. This establishes a good fit for that session, not a universal level mapping.

In that neutral-control session, FE84=`40` is the native-size identity candidate under the range-converted model. FE84=`7A` matches the model within one code on only 90.070421% of full-frame samples; its C1 one-pixel grid clips to 0/255 and edge A measures +40/−30 codes. FE84=`60` already measures +23/−23 codes. The earlier startup-procamp test also found `40` matched selected source-render luma levels; it used different procamp controls and remains a separate measurement. A later native FE85 test found a different level fit: its fresh FE85=`00`, FE84=`40` capture matched direct AppKit Y codes within one code everywhere outside the top-right overlay (MAE 0.331), while the limited-range model had MAE 9.928 and only 36.03% within one code. The old and new source-render grayscale pixels were identical, but the saved display ICC profile changed. This supports your full/limited-level explanation for apparent code differences, while showing the mapping can depend on the display/link session or capture path.

Neither model identifies the conversion stage or proves the HDMI link's quantization range: the AppKit source render is not a measured HDMI framebuffer. The saved chart has B1 vertical bars and C1 grids but no B2 horizontal-bar patch. The [native 1080 dashboard](../../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-roi-dashboard.html) plots the earlier range-converted model with selectable FE84 traces. Static SVGs show [B1 bars](../../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-bars.svg), [C1 grids](../../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-grids.svg), and [edge A](../../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-edge.svg). The new [native FE85 dashboard](../../artifacts/scaler-f9a0/native-fe85-1080-analysis-20261007/native-fe85-1080-dashboard.html) plots both level fits and the phase-sensitive ROIs separately. See the [follow-up report](../2026-10-07_ms2109-fe85-native-report.md) for the session/profile comparison. The [earlier machine-readable measurements](../../artifacts/scaler-f9a0/native-1080-roi-final-20261007/native-1080-roi.json) and offline [FE84 analysis script](../../tools/analyze_native_1080_roi.py) remain reproducible; the FE85 plots are built by [the native FE85 analyzer](../../tools/analyze_native_fe85.py).

## Reproduce the static review

From the repository root, with radare2 installed:

```sh
r2 -q -a 8051 -b 8 -m 0 -c 's 0x2be5; pd 100; s 0x3749; pd 24; s 0x6f35; pd 18; s 0x6f64; pd 24; s 0x6a74; pd 24; s 0x6fa3; pd 15' backups/ms2109-maskrom.bin
```

Cross-family names come from `upstream/macrosilicon_firmware/ms2107/eeprom/eeprom_fw.c` (declarations around lines 72–83 and video handlers around lines 515–524 and 621–622). They are references, not MS2109 documentation. The active MS2109 UVC descriptor bitmap and existing caveat are recorded in [the color report](../2026-10-05_reverse-ms2109-color-report.md#f-procamp-hardware-gain-offset-saturation-and-hue-controls).

## What would resolve the toggle question

The FE84 call trace is now partly mapped: `0x3F0B` reaches the fixed `FE84=7A` writer at `0x3F84 → 0x6F3F → 0x6FA3`, and two routines call `0x3F0B` (`0x31D7`, `0x5375`). No exact input/output-dimension test has been established around that write. An initial 1280×720 capture of the desktop was discarded. The later chart presenter worked after launch with host permissions; chart-correlated raw YUY2 tests found that `FE84=40` reduces the 32/16/8/4-pixel stripe contrasts versus `7A` while preserving the sampled black, white and gray fields exactly at Y=16/232/117. A coarse `0x40–0x80` sweep and selected byte-endpoint probes from `0x00–0xFF` now measure the response; `40` is not a proven global setting, and native-only selection remains blocked on finding a mode discriminator. The guarded tests verify chart correlation and flat-field constancy. A control-bit readback alone does not prove scaler bypass. No independent sharpness gain register has been established.

### Scaled 720p response across a coarse FE84 range

A RAM-only sweep sampled 19 values from `0x40` through `0x80`, including `0x7A` and `0x7B`, with three packed-YUY2 frames at each value. The chart correlation stayed between 0.933538 and 0.949013. Sampled interior black, white and gray fields remained exactly Y=16, 232 and 117 at every value. The EEPROM SHA-256 was unchanged, and FE84 plus FE80/FE85/F9A0/F92C/FEBA were restored and read back. A later set of bracket probes extended the sampled values to `0x00` and `0xFF`; those results are below.

Michelson contrast for the line-pair patches rose substantially with FE84. The 2-source-pixel patch remained at near-zero contrast because it aliases in this 1280×720 mode.

| FE84 | 32-pixel stripes | 16-pixel | 8-pixel | 4-pixel |
|---:|---:|---:|---:|---:|
| `40` | 0.294371 | 0.251617 | 0.198274 | 0.074728 |
| `50` | 0.297333 | 0.256954 | 0.211715 | 0.083814 |
| `60` | 0.301220 | 0.262576 | 0.223944 | 0.088721 |
| `70` | 0.304228 | 0.267211 | 0.233201 | 0.093974 |
| `7A` | 0.305755 | 0.269474 | 0.238845 | 0.102375 |
| `80` | 0.306627 | 0.270567 | 0.242192 | 0.107296 |

Across the sampled band, the endpoint increase was 4.2% at 32 pixels, 7.5% at 16 pixels, 22.2% at 8 pixels, and 43.6% at 4 pixels. The response is **near-monotonic**, not strictly monotonic: the 16-pixel result dips by 0.000176 from `7A` to `7B`, and the 8-pixel result dips by 0.000181 from `7B` to `7C`. This coarse sweep supports a useful FE84-controlled detail fader in this one mode, but it does not test every byte or establish the correct setting for other sizes.

Reproduce the sweep with the chart visible on `HDMI TO USB`:

```sh
python3 tools/show_scaler_chart.py \
  --output artifacts/scaler-f9a0/chart-session-fe84-range-20261007 --seconds 3600
python3 tools/probe_fe84_range_scaled_y.py \
  --output artifacts/scaler-f9a0/fe84-range-scaled-y-20261007 \
  --chart-session artifacts/scaler-f9a0/chart-session-fe84-range-20261007
```

The probe refuses an unexpected EEPROM or startup register state, verifies the displayed chart from every set of captured frames, checks flat fields at every value, writes only RAM, restores FE84 in `finally`, and verifies EEPROM plus neighboring register readback. Raw frames and the complete result are in `artifacts/scaler-f9a0/fe84-range-scaled-y-20261007/`; the result JSON SHA-256 is `2f6acb7781984b9ff565b4d23a2cb64334216d1f8a003056109bd590fd33d9ec`.

### Extended FE84 byte range (`0x00–0xFF`)

Two guarded RAM-only probes sampled the lower and upper brackets, each with three raw YUY2 frames per setting. They tested `00, 01, 02, 04, 08, 10, 20, 30, 3F, 40, 50, 60, 7A, 7F, 80, 81, 82, 88, 90, A0, B0, C0, D0, E0, F0, FF` (hex). Every requested byte read back exactly, including the high-bit boundary `7F → 80 → 81`; captures at both endpoints remained chart-correlated. The response changed across that boundary, so the result is inconsistent with a seven-bit value masked to `0x7F`. This confirms an 8-bit write/read path and active bit 7 for this mode; the sparse samples do not prove that all 256 codes produce unique output levels.

| FE84 | 8px contrast | 4px contrast | Interpretation |
|---:|---:|---:|---|
| `00` | 0.145443 | 0.018765 | Lowest tested detail response |
| `10` | 0.158092 | 0.032964 | Lower values still change the response, with a smaller step near zero |
| `40` | 0.198274 | 0.074728 | Native-1080 luma-identity candidate; scaled mode is softer here |
| `7A` | 0.238845 | 0.102375 | Live startup value |
| `7F` | 0.241480 | 0.106438 | Just below the high-bit boundary |
| `80` | 0.242192 | 0.107296 | Just above the boundary |
| `81` | 0.242765 | 0.108807 | Confirms a response change above `0x80` |
| `A0` | 0.262976 | 0.135415 | Upper-range response continues changing |
| `B0` | 0.274566 | 0.145417 | 4px contrast reaches its sampled maximum near here |
| `E0` | 0.310356 | 0.137375 | 8px response continues rising while 4px response eases |
| `FF` | 0.333640 | 0.134502 | Maximum byte tested; still chart-valid |

Across all tested values, chart correlation ranged from 0.909452 to 0.957335, and sampled flat fields stayed exactly Y=16/232/117. Each run restored FE84 to `7A`; FE80/FE85/F9A0/F92C/FEBA also matched their pre-test reads. EEPROM SHA-256 remained `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. Result files: [lower bracket](../../artifacts/scaler-f9a0/fe84-range-low-20261007/result.json) (SHA-256 `3c0a5d197833fd2f959150d98be3046a0ae9120da0516f277b1605487af9ddac`) and [upper bracket](../../artifacts/scaler-f9a0/fe84-range-high-20261007/result.json) (SHA-256 `761d690d75078347dd3a0297e0a71cfd61e0dc6ef058e77c614a652d17bfe288`). The `.yuy2` captures alongside them contain the raw measurements.

The full byte range is therefore available to an 8-bit host-side mapping, but the control is **not** a simple “more sharpness” scale: spatial frequency matters, `0x40` is the native 1080p identity candidate but reduces fine detail at scaled 720p, and the 4px response turns down above roughly `0xB0`. A mode-aware UVC fader needs mode qualification and an explicit policy for whether its endpoints mean “softest/sharpest” or expose the raw coefficient.

### Could FE84 drive a host UVC slider?

Engineering answer: the complete byte endpoints and the `0x7F/0x80/0x81` boundary are now chart-tested at 1280×720. This supports mapping an 8-bit FE84 value to a normalized host fader, but does not make the curve a conventional sharpness gain: 8px contrast continues upward through `0xFF`, while 4px contrast peaks near `0xB0` and then decreases. The attached device does **not** expose that slider yet: its Processing Unit bitmap is still `0x000F`, and the ROM's Sharpness selector-`0x08` callback is not implemented. Standard UVC assigns bitmap bit `0x0010` to Sharpness and selector `0x08` with a 16-bit payload. Advertising bitmap `0x001F` and implementing Sharpness `GET_*`/`SET_CUR` requests could make Windows expose its standard Sharpness setting and let Linux map it to `V4L2_CID_SHARPNESS` ([Windows camera settings](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/camera-settings-page), [Linux UVC control implementation](https://github.com/torvalds/linux/blob/master/drivers/media/usb/uvc/uvc_ctrl.c), [UVC selector definitions](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/video.h)). Capture-size and mode-specific behavior remain unqualified.

The callback would need to translate the standard 16-bit value and range into FE84's single byte, and return truthful `GET_CUR`, `GET_MIN`, `GET_MAX`, `GET_RES`, `GET_DEF`, and `GET_INFO` responses. The descriptor must be updated consistently in its active and alternate copies, and the class-request path must accept selector `0x08`; changing only the bitmap would advertise a nonfunctional control. The saved ROM routes control requests through the built-in dispatcher at `0x2AD0` and fixed handler branches. One ROM path recognizes UVC GET request codes `0x81–0x84`, but does not establish selector `0x08` support or all required queries. The EEPROM hook can replace the dispatcher when `CBD4.1` is set, but the installed flags are `0x05` and the existing `CC10` entry is also the factory video-table helper. A new handler must multiplex that call and delegate all unrelated USB requests to ROM. The new offline implementation below adds the query/set path and modifies only a guarded RAM response copy of each descriptor; it has not been loaded into the device. See the [saved UVC dispatch transcript](../../artifacts/programmer-reference/uvc-sharpness-dispatch.txt). FE84 remains a probable horizontal scaler/filter coefficient, not a decoded sharpness gain. Calling it “Sharpness” is a convenient standard-host mapping; the agreed profile uses the standard control with a seven-bit range and applies it to every mode. No descriptor or EEPROM change has been made.

### Standard UVC Sharpness build status

**ROM-only variant:** omitting the custom EDID and using ROM `7738` directly saves 175 bytes in the current packing: 2,439 code bytes, **443 bytes over** the 1,996-byte limit. The ROM still advertises preferred 1080p60, includes 720p60 and has the same audio capability block. The extra custom video modes and display/range fields are dropped. Both variants pass the expanded 49-test offline suite; neither is installed or fits the EEPROM yet. See the [ROM-only option and reproducible evidence](../2026-10-07_ms2109-uvc-sharpness-report.md#rom-only-edid-option). The accounting below describes the retained custom-EDID variant.

The complete offline handler is implemented in [`sharpness_firmware.py`](../../tools/sharpness_firmware.py). Its USB data-stage and descriptor-response paths execute successfully against the saved ROM in an instruction harness. **The current implementation exceeds the 2 KiB EEPROM limit by 618 bytes:** 2,614 code bytes versus the allowed 1,996. No EEPROM image is emitted and no live hook was installed. This is the measured size of this implementation, not proof that a smaller implementation is impossible.

The agreed contract is unit 2, selector `0x08`, VideoControl interface 0; unsigned 16-bit little-endian transfers; values 0–127; default 64; direct mapping to FE84; FE85 fixed at `0x00`. The selected byte lives at `D4FB` in this build. The stage-1 callback initializes it to 64; stage 2 and delegated USB calls repair FE84/FE85 without changing the selection. Repair writes only when readback differs. Offline tests simulate register changes between polls; physical stream restarts and HDMI recovery remain untested.

| Resolved path | Contract and evidence |
|---|---|
| CC10 multiplexing | Return address `4792` identifies ROM USB dispatch; other callers reach the factory video helper. Unrelated requests delegate to `2AD0`. |
| Parsed setup | IRAM `0B/0C`: request type/code; `0D/0E`: wValue high/low; `0F/10`: wIndex high/low; `11/12`: wLength high/low. Sharpness is wValue=`0800`, wIndex=`0200`. The payload remains little-endian. |
| SET_CUR | Acknowledge setup with SFR `80.6`, wait for `80.0`, set generic destination `01:C020` through `4B69`, read two bytes through `62CA`. Validate high byte zero and low byte below 128 before updating state. |
| Queries and completion | Stage response at `C020`, send through `49C2`, finish through `2B8E`. GET_INFO is one byte `03`; other replies are two bytes. Invalid targeted requests set the ROM stall flag. |
| Active configuration | ROM standard-request branch `0C79` uses helper `4B10`, which reads the selected source pointer at `C002:C003` (`C03A` in the live probe). The staged hook did not alter the raw type-2 response; changing XDATA `C07B` also left it at `0F`. This path needs its serving source or startup snapshot point identified before claiming the active descriptor is patched. |
| Other speed | ROM branch `0D8D` uses helper `4B37` to select CODE `75CC`, length 355. The guarded overlay copy successfully changes this response to bitmap `001F`. |
| Packet continuation | Bound the response to min(wLength, descriptor length), send at most 64 bytes per callback, preserve the original setup/cached lengths, and maintain ROM remaining-count bytes `08:09`. |

The custom EDID occupies the original `CD52–CE51` table area as a 124-byte lossless ROM-relative delta, an 84-byte decoder and a 44-byte repair helper, with four bytes unused. ROM `7738–7837` supplies the base EDID. Reconstruct into `DD00–DDFF` before invoking the factory upload routine `6345`; all 256 uploaded bytes match the original custom EDID in execution tests. Literal-reference scans and the pinned `D118` caller support this reuse, but do not constitute an exhaustive computed-reference audit.

The descriptor buffer `D800–DCBA` and EDID buffer `DD00–DDFF` do not overlap the generated overlay `CC00–D635`. These are proposed scratch allocations; full ROM/interrupt ownership and live reentrancy are still qualification gates. The complete generated code has independently decoded branch destinations. All 36 repository tests pass, including 12 new handler tests covering all 128 values and queries, invalid requests, descriptor packet boundaries and guards, register preservation at the stock bank-zero ABI, calibrated/audio-write equivalence, and exact EDID reconstruction. Audio/streaming/HID delegation has a routing-context test; it is not end-to-end device qualification.

Run `python3 tools/qualify_sharpness_offline.py artifacts/sharpness-firmware/new-offline-run` to create a new bundle. The builder's `--sharpness-profile --rom backups/ms2109-maskrom.bin` option refuses the oversized profile before writing an output file. See the [qualification report](../2026-10-07_ms2109-uvc-sharpness-report.md), [memory/size manifest](../../artifacts/sharpness-firmware/20261007-offline/qualification.json), [decoded hooks](../../artifacts/sharpness-firmware/20261007-offline/decoded-hooks.txt), and [test log](../../artifacts/sharpness-firmware/20261007-offline/tests.txt). The saved calibrated stereo rollback image remains the release reference. USB timing, interrupted or short OUT transfers, real scratch ownership, native/scaled captures, and Linux/Windows control discovery remain unqualified. No EEPROM, flash or device RAM write occurred during this implementation pass.

### EDID and the 720p-to-1080p scaling claim

The mask-ROM default EDID at CODE `7738–7837` does not stop at 720p. Its base detailed timing is 1920×1080p60 (148.5 MHz, 2200×1125 totals), its CTA extension includes 1080p60 VIC 16 and 720p60 VIC 4, and both checksums pass. The attached `HDMI TO USB` display was running at 1920×1080@60; 1280×720@60 was also available. The full byte-level summary is in the [register reference](registers.md#rom-edid-table-code-space).

Keep three mode lists separate: HDMI timings offered to the source by EDID, the actual HDMI input timing, and USB/UVC capture-output formats. The manufacturer datasheet lists 1920×1080@60 among supported HDMI input modes and separately lists default USB output modes (including YUV422 1920×1080@5 and 1280×720@10); it also says external EEPROM can supply a custom EDID. Those USB-output limits do not imply that the HDMI EDID advertises only 720p, and EDID selection alone does not show an internal downscale/upscale stage. See the [MacroSilicon MS2109 datasheet](https://atta.szlcsc.com/upload/public/pdf/source/20241106/63E0CC799512327484A4AEBE801A6447.pdf).

One published “720p EDID versus 1080p capture” result concerns a **different VGA capture board** with an MS9288A analog receiver/scaler beside its MS2109. It cannot establish the HDMI-only processing path on this unit ([board teardown and A/B test](https://www.kernel-error.de/2026/05/29/ms2109-vga-usb-capture-reverse-engineering-edid-1080p/)).

The updated [bidirectional chart](../../artifacts/scaler-f9a0/test-chart-bidirectional-v2-1920x1080.png) adds horizontal and vertical line pairs. Its 2-pixel source bars are expected to lose contrast when 1080p is reduced to a 720p capture; that is a cross-resolution resampling result, not evidence of bad 1:1 luma. The dedicated [FE85 sweep](../../tools/probe_fe85_scaled_y.py) measures the 1080p-input→720p-capture path. A separate [matched 720p probe](../../tools/probe_fe84_matched_720.py) compares FE84=`7A` and `40` with a 1280×720 input chart and 1280×720 YUY2 capture against the presenter's same-size source render.

### FE85 sweep and matched 720p result

On 7 October 2026, the FE85 probe sampled `00, 01, 02, 03, 04, 08, 10, 20, 40, 80, FF` with a 1920×1080 chart on HDMI and 1280×720 YUY2 capture. It captured three frames per value and required chart correlation before accepting them. Horizontal-detail response is represented by vertical bars varying across X; vertical-detail response is represented by horizontal bars varying across Y.

| FE85 | X-varying 8 px contrast | Y-varying 8 px contrast |
|---:|---:|---:|
| `00` | 0.237379 | 0.085300 |
| `01` | 0.237379 | 0.085300 |
| `02` | 0.203299 | 0.085164 |
| `03` | 0.203299 | 0.085164 |
| `04` / `08` | 0.237379 | 0.085300 |
| `10` | 0.236470 | 0.085288 |
| `20` | 0.234605 | 0.085291 |
| `40` | 0.231865 | 0.085305 |
| `80` | 0.226750 | 0.085340 |
| `FF` | 0.194132 | 0.085193 |

The X-varying 8 px response changes with FE85 while the Y-varying response stays within 0.085164–0.085340. At every value, the captured black, gray and white interiors remained exactly Y=16, 117 and 232. At `00`, `01`, `04` and `08`, the measured X response matched; `02` and `03` also matched each other. This supports FE85's probable horizontal-scale high-byte role, but the selected values are not a complete decode of the byte or its arithmetic.

The matched-mode test then presented a 1280×720 chart at 1:1 and captured 1280×720 YUY2, with eight frames each at FE84=`7A` and `40`. The table gives Michelson contrast by chart stripe pitch, in source pixels. X-varying stripes test horizontal spatial detail; Y-varying stripes test vertical spatial detail.

| FE84 | X-varying stripes, pitches 32 / 16 / 8 / 4 / 2 px | Y-varying stripes, pitches 32 / 16 / 8 / 4 / 2 px |
|---:|---|---|
| `7A` | 0.3173 / 0.3152 / 0.3173 / 0.3191 / 0.2094 | 0.2937 / 0.2562 / 0.1932 / 0.0533 / −0.0957 |
| `40` | 0.3071 / 0.2940 / 0.2703 / 0.2280 / 0.1112 | 0.2937 / 0.2563 / 0.1933 / 0.0534 / −0.0958 |
| Source render | 0.3295 at all pitches | 0.3268 at all pitches |

FE84=`40` reduced X-varying contrast at every sampled pitch relative to `7A`, with the largest separation at the 2 px pitch (0.1112 versus 0.2094). The Y-varying response was effectively unchanged. This is a relative response change between two captured register states; the text labels are outside the stripe measurement regions. The earlier whole-frame comparison reported 77.50% (`7A`) and 78.65% (`40`) of captured samples within one code value of the reference, with mean absolute error 11.47 and 11.10 codes. That reference is the presenter's AppKit render, however, not a captured HDMI framebuffer: the session record says `source_screenshot_available=false`. The whole-frame score also includes antialiased text and display-profile conversion. It therefore does **not** settle whether the input and capture are pixel-identical, and does not refute a visual 1:1 match in GIMP. The text-free stripe regions support a relative FE84 response change, but the absolute source-to-capture fidelity and whether `40` is neutral remain unresolved. This result does not identify the internal scaler architecture, prove a 720→1080→720 stage, or establish any comb-filter function.

### ROI histograms: aliasing and edge ringing

The offline analysis uses rectangular, text-free ROIs from B1 vertical bars, B2 horizontal bars and C1 grids. It histograms every captured Y sample in each ROI, so the distribution does not depend on whether an individual transition is light-to-dark or dark-to-light. B1, B2 and C1 remain separate in the JSON; the figure pools B1/B2 pitch-2 bar samples only for an orientation-neutral overview. Histograms are normalized to the measured black/white edge plateaus; the source raster uses its nominal 16/235 levels. Edge A is also measured with a slanted-edge profile to quantify overshoot and undershoot.

At matched 1280×720, the source B1 pitch-2 bar ROI has two normalized-luma modes near 0.51 and 1.00. FE84=`7A` shifts the captured modes inward to about 0.54/0.88; FE84=`40` moves them farther inward to about 0.62/0.80. The B2 horizontal-bar distribution stays nearly the same between those FE84 values, consistent with the earlier result that FE84 changes detail varying across X more than detail varying across Y. In C1's one-pixel grid ROI, 96.59% of samples at `7A` and 100% at `40` lie in the normalized mid band, versus an even low/high source distribution: that Nyquist pattern is averaged toward gray rather than resolved as separate black/white pixels.

For 1920×1080 input scaled to 1280×720, the pitch-2 B1/B2 bars lose their source's separate mid/high modes and concentrate around a blended normalized luma near 0.75. The one-pixel C1 grid is entirely in the mid band at the plotted FE85 values. That is evidence of high-frequency averaging in this downscale path; by itself it does not show an unintended alias pattern. The edge profile at FE85=`00` measured +22.31/−13.77 luma codes of bright overshoot/dark undershoot; at `02`, +0.40/−1.28; at `FF`, +0.68/−0.46. The lower ringing at `02` and `FF` trades off against reduced horizontal stripe contrast, so neither is established as universally better.

At matched 720p, edge A measured +23/−16 codes at FE84=`7A` and +2.17/−13.73 at `40`: the bright overshoot falls, while dark undershoot remains. The chart's second edge is labelled light-to-dark but its raster is also dark-to-light, so reverse-polarity edge ringing remains untested. These are captured-output measurements, not a direct HDMI framebuffer comparison. See the [ROI histogram and edge plot](../../artifacts/scaler-f9a0/roi-histogram-20261007/roi-histogram.png), [machine-readable ROI measurements](../../artifacts/scaler-f9a0/roi-histogram-20261007/roi-analysis.json), and offline [analysis script](../../tools/analyze_scaler_roi.py). No device writes were made for this analysis.

Both probes made RAM-only writes, restored FE84=`7A` and FE85=`00`, and verified the monitored registers. EEPROM SHA-256 remained `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`; no firmware was written. Full frame measurements and restoration records are in [the FE85 result](../../artifacts/scaler-f9a0/fe85-scaled-resume-20261007/result.json) (SHA-256 `6fdc27196bccfad76509ef28a34ea9eb82e65a17666387ff64e978dd7619ad92`) and [the matched 720p result](../../artifacts/scaler-f9a0/fe84-matched-720-20261007/result.json) (SHA-256 `b022efcb7b0f6beeb84bb17c8e9ae035106faf7eb3ce22fc1fc0b39eed253cdf`). Reproduction scripts: [FE85](../../tools/probe_fe85_scaled_y.py) and [matched FE84](../../tools/probe_fe84_matched_720.py); both require the chart on the HDMI input and the expected device baseline.
