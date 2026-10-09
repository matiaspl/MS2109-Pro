# MS2109 XDATA FE-range firmware audit

> Analysis date: 2026-10-08  
> Analysis type: Offline 8051 firmware review  
> Tools: radare2 6.2.2, Python 3.14.7  
> Scope: [project scope](scope.html), using saved ROM and EEPROM images only

## Summary

I decoded every explicit XDATA address in FE00–FEFF used by the pinned ROM and both the original and currently named EEPROM overlays. The accesses resolve into four groups: an FE20 command/status handshake, audio routing and rate setup, video-mode initialization, and procamp values/shadows. The ROM writes FE84 as a single mode byte and read-modify-writes FE85 only to clear bit 1; it does not use them as a numeric input-width/height pair or map them to sharpness. Prior live pattern measurements show they affect horizontal image response, but their exact scale arithmetic is still unknown. The installed overlay adds FE60=01 for its stereo audio setup and applies its chosen procamp values.

## Scope and limits

The current project scope requested saved-image ROM/EEPROM and local-source analysis without live access or writes. This audit follows that boundary. It does not claim that the explicit firmware inventory is the full peripheral map, and it does not assign hardware names where the code only exposes a command, status, or mode flag.

## Evidence

### E-001 — Immutable ROM instruction paths

- observed_at: 2026-10-08
- source_type: file
- source_ref: backups/ms2109-maskrom.bin
- content_hash: b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8
- artifact_path: backups/ms2109-maskrom.bin
- repro_command:

~~~sh
r2 -q -a 8051 -b 8 -c 's 0x3e78; pd 70; s 0x4d54; pd 70; s 0x51f5; pd 60' backups/ms2109-maskrom.bin
r2 -q -a 8051 -b 8 -c 's 0x6a74; pd 24; s 0x6b3d; pd 12; s 0x6cbd; pd 62; s 0x6e76; pd 20; s 0x6eed; pd 12; s 0x6f3f; pd 48' backups/ms2109-maskrom.bin
~~~

- raw_excerpt: The ROM's FE immediate helper-address constructions are at 3E92, 3EA4, 3EC3, 3ED0, 3EE7, 3EF0, 3EF9, 3EFF, 6A7C, 6A87, 6CC8, 6CD8, 6CE8, 6CF8, 6E7E, 6EF3, and 6FA7. Direct MOV DPTR operands are FE20, FE22, FE28, and FE90–FE93.
- linked_workitem: n/a
- supersedes: none

### E-002 — Current named EEPROM overlay

- observed_at: 2026-10-08
- source_type: file
- source_ref: artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin
- content_hash: 2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5
- artifact_path: artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin
- repro_command:

~~~sh
dd if=artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin of=/tmp/ms2109-named-overlay.bin bs=1 skip=48 count=1816 status=none
r2 -q -a 8051 -b 8 -m 0xcc00 -c 's 0xd082; pd 18; s 0xd238; pd 51; s 0xd2bc; pd 47' /tmp/ms2109-named-overlay.bin
~~~

- raw_excerpt: The overlay's direct FE addresses are FE20 at D082, FE90/91/93/92 at D248/D250/D258/D260, FE90 again at D2DB with sequential stores through FE93, and FE60 at D304. Its executable body is 1816 bytes; body SHA-256 is f0e9d538f411460fab6cfebcd2bd810e474ffb4dca10b08f8498077bee534b92.
- linked_workitem: n/a
- supersedes: none

### E-003 — Original EEPROM overlay comparison

- observed_at: 2026-10-08
- source_type: file
- source_ref: backups/ms2109-original.bin
- content_hash: 37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1
- artifact_path: backups/ms2109-original.bin
- repro_command:

