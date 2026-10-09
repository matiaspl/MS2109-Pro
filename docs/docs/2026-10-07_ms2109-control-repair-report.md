# MS2109 video controls and register console

**Date:** 7 October 2026  
**Target:** attached MS2109, USB ID `534d:2109`  
**Status:** partial implementation; the Sharpness-removal candidate is in EEPROM and fully read back, but live cold-boot qualification is pending after the USB reset left a mismatched runtime image

**Superseding update (8 October 2026):** the user unplugged and reconnected the device. The 1,816-byte profile then passed read-only firmware checks, the four picture-control SET/GET round-trips and restoration, and two YUY2 stream starts. A later EEPROM update changed only the two name records and header checksum; its exact readback and pending post-update cold-boot name check are in the [USB name report](2026-10-08_ms2109-usb-name-header-report.html).

## Scope

The user authorized reversible live XDATA tests on the attached MS2109. Persistent firmware installation was excluded. The two-read EEPROM baseline is [current-eeprom-readback.bin](../artifacts/ms2109-repair/20261007/current-eeprom-readback.bin), SHA-256 `b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8`.

## Findings

### F-001 — Native 1080p overflows; 720p fits

**Status:** measured; mode-specific correction unresolved. Evidence: E-002–E-004.

With a corner-marked 1920×1080 chart and a 1920×1080 YUY2 capture, the left markers measured 17×12 px cells for 12×12 px source cells. The fitted horizontal scale is 1.4167 and vertical scale is 1.0. The inferred right edge is x=2723.647, or about 805 px beyond the 1920-pixel capture. The right corner markers are clipped.

At 1280×720 input and capture, all four markers were found in all eight frames. Their geometry fits at 1.0× scale, with less than one pixel of predicted edge overflow. This confirms that the overflow is mode-specific in the tested path.

The live register values in both modes included FE84=`7F` and FE85=`00`. A RAM-only FE84=`40` write read back as `7F`, so the probe stopped before taking a candidate frame. It verified the original value and EEPROM hash afterward. No FE84/FE85 fix is qualified, and the measurements do not identify those bytes as input dimensions or a comb-filter setting.

### F-002 — Brightness, contrast, hue, and saturation setters work

**Status:** live SET/GET round-trip and restoration passed. Evidence: E-001.

UVC SET_CUR changed each current value by one step, GET_CUR returned the new value, and a second SET_CUR restored the original value. The live settings were brightness −18, contrast 149, hue 0, and saturation 147 before the probe. UVC shadows and the EEPROM matched their original values after restoration. This verifies control writes and readback; it does not measure the visible image change.

### F-003 — UAC name change is incomplete

**Status:** candidate works on the type-7 overlay path; active type-2 path remains unchanged. Evidence: E-005 and E-006.

The device product string at USB string index 2 is already `MS2109-Pro`. Audio interfaces use string index 4, which still returns `usb video`. A reversible edit to the suspected CBF0 source did not change the raw EP0 string and was restored.

The offline candidate rewrites the three audio interface string indexes to 2 and suppresses the Sharpness bit in its guarded configuration-copy path. The [reviewed candidate metadata](../artifacts/ms2109-repair/20261007/ms2109-uac-index-candidate-reviewed.json) records the live limitation. The RAM probe showed this on configuration type 7. Active type 2 still returned interface indexes `[4, 4, 4]` and Processing Unit bitmap `1F00` through the ROM path. The candidate is therefore not a complete UAC rename, and the attached device still reports `usb video` for audio.

### F-004 — UVC Sharpness is removed from the control-repair candidate

**Status:** offline implementation rebuilt; attached device remains unchanged. Evidence: E-005 and the [Sharpness-removal follow-up](2026-10-08_ms2109-sharpness-removal.html).

The rebuilt candidate delegates brightness, contrast, hue, and saturation to the stock ROM; rejects UVC selector 8; clears bit 4 in standard and other-speed configuration response copies; and keeps no Sharpness value or FE84/FE85 writes. Its compact overlay is 1,816 bytes. The EEPROM was updated after the user authorized persistent writes, and a full readback matches the candidate. A USB reset returned, but live RAM still reports the old 1,904-byte image and UVC GET requests timed out. Cold-boot behavior remains unqualified. No visible Sharpness mapping was established.

