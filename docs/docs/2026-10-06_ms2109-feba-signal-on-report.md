# MS2109 FEBA test with active HDMI

6 October 2026. User-authorized temporary RAM test on the attached MS2109. HDMI was connected and a live desktop was visible. Capture path: AVFoundation-delivered 1920×1080 YUY2.

## Procedure and result

Two baseline → FEBA=08 → restored sequences were captured. Each began with FEBA=00 and F92C=20. The script checked the EEPROM SHA-256 before any write and refused to run if it did not match the expected installed image. It wrote only XDATA FEBA, read FEBA=08 after the active-signal capture in the repeat run, restored FEBA=00, and checked the full EEPROM again.

**FEBA=08 did not put the color bars over active HDMI.** The baseline and FEBA=08 captures were pixel-identical throughout the central page area in both runs (mean absolute RGB difference 0.0). FEBA remained 08 after the capture, so the firmware did not immediately clear the test value. The unchanged image therefore reflects output-path selection while a valid HDMI source is present, not a failed or transient register write.

After restoration, FEBA read back as 00. The EEPROM SHA-256 matched before and after: `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. Normal HDMI video remained visible. No EEPROM write occurred.

| Trial | Baseline frame SHA-256 | FEBA=08 frame SHA-256 | Restored frame SHA-256 | FEBA after capture |
|---|---|---|---|---:|
| 01 | `f4423d691505eedef0a0a09788fcc3a53080a41dea70e4a45b9dc3baba8a1121` | `41e73c403bac2f1f53c00f514772e72a9eb2c9228e0098f16b273fa285e51f03` | `9f0526c6d773e8e5e2e85fdf1cc1dc1de6131e44832ed8931d68a605f93ebda7` | not sampled after capture |
| 02 | `60e9b2a14b3b4e8a51f063445f0978445674f2d1d6ddb42e7a40b2b136f8570c` | `603587ad152a1a4d7fc6ed54fd8ff8fc867157ada2bb8ebc800b5a29aadce300` | `5b388311f1217229567ad90076bcbab7666ee34459633db5f1a1137fad89cafd` | `08` |

The full-frame hashes differ because desktop elements such as the clock changed between captures. The page-area image comparison is the direct visual result. PNGs, Matroska captures, logs and JSON are under `artifacts/no-signal-feba/live-signal-01/` and `live-signal-02/`.

## Interpretation

FEBA is confirmed as a selector for the **no-signal fallback pattern**. With no HDMI input, FEBA=08 yields color bars and FEBA=00 yields black. With valid HDMI present, the same stable FEBA=08 write leaves the HDMI picture unchanged. This is consistent with an automatic path/mux choice that uses the internal pattern only when the HDMI receiver has no valid picture; the exact mux circuit or control is not identified.

A UVC control for FEBA could select which built-in fallback appears after signal loss. It would not, by itself, force bars over live video. Forcing a pattern over valid HDMI would require a separate source-override control or firmware path, neither identified in this pass. The current ROM's `FEBA` startup mask should therefore be read as a default pattern-field clear, not as the signal-present gate itself.

## Reproduction

`tools/probe_feba_signal_on.py` captures baseline, FEBA=08 and restored states. It checks the installed EEPROM identity and known register baseline before writing, verifies FEBA after the test capture, restores the original value in `finally`, and verifies EEPROM unchanged.
