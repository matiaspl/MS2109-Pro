# MS2109-Pro product-name candidate

The ROM-backed USB device descriptor at XDATA `C688` uses product-string index 2. XDATA `C636` is the response buffer, but the ROM rebuilds that buffer when serving the string request. The candidate's startup-only write to `C636` did not change the product string after a cold boot.

The candidate preserves calibrated color defaults, stereo routing, factory EDID, HID transport, and other existing firmware behavior. It does not include the planned standard UVC Sharpness control. Its offline 8051 harness confirms the generated helper inputs and intended bytes, but that model did not establish that the ROM copy helper works for this use on hardware.

After installation and a physical USB power cycle, live RAM showed the candidate header and 1,993-byte code length. The calibrated procamp values and both patched color records were present, proving the startup callback ran. However, XDATA `C636` and a fresh raw EP0 `GET_DESCRIPTOR` still returned “usb video”. A reversible write to XDATA `CBE1–CBE9` also left the response unchanged; the original 16-byte window was restored byte-for-byte. Two full EEPROM reads matched the candidate SHA-256. The candidate is installed but the requested name change is **not** qualified. See the [post-power-cycle RAM check](../artifacts/ms2109-pro-name/20261007/post-power-cycle-ram-check.json) and [updated descriptor analysis](ms2109-reference/usb-descriptors.html).

| Item | Value |
|---|---|
| Candidate | `artifacts/ms2109-pro-name/20261007/ms2109-pro-calibrated-stereo.bin` |
| Candidate SHA-256 | `543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961` |
| Declared code | 1,993 bytes of 1,996 maximum |
| Rollback | `artifacts/ms2109-pro-name/20261007/rollback-current-calibrated-stereo.bin` |
| Rollback SHA-256 | `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82` |
| Offline verification | Candidate checksum validation and generated startup-hook execution passed; full repository suite: 72 tests passed |
| Live qualification | Candidate boot and calibrated startup state verified; product descriptor check failed and remains “usb video” |

The candidate was built from the pinned original EEPROM with the calibrated/stereo profile. It was installed after user authorization; full EEPROM readback matched the candidate. The [rollback image](../artifacts/ms2109-pro-name/20261007/rollback-current-calibrated-stereo.bin) remains available. A corrected candidate needs to intercept or patch the ROM's descriptor-generation path; another startup write to `C636` is not sufficient. See the [hash manifest](../artifacts/ms2109-pro-name/20261007/sha256-manifest.json) and build metadata.

## Corrected stage-2 candidate

The ROM calls its descriptor builder immediately after the stage-1 callback, so a stage-1 write to `C636` is overwritten before the first USB request. The corrected image moves the descriptor repair to the stage-2 polling callback, after the ROM builder has run. It leaves the other startup changes and factory EDID path intact.

The corrected 2,048-byte candidate is [ms2109-pro-calibrated-stereo-stage2.bin](../artifacts/ms2109-pro-name/20261007/ms2109-pro-calibrated-stereo-stage2.bin), SHA-256 `b0b25243c155086bb0b96d41a5927104a3f04a8a1f5a3ae3930568943f5690d7`. It declares 1,993 of 1,996 permitted code bytes (3 bytes spare). Offline tests pass, and a volatile RAM qualification verified the UTF-16LE response through raw EP0 both before and after `libusb_reset_device`; the candidate overlay survived that USB reset. The calibrated procamp and color records remained present. The qualification restored all snapshotted RAM and confirmed two EEPROM reads still matched the previously installed image, SHA-256 `543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961`. See the [stage-2 RAM qualification record](../artifacts/ms2109-pro-name/20261007/stage2-ram-qualification-usb-reset-02.json).

The corrected image is now installed. The guarded writer verified the pre-install EEPROM against `installed-readback.bin`, wrote 104 changed bytes, and verified a complete readback against the candidate SHA-256. The exact pre-install EEPROM image remains available as [installed-readback.bin](../artifacts/ms2109-pro-name/20261007/installed-readback.bin), SHA-256 `543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961`; the older calibrated baseline rollback is also retained. After the physical USB power cycle, EEPROM readback still matched the candidate and raw EP0 returned `MS2109-Pro`. The corrected candidate is cold-boot qualified. See the [installation record](../artifacts/ms2109-pro-name/20261007/stage2-installation.json), [cold-boot qualification](../artifacts/ms2109-pro-name/20261007/stage2-cold-boot-qualification.json), and [full EEPROM readback](../artifacts/ms2109-pro-name/20261007/stage2-installed-readback.bin).

## Scope and evidence

Scope: the user's connected MS2109 capture dongle, its installed 2 KiB EEPROM image, and the pinned mask ROM. The user authorized the candidate installation and then confirmed the physical USB power cycle. This workspace has no separate case `scope.md` or `timeline.md`; the scope and event sequence are recorded here.

| ID | Evidence | Reproduction | Result |
|---|---|---|---|
| E-001 | [Installed qualification record](../artifacts/ms2109-pro-name/20261007/installed-qualification.json) and [post-power-cycle RAM check](../artifacts/ms2109-pro-name/20261007/post-power-cycle-ram-check.json) | `python3 tools/ms2109_hid.py inspect` plus the recorded read-only HID/EP0 checks | After physical power-cycle, live header length is 1,993; EEPROM SHA-256 matches candidate; USB string remains `usb video`. |
| E-002 | ROM bytes and disassembly at `0x2340–0x236D`; mask-ROM table at `CBE0` | `r2 -q -a 8051 -b 8 -c 's 0x2340; pd 45; q' backups/ms2109-maskrom.bin` | ROM reconstructs product-string bytes into `C636`; the ROM table contains `usb video`. |
| E-003 | Reversible XDATA probe in the [post-power-cycle RAM check](../artifacts/ms2109-pro-name/20261007/post-power-cycle-ram-check.json) | Recorded RAM-only change to `CBE1–CBE9`, raw EP0 query, byte-for-byte restore, and EEPROM hash check | EP0 remained `usb video`; the 16-byte XDATA window was restored and EEPROM stayed unchanged. |

### Finding

**F-001 — Startup-only response-buffer patch does not rename the device.** Severity: `n/a_re`; confidence: high for the observed failure. Evidence: E-001 and E-003. Location: startup hook in the candidate and ROM product-string path at `0x2340–0x236D`. Status: validated failure. The candidate is loaded and its calibrated startup state is present, but a cold boot still enumerates with “usb video”. The exact ROM source-buffer refresh order remains unresolved.

### Call path

**P-001 — Product-string response generation.** Type: `callflow`.

1. EEPROM image boots; live header reports 1,993 code bytes — E-001.
2. Startup callback applies calibrated procamp and color-record changes — E-001.
3. ROM builds the string response in `C636`; current EP0 result is “usb video” — E-001 and E-002.
4. A reversible write to the live `CBE0` XDATA window does not change EP0 output; the original bytes are restored — E-003.

Timeline: candidate installed after user authorization; user physically power-cycled USB; readback confirmed candidate boot; product-name verification failed; volatile probe restored successfully. No EEPROM write occurred during the RAM qualification.
