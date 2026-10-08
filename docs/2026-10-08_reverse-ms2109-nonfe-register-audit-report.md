# MS2109 non-FE XDATA audit and live qualification

> Analysis date: 2026-10-08  
> Analysis type: 8051 firmware review plus bounded live USB checks  
> Toolchain: radare2 6.2.4; Python 3.14; local HID and libusb qualification tools  
> Scope: [project scope](scope.md), attached MS2109, current named EEPROM image

## Summary

The non-FE addresses are not one general-purpose RAM bank. The reviewed code uses several distinct classes: startup and interrupt control bytes, the live UAC mute value, mode/procamp gates, video and timing setup fields, and F5xx command/data streams. The installed EEPROM overlay adds sparse mode commands and status/response blocks. Many F9xx/FAxx/FDxx/FFxx values reach the device through shared XDATA helpers, but their field encodings and electrical meanings remain unresolved.

The live checks passed after reconnect. The current EEPROM is the expected 2 KiB image (`2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`). Video string 2 and audio string 4 both report `MS2109-Pro`. Brightness, contrast, hue and saturation each accepted a one-step UVC SET_CUR, returned the new GET_CUR value, and restored to the starting value. A standard UAC mute request changed `F1F8` from `00` to `01`, then restored it to `00`. EEPROM readbacks remained unchanged.

No raw HID writes were made to the unknown non-FE addresses. The source shows that some are active command or stream ports; restoring their previous byte cannot guarantee reversal of a write side effect. `E0C3=0E` in the baseline is retained as an exploratory read only: valid instruction-boundary decoding found no firmware access at that address.

## Scope and limits

The audit covers non-FE XDATA references in the immutable MS2109 ROM and the currently installed named EEPROM overlay. It includes direct `MOVX` sites and addresses resolved through shared helpers when the caller supplies a literal address. It does not claim to list all possible silicon registers or to decode undocumented electrical behavior. General Cxxx firmware state and descriptor RAM are outside the peripheral-focused inventory unless they directly explain an audited control path.

Live work was limited to identity, duplicate EEPROM reads, USB descriptor/string reads, standard UVC control round-trips and a standard UAC mute round-trip. No EEPROM write or direct HID XDATA write occurred in this audit. Earlier authorized FE84/FE85 chart probes are covered by [scaler and sharpness notes](ms2109-reference/scaler-and-sharpness.md), not repeated here.

## Evidence

### E-001 — Immutable MS2109 mask-ROM image

- observed_at: 2026-10-08
- source_type: file
- source_ref: `backups/ms2109-maskrom.bin`
- content_hash: `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`
- artifact_path: `backups/ms2109-maskrom.bin`
- raw_excerpt: Instruction-aligned disassembly confirms the direct F0xx/F1xx control paths, procamp gate, F5xx setup stream, F8xx mode setup, and generic helper call paths. Raw signature hits at E090, E0C3, E490, F043 and F0A3 were not valid XDATA operands at instruction boundaries.
- repro_command:

~~~sh
r2 -q -a 8051 -b 8 -c 's 0x51e4; pd 32; s 0x5ec0; pd 64; s 0x6d70; pd 64; s 0x78d0; pd 32' backups/ms2109-maskrom.bin
~~~

### E-002 — Current named EEPROM readback

- observed_at: 2026-10-08
- source_type: file
- source_ref: `artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin`
- content_hash: `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`
- artifact_path: `artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin`
- raw_excerpt: The 2048-byte image contains a 1816-byte overlay. Its two EEPROM header name records are both `MS2109-Pro`; the executable overlay body hash is `f0e9d538f411460fab6cfebcd2bd810e474ffb4dca10b08f8498077bee534b92`.
- repro_command: `shasum -a 256 artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin`

### E-003 — Live register and descriptor baseline

- observed_at: 2026-10-08
- source_type: file
- source_ref: `artifacts/ms2109-repair/20261008/nonfe-live-baseline-20261008.json`
- content_hash: `e452c666bc9350d306b60f87e714098be0ff0fc5a440f34d935102c6c6e7a114`
- artifact_path: `artifacts/ms2109-repair/20261008/nonfe-live-baseline-20261008.json`
- raw_excerpt: Chip ID is MS2109; EEPROM size is 2048; two EEPROM reads match the expected installed hash. The saved configuration descriptor includes AudioControl interface 2 and Feature Unit 2, selector 1. Snapshot bytes include `F000=00`, `F1F0=05`, `F1F8=00`, `F803=7F`, `F804=69`, `F80B=C1`, `F83A=03`, `F8E4:E5=80 07`, `F8EC:ED=38 04`, `F9A0=00`, and `F944=00`. `E0C3=0E` is explicitly marked as an exploratory raw-pattern candidate, not a mapped register.
- linked_workitem: none