~~~sh
python3 - <<'PY'
from pathlib import Path
image = Path("backups/ms2109-original.bin").read_bytes()
length = int.from_bytes(image[2:4], "big")
Path("/tmp/ms2109-original-overlay.bin").write_bytes(image[0x30:0x30 + length])
print("code length:", length)
PY
r2 -q -a 8051 -b 8 -m 0xcc00 -c 's 0xd082; pd 12; s 0xd238; pd 45' /tmp/ms2109-original-overlay.bin
~~~

- raw_excerpt: The 1716-byte original overlay writes FE20=2A and has the same FE90–FE93 apply callback. It does not contain the installed image's FE60=01 write or its additional command-01 shadow and procamp initialization block.
- linked_workitem: n/a
- supersedes: none

### E-004 — Prior live FE84/FE85 response measurements

- observed_at: 2026-10-07
- source_type: file
- source_ref: docs/ms2109-reference/scaler-and-sharpness.md
- content_hash: d8e7beea59c6b35aa19eb61d8fb96ebaccc520bae92d737b0bc58cead00b3fba
- artifact_path: docs/ms2109-reference/scaler-and-sharpness.md
- repro_command: n/a — this saved report summarizes earlier authorized RAM-only probes; this offline audit did not repeat them.
- raw_excerpt: The documented matched 1280x720 captures at FE84=7A and FE84=40 changed horizontal stripe response while flat fields stayed stable. The same reference documents FE85-dependent horizontal phase changes in native mode. These results support a horizontal response role, not an exact register decode.
- linked_workitem: n/a
- supersedes: none

### E-005 — Prior live FEBA pattern sweep

- observed_at: 2026-10-06
- source_type: file
- source_ref: docs/2026-10-06_ms2109-feba-pattern-sweep-report.md
- content_hash: 29e30767a4e44881c9c3ed34ef2cb091e74f0017ac17293ff6e568493dcb6537
- artifact_path: docs/2026-10-06_ms2109-feba-pattern-sweep-report.md
- repro_command: n/a — the saved report records a completed RAM-only sweep; it was not repeated for this offline audit.
- raw_excerpt: FEBA low-five-bit values 00–1F were swept on the board with HDMI disconnected. FEBA=00 produced black and FEBA=08 produced SMPTE-like bars; the EEPROM remained unchanged.
- linked_workitem: n/a
- supersedes: none

### E-006 — Prior live FE60 channel routing qualification

- observed_at: 2026-10-06
- source_type: file
- source_ref: docs/2026-10-06_ms2109-producer-phase-control-report.md
- content_hash: 8f946c4b8373ca5c10cf05a923ca997704e1c8e8300c17bdd58ce3a80d8f139e
- artifact_path: docs/2026-10-06_ms2109-producer-phase-control-report.md
- repro_command: n/a — the saved report records earlier channel-order captures; this audit did not capture from the device.
- raw_excerpt: FE60=01 routed the continuous left source to USB channel 0 and the gapped right source to channel 1; the one-sample lag remained.
- linked_workitem: n/a
- supersedes: none

## Findings

### F-001 — FE20/FE22/FE28 form a command/status handshake

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-002]
- location: ROM 23EB and 6B3D–6B51; installed overlay D082
- impact: Firmware writes FE20=2B, reads FE22, then writes FE28=00 for a zero result or 01 for a nonzero result. The installed command-01 handler writes FE20=2A and enters its setup helper. This is not enough to name the underlying peripheral function.
- confidence: high for the instruction flow; low for the silicon function
- repro_steps:
  1. Decode the ROM around 23EB and 6B3D.
  2. Decode the installed overlay around D082 and compare its literal to ROM's 2B.
- remediation: n/a
- optional_attack:

### F-002 — FE60 and FE61–FE67 are separate audio controls

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-002, E-006]
- location: installed overlay D304; ROM 3E78–3F01
- impact: The installed command-02 path declares stereo/48 kHz and writes FE60=01. ROM separately writes input and output rate values to FE62–FE67 and changes FE61 bits according to rate equality. FE60's observed routing result does not establish a complete bitfield or correct sample alignment.
- confidence: high for software operations; medium for FE60's observed routing role
- repro_steps:
  1. Decode the installed overlay at D2F1–D30A.
  2. Decode the ROM at 3E78–3F01 and follow helper 65CD.