### E-008 — Sharpness-removal candidate and refused RAM qualification

| E-008 | [Sharpness-removal qualification record](../artifacts/ms2109-repair/20261007/sharpness-removal-ram-qualification.json) and [candidate image](../artifacts/ms2109-repair/20261007/ms2109-control-repair-candidate.bin) | Candidate SHA-256 `bee6059bc398bda76348e4dfe7d3df76fbedd32ac8d5a0d79af97ab3ed382bab`; RAM probe refused before writing; two postflight EEPROM reads match baseline | `python3 tools/qualify_sharpness_ram.py --output artifacts/ms2109-repair/20261007/sharpness-removal-ram-qualification.json` |
| E-009 | [EEPROM installation record](../artifacts/ms2109-repair/20261008/eeprom-installation.json), [pre-install backup](../artifacts/ms2109-repair/20261008/preinstall-eeprom-backup.bin), and [post-reset qualification](../artifacts/ms2109-repair/20261008/postinstall-basic-qualification.json) | 680 bytes written with per-byte and full-image verification; EEPROM SHA-256 matches candidate; USB reset did not confirm fresh overlay load | `python3 tools/flash_eeprom.py --expected-current artifacts/ms2109-repair/20261008/preinstall-eeprom-backup.bin --image artifacts/ms2109-repair/20261007/ms2109-control-repair-candidate.bin --apply --readback artifacts/ms2109-repair/20261008/installed-readback.bin` |

### F-005 — Live register console added

**Status:** implemented and covered by offline tests. Evidence: E-007.

Run `python3 tools/ms2109_register_console.py` from the repository. It reads XDATA bytes or little-endian words, displays hexadecimal and decimal values, toggles a selected bit, and accepts hex or `d:` decimal edits. Press `p` to browse the curated [register-purpose map](ms2109-reference/registers.html); the selector shows each entry's description and evidence limits, and selecting one jumps to its address and preferred width. Unmapped addresses remain explicitly unmapped. Before the first write, the console records the original byte in a recovery journal. `u` restores the selected bytes, `R` restores the session, and `q` restores then exits. Use `--recover JOURNAL.json` after an interrupted session. The tool reads and hashes EEPROM twice; it only writes XDATA RAM.

The console reports a failed readback if the device or firmware immediately replaces a register value. The FE84=`40` probe encountered this behavior and restored its snapshot.

## Evidence