### E-004 — Live UAC Feature Unit mute round-trip

- observed_at: 2026-10-08
- source_type: live_protocol_test
- source_ref: `artifacts/ms2109-repair/20261008/nonfe-uac-mute-roundtrip-20261008.json`
- content_hash: `d8952aa2d652c8b66224510ae98d32222e634179d100c0ff8e095a729c65dea7`
- artifact_path: same as source_ref
- raw_excerpt: AudioControl interface 2, Feature Unit 2, selector 1: GET_CUR=`00`; standard SET_CUR=`01` returned one byte; GET_CUR and XDATA `F1F8` both became `01`; standard SET_CUR restored `00`; final GET_CUR and `F1F8` were `00`. Two full EEPROM reads still matched the same hash.
- test_limit: Protocol state and readback were verified; this did not test audible mute behavior.

### E-005 — Live UVC picture-control round-trips

- observed_at: 2026-10-08
- source_type: live_protocol_test
- source_ref: `artifacts/ms2109-repair/20261008/nonfe-post-reconnect-picture-controls-20261008.json`
- content_hash: `277fe3521afe42e738dde6fdb9c8a45597610babd7c2cdd70b9c4772017e19b7`
- artifact_path: same as source_ref
- raw_excerpt: Brightness `-18→-17→-18`, contrast `149→150→149`, hue `0→1→0`, saturation `147→148→147`. Every SET_CUR was accepted; each GET_CUR matched the candidate and the restored value. The C6A0 shadow and FE90–FE93 bytes matched their saved baseline after restoration. The pre/post EEPROM hashes both equal E-002.

### E-006 — Live USB name verification after reconnect

- observed_at: 2026-10-08
- source_type: live_protocol_test
- source_ref: `artifacts/ms2109-repair/20261008/nonfe-post-reconnect-usb-names-20261008.json`
- content_hash: `b2094d39fc1b0f998491df25a88e27c4295827e622df1d354df6f28593ab3cdc`
- artifact_path: same as source_ref
- raw_excerpt: The live EEPROM matched E-002 on two reads. Header records `0x10` and `0x20` both decode as `MS2109-Pro`; USB string descriptors 2 and 4 both returned UTF-16LE `MS2109-Pro`.

## Findings

### F-001 — Several raw byte-pattern hits were not register accesses

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-003]
- location: ROM instruction boundaries around E090, E0C3, E490, F043 and F0A3
- impact: Searching raw bytes alone produced false candidates where an operand straddled a preceding instruction or bytes belonged to data. `E0C3` was read once during discovery, but the decoded ROM has no valid access there. The baseline now separates that read from mapped register bytes.
- confidence: high for the reviewed ROM bytes and instruction boundaries
- remediation: use instruction-aligned decode and trace helper arguments before adding an address to the register map.

### F-002 — F000/F1xx contain distinct control and state paths

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-003, E-004]
- location: ROM startup, procamp apply path `51E4`, interrupt/state paths, UAC handler `5ED2–5FEB`
- impact: `F000` is written `07` then `02` at startup and later has bit 1 set or cleared. ROM writes F002/F003 during startup; F005/F006 are zero-written in interrupt clear paths. F0EE/F0EF receive `04/B8` during startup without a decoded read path. `F1F0` gates the procamp apply routine: nonzero returns before the UVC shadow copy to FE90–FE93. `F1F3/F1F4` are written in video/signal paths without decoded field names. `F1F8` backs the live Feature Unit mute value, confirmed by standard SET/GET. `F1F9` is pulsed; `F1FA–F1FC` participate in an interrupt state machine; `F1FF` receives a `04`, bit-1 update, and later `07` sequence. ROM also reads FDBF in an interrupt branch, but the returned byte is not used by the following visible instructions. These hardware sources and side effects remain unknown except for the F1F8 protocol mapping.
- confidence: high for software paths; high for F1F8 request/readback mapping; unknown for silicon details of the other fields

