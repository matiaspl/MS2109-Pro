# MS2109 FEBA no-signal pattern sweep

6 October 2026. Reversible RAM-only sweep on the attached MS2109, with HDMI physically disconnected and USB connected. Captures used AVFoundation-delivered 1920×1080 YUY2.

## Result

FEBA bits 4:0 select internal no-signal video patterns on this device. In particular, **FEBA=08 produces SMPTE-like vertical color bars**, while the installed EEPROM's FEBA=00 state produces black. This confirms that EEPROM startup code can determine whether the bars appear: the installed image does not write FEBA=08, while the upstream reconstruction does.

The experiment wrote each value from 00 through 1F to XDATA FEBA, captured frames, and verified readback before and after each capture. The original FEBA value was 00 and was restored. After HDMI reconnection, a read-only check confirmed FEBA=00, F92C=20, the same EEPROM SHA-256, and a nonuniform source frame. EEPROM SHA-256 matched before and after: `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. No EEPROM writes occurred.

## Observed values

Descriptions identify the captured appearance only; these values do not establish a vendor-defined name or guarantee behavior on other chip revisions and formats.

| FEBA | Captured appearance |
|---:|---|
| 00 | Black |
| 01 | Solid blue |
| 02 | Solid green |
| 03 | Solid red |
| 04 | Solid white |
| 05 | Fine grid |
| 06 | Horizontal grayscale ramp, black at left to white at right |
| 07 | Vertical grayscale ramp, black at top to white at bottom |
| 08 | Six vertical color bars on black (white, yellow, cyan, green, magenta, red, blue); the bar field fills most of the frame height |
| 09 | Vertical stepped grayscale bars |
| 0A | Horizontal stepped grayscale bars |
| 0B | Two stacked grayscale ramps in opposite directions |
| 0C | Four-band ramp: grayscale, red, green and blue |
| 0D | Mid-gray field, approximately RGB 128/128/128 |
| 0E | Dark olive field, approximately RGB 55/63/10 |
| 0F | Olive field, approximately RGB 117/135/32 |
| 10 | Blue-tinted field, approximately RGB 15/0/245 |
| 11–1F | Black in these captures |

All 32 values are shown in [the capture contact sheet](../artifacts/no-signal-feba/trial-03/contact-sheet.png). The raw per-value PNG and Matroska captures, logs, readbacks and EEPROM hashes are under `artifacts/no-signal-feba/trial-03/`; the focused values 00–10 and selected combinations are also retained in trials 01 and 02.

## Interpretation and limits

ROM code calls a masked-write helper with mask `1F` for FEBA, clearing the low five bits during startup. The installed calibrated EEPROM later leaves FEBA at 00; the separate upstream assembly writes 08 from command 01 and command 0B, with a source comment calling it color-bar enable. The live capture verifies the effect of FEBA on this board and path. It does not prove the precise internal register name, the behavior of FEBA's upper bits, or identical output on raw USB/MJPEG capture.

F92C=20 remained at the installed value throughout this sweep. The prior F92C=20/30 comparison at FEBA=00 produced black in both cases. Together, these results identify FEBA bit 3 as sufficient to select bars in the tested no-signal state; no F92C change was needed. The experiment did not test synthetic audio or persistent EEPROM changes.

## Reproduction

The live probe is `tools/probe_no_signal_feba.py`. It refuses unexpected initial FEBA values, captures each selected value, checks readback, restores the original byte in `finally`, and verifies the EEPROM hash. The completed full-range run used values 00–1F.