| ID | Evidence | SHA-256 / result | Reproduction |
|---|---|---|---|
| E-001 | [Live procamp SET/GET and restore](../artifacts/ms2109-repair/20261007/procamp-set-cur-qualification.json) | `55fedd0001e5b914b04ee2216b47a35c5ddaa0972e9f9809437c26690d396c29`; four controls changed and restored; EEPROM unchanged | `python3 tools/probe_procamp_setters.py --output artifacts/ms2109-repair/20261007/procamp-set-cur-qualification.json` |
| E-002 | [Native 1920×1080 corner geometry](../artifacts/ms2109-repair/20261007/geometry-native-1920x1080-corrected/result.json) and 8-frame raw YUY2 capture | JSON SHA-256 `d3bc534d7cb1cbf95066f5d216f757ce76e2587790829efacc2882d042c95764`; raw capture SHA-256 `167e016a9f53ca989ed529bee2dd40f3b5cefbd2fb240a5ec0073a1083bba0f6` | `python3 tools/capture_corner_geometry.py --chart-session artifacts/ms2109-repair/20261007/corner-native-session --manifest artifacts/ms2109-repair/20261007/geometry-charts/manifest.json --chart-size 1920x1080 --capture-width 1920 --capture-height 1080 --frames 8 --output artifacts/ms2109-repair/20261007/geometry-native-1920x1080-corrected` |
| E-003 | [Scaled 1280×720 corner capture](../artifacts/ms2109-repair/20261007/geometry-scaled-1280x720-rerun/result.json) and [per-frame geometry](../artifacts/ms2109-repair/20261007/geometry-scaled-1280x720-rerun/frame-geometry.json) | Raw YUY2 SHA-256 `48b42d61c6b3537c339a1465b477657357de3fd368bebb90e275529e03f5275a`; all four markers found in each frame; all fits within viewport | `python3 tools/capture_corner_geometry.py --chart-session artifacts/ms2109-repair/20261007/corner-scaled-session-elevated --manifest artifacts/ms2109-repair/20261007/geometry-charts/manifest.json --chart-size 1280x720 --capture-width 1280 --capture-height 720 --frames 8 --output artifacts/ms2109-repair/20261007/geometry-scaled-1280x720-rerun` |
| E-004 | [FE84=`40` RAM probe record](../artifacts/ms2109-repair/20261007/geometry-fe84-40-native-1920b/result.json) | SHA-256 `32e928df11a628ba982ee813ed499a6fee41460d3b6309cbb2b4e896b26cf09f`; attempted value read back as `7F`; restoration verified; EEPROM unchanged | `python3 tools/probe_corner_geometry_fe84.py --chart-session artifacts/ms2109-repair/20261007/corner-native-session-final2 --manifest artifacts/ms2109-repair/20261007/geometry-charts/manifest.json --output artifacts/ms2109-repair/20261007/geometry-fe84-40-native-1920b` |
| E-005 | [UAC descriptor RAM qualification](../artifacts/ms2109-repair/20261007/uac-descriptor-ram-qualification.json) | SHA-256 `0fd73dbfb22819550621a7922d9d044633846f0bce7a481bef74659ab6d6f2d7`; type 7 changed, type 2 remained on ROM | `python3 tools/probe_uac_descriptor_patch_ram.py --output artifacts/ms2109-repair/20261007/uac-descriptor-ram-qualification.json` |
| E-006 | [UAC string-source RAM qualification](../artifacts/ms2109-repair/20261007/uac-string-source-ram-qualification.json) and [read-only EP0 strings](../artifacts/ms2109-repair/20261007/uac-string-source-readonly.json) | CBF0 edit did not change string 4; buffer restored; EEPROM unchanged | `python3 tools/probe_uac_string_source_ram.py --output artifacts/ms2109-repair/20261007/uac-string-source-ram-qualification.json` |
| E-007 | Offline firmware and register-console tests; implementations in [sharpness_firmware.py](../tools/sharpness_firmware.py), [ms2109_register_console.py](../tools/ms2109_register_console.py), and [patch_uac_interface_name.py](../tools/patch_uac_interface_name.py) | 61 tests passed in 48.785 s | `python3 -m unittest tests.test_sharpness_firmware tests.test_compact_sharpness tests.test_sharpness_rom_edid tests.test_sharpness_space tests.test_register_console tests.test_corner_geometry tests.test_procamp_setters tests.test_uac_interface_name -v` |

## Path and timeline

**P-001 — Geometry check:** present each corner chart on `HDMI TO USB`; capture matching YUY2 dimensions; locate all four markers; fit horizontal and vertical scale and offsets; compare native and scaled modes. A single FE84 candidate was attempted only after the baseline capture and stopped when readback failed. RAM and EEPROM readbacks verified recovery.

**P-002 — Picture-control path:** issue UVC SET_CUR for selectors 2, 3, 6, and 7; confirm with GET_CUR; restore the original values and saved RAM shadows. Offline firmware tests confirm these selectors delegate to ROM. The rebuilt candidate stalls selector 8 and does not touch FE84/FE85.

**P-003 — UAC descriptor path:** stage the candidate in volatile RAM; query raw EP0 descriptors for types 2 and 7; restore all staged ranges. The type-7 result changed; type 2 did not. A separate CBF0 source edit also did not change EP0 string 4 and was restored.

**Timeline:** 2026-10-07: captured native and scaled corner charts, tested the four picture setters, attempted one reversible FE84 value, and qualified the type-7 descriptor path. The HDMI output was returned to 1920×1080. No EEPROM write occurred.

## Reproduction limits

The corner measurements cover the attached device, this HDMI source, the tested firmware state, and two matching input/capture modes. The native overflow is measured, but no safe scaler setting was verified. The scaled capture's raw frames differed slightly; geometry was measured independently in every frame and remained within the viewport. The active type-2 USB descriptor path still needs a patch point that survives ROM handling. The register console is RAM-only and does not make unsupported register semantics safe or known.