### F-003 — F5xx is a setup command and streaming window

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001]
- location: ROM setup routines using F500–F527
- impact: ROM writes `00 00 00 01` across F500–F503, table values to F504–F506 and F50A–F50C, a longer setup sequence across F50D–F519, and command values `02`, `00`, `01` to F520. F526 is cleared before a loop streams 128 ROM-table bytes through F527. These are not safe candidates for arbitrary RAM-style edits; writing an old byte back may not reverse a command or consumed stream value.
- confidence: high for write sequence and loop; low for the underlying protocol

### F-004 — F8xx and selected F9xx values are mode/configuration fields, not dimensions

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-003]
- location: ROM mode setup and data-copy paths around 3E78, 4F47, 6Axx–6Fxx; installed overlay D1xx–D2xx
- impact: ROM reads and masks F803/F804/F80B, writes mode/rate setup bytes such as F805–F813 and paired parameters at F815/F816, F817 and F840, and copies values from F8E4/F8E5 and F8EC/F8ED into RAM state. F83A/F83B hold state touched by transition/init paths; F83F is computed from RAM mode state. ROM mode/config paths also use F924/F925/F927/F928 and F948/F949 as helper/DPTR setup addresses. F944 bit 2 selects between the F927/F928 and F948/F949 setup sequences. This code does not establish that the F8xx/F9xx fields are input width/height values.
- confidence: high for call/data flow; low or unresolved for peripheral field meanings

### F-005 — F9xx/FAxx/FDxx/FFxx are sparse helper-mediated addresses

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001]
- location: ROM calls to shared XDATA helpers; mode, setup and interrupt paths
- impact: 115 unique literal helper addresses appear across 163 decoded callsites and are listed below. They are sparse addresses, not evidence that every byte in any family is a register or that a single meaning applies across the family. The helper supplies the operation (read, write, bit update or masked read/modify/write); the caller supplies the address and often a mode-dependent value. Except for specific rows elsewhere in this report, no complete silicon encoding is established.
- confidence: high that the listed literal addresses are passed through decoded helper callsites; low for hardware meanings

| Family | Resolved helper-address literals |
|---|---|
| F8xx | `F803 F804 F805 F808 F809 F80A F819 F831 F83C F83D` |
| F9xx | `F921 F922 F923 F926 F929 F92B F92C F92E F933 F936 F944 F947 F94A F960 F962 F963 F966 F969 F980 F983 F986 F987 F9A0 F9A1 F9A2 F9AF F9C0 F9C1 F9C2 F9C3 F9C5 F9CD F9E4 F9E5 F9F5` |
| FAxx | `FA00 FA07 FA08 FA09 FA0A FA10 FA13 FA14 FA80 FA83 FA85 FA8C FA8F FA90 FA9C FAA0 FAA1 FAA2 FAA3 FAA4 FAA5 FAA9 FAAA FAAD FAAE FAB1 FAB2 FAB9 FAC1 FAC2 FAC3 FAC4 FAC5 FAC6 FAC7 FAC9 FACA` |
| FDxx | `FD00 FD01 FD3A FD3F` |
| FFxx | `FF00 FF01 FF08 FF09 FF0A FF11 FF12 FF16 FF17 FF18 FF19 FF1A FF1B FF35 FF47 FF48 FF90 FF91 FFA0 FFA1 FFA3 FFA5 FFA6 FFA7 FFA8 FFAB FFAF FFB0 FFBC` |

The direct/helper-visible F9xx examples with stronger path context include F944 (mode-path test), F92C (installed command-0B value `20`), and F9AF (installed command-0A values `22` then `02`). F9A0 bit 0 remains a scaler-enable candidate without demonstrated bypass effect. These labels are deliberately narrower than a silicon register name.

The resolved generic helpers include `697C` (bit update), `65CD` (masked read/modify/write), `700A` (one-byte read), and `7011` (one-byte write). The F5xx stream additionally uses `5E56` for DPTR-preserving table writes and `5E4F` to write through the current DPTR. Following the helper prevents a false register read/write classification, but does not recover the device's undocumented field definition.

### F-006 — The installed overlay adds E/F-space command and response blocks

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-002]
- location: installed overlay command paths D08B, D0A8, D0CE, D0E7, D1AD, D1B3, D1BA–D1D8, D238 and D27F
- impact: Command 0B writes `F92C=20` and `E33C–E33F=F5 0F 00 00`; command 0F clears `EFD0–EFD3`; one status branch reads `EFE0.6` and writes `EFE8–EFEB=40 00 00 00`; command 0A writes F9AF; mode paths update F805/F806/F807 and sparse F8/F9/FD fields; command setup writes F814=`33` then `32`. These are firmware command/setup roles, not generic tuning values. Exact hardware meanings remain unresolved.
- confidence: high for the installed code path and constants; unknown for underlying silicon protocol