- remediation: n/a
- optional_attack:

### F-003 — The other video-mode FE writes are bit/configuration paths, not dimensions

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-004, E-005]
- location: ROM 3F66–3F84, 6A74–6A89, 6CBD–6CFA, 6E76–6E80, 6EED–6EF5, 6F3F–6FA9
- impact: FE80.0 copies IRAM 20.0; FE85.1 is cleared. FE8E/FE8F bits 0 and 4 are updated from the inverse of 20.0. FEB9.0 copies 20.4. FEBA bits 4:0 copy the current R7/IRAM 07 byte, preserving bits 7:5. FE84 receives the mode caller's 7A value. None of these code paths reads a multi-byte input width or height from FE84/FE85.
- confidence: high for source bytes, masks and call flow; medium for assigning FE84/FE85 a horizontal resampling role, supported by prior live captures and still not a silicon decode
- repro_steps:
  1. Decode each listed ROM path.
  2. Follow calls to 697C, 65CD, and 7011 to distinguish masked updates from full-byte writes.
- remediation: n/a
- optional_attack:

### F-004 — FE90–FE93 bridge ROM defaults, UVC shadows and overlay settings

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: [E-001, E-002, E-003]
- location: ROM 4D54–4DA8 and 51F5–5225; installed overlay D248–D263 and D2BC–D2EB
- impact: ROM initializes FE90–FE93 with F5, 94, B4, 00, then reads those bytes into C6A0–C6A7 shadows. Installed command 01 seeds its selected shadows and writes FE90–FE93 as EE, 95, 93, 00. The UVC shadow order is brightness, contrast, hue, saturation, while the hardware order is brightness, contrast, saturation, hue.
- confidence: high
- repro_steps:
  1. Decode ROM 4D54–4DA8 and 51F5–5225.
  2. Decode overlay D248–D263 and D2BC–D2EB.
- remediation: n/a
- optional_attack:

## Call path

~~~mermaid
flowchart LR
  init["ROM caller at 23EB"] --> handshake["FE20 command → FE22 status → FE28 response"]
  init --> rates["Rate setup: FE61–FE67"]
  init --> video["Video mode: FE80, FE84–FE85, FE8E–FE8F, FEB9, FEBA"]
  init --> procamp["ROM defaults and reads: FE90–FE93 ↔ C6A0–C6A7"]
  overlay["EEPROM command 01"] --> latch["FE20=2A; setup helper"]
  overlay --> selected["Selected procamp shadows → FE90–FE93"]
  overlay2["EEPROM command 02"] --> stereo["Audio descriptor 2ch/48 kHz; FE60=01"]
~~~

## Timeline summary

- 2026-10-06: project scope was extended to map saved ROM/EEPROM register behavior offline.
- 2026-10-08: this pass completed the FE00–FEFF address inventory and compared the original and named EEPROM overlays.
- No device access, RAM write, firmware write, or EEPROM write was performed for this audit.

## Reproduction and residual questions

The commands under E-001 through E-003 reproduce the disassembly. Address arguments passed through R6:R7 must be followed into helpers: 697C performs bit updates, 65CD performs masked read-modify-write, 700A reads one byte, and 7011 writes one byte. A raw byte-pattern search alone can mistake instruction operands or data for code, so these sites were decoded at ROM instruction boundaries.

The FE20/FE22/FE28 silicon function remains unnamed. FE80, FE8E, FE8F and FEB9 lack hardware labels. FE84/FE85 remain horizontal scaling/phase candidates; the ROM source reviewed here does not encode width/height semantics, while prior pattern captures show a response to horizontal detail and phase. FEBA's low-five-bit no-signal selector role is supported by prior live sweeps documented in [no-signal patterns](ms2109-reference/no-signal-patterns.html); those measurements were not repeated in this offline pass.