| Overlay path | Non-FE accesses and decoded software role |
|---|---|
| D08B, command 0B | Writes `F92C=20`, writes `E33C–E33F=F5 0F 00 00`, and clears F805 bits 0–1. |
| D0A8 status path | Reads EFE0 and tests bit 6; if set, writes `EFE8–EFEB=40 00 00 00` and updates RAM state C776/C777. |
| D0CE/D0DB, command 0A | Writes F9AF=`22`, then `02` on one path; alternate path writes `22`. |
| D0E7, command 0F | Clears EFD0–EFD3. |
| D1AD/D1B3 mode branch | Writes F92E=`22` and F922=`82`. |
| D1BA–D1D8 mode paths | Writes mode-dependent F806/F807 and FD02/FD03 values. |
| D238 procamp path | Reads F1F0; when the gate allows, copies current UVC shadows to FE90–FE93. |
| D27F command setup | Writes F814=`33` and then `32`. |
| Other C/D overlay setup paths | Write F8E0/F8E1/F8E6/F8E7; F925/F926/F928/F929/F935–F93A/F947/F94A; FD00/FD02/FD03/FD3B/FD3C/FD40/FD41. These are mode/setup values with callsite-specific use; silicon encodings remain unknown. |

### F-007 — Live USB and picture-control checks passed after reconnect

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-002, E-004, E-005, E-006]
- location: live MS2109, UAC interface 2 and UVC Processing Unit controls
- impact: Both name records and both live USB string descriptors are `MS2109-Pro`. The four picture-control SET/GET round-trips restored their original values. The UAC mute state at F1F8 followed standard SET_CUR/GET_CUR and returned to zero. All checked EEPROM hashes matched E-002; no direct raw XDATA write occurred in these checks.
- confidence: high for descriptor/control protocol responses and byte readback; this does not prove audible mute response or visible color change from one-step controls.

## Call path

~~~mermaid
flowchart LR
  boot["ROM startup / mode selection"] --> controls["F000, F1xx control and state"]
  boot --> setup["F5xx command and table stream"]
  boot --> mode["F8xx and sparse F9xx/FAxx/FDxx helpers"]
  uvc["UVC SET_CUR"] --> shadows["C6A0-C6A7 software shadows"]
  shadows --> gate["F1F0 procamp apply gate"]
  gate --> fe["FE90-FE93 hardware values"]
  uac["UAC Feature Unit 2 mute SET/GET"] --> f1f8["F1F8 bit 0"]
  overlay["EEPROM overlay commands"] --> blocks["E33C/EFD0/EFE0/EFE8 and F8/F9/FD setup fields"]
  live["Read-only identity / strings / EEPROM checks"] --> proof["MS2109-Pro; EEPROM hash unchanged"]
~~~

## Timeline summary

- 2026-10-08: instruction-aligned ROM and named-overlay analysis grouped the non-FE XDATA paths and rejected raw-pattern false positives.
- 2026-10-08: after physical unplug/reconnect, live identity, EEPROM, video/audio names, four UVC picture-control round-trips and the UAC mute SET/GET path passed; all temporary control changes were restored.
- No raw XDATA writes to the newly mapped non-FE addresses or EEPROM writes were made during this audit.

## Reproduction and residual questions

Reproduce the live read-only name check with:

~~~sh
python3 tools/qualify_usb_names.py --output artifacts/ms2109-repair/20261008/nonfe-post-reconnect-usb-names-20261008.json
~~~

Reproduce the live reversible picture-control check with:

~~~sh
python3 tools/probe_procamp_setters.py --output artifacts/ms2109-repair/20261008/nonfe-post-reconnect-picture-controls-20261008.json
~~~

Reproduce the instruction-aligned static excerpts with the command under E-001. `artifacts/programmer-reference/candidate-index.md` is a raw discovery index and must not be treated as a confirmed register map. The device's vendor field names, reset behavior, clear-on-read/write-one-to-clear semantics, latch timing and side effects are still unknown for most F0xx/F1xx/F5xx/F8xx/F9xx/FAxx/FDxx/FFxx values. A live snapshot establishes current bytes only. Future probes need a specific call path and a recovery strategy suited to the operation; for command and stream ports, restoring the previous byte is not sufficient evidence of reversal.
