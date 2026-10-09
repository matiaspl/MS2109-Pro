# MS2109 compact Sharpness EEPROM candidate

## Current status — Sharpness removed

8 October 2026. The requested UVC Sharpness control has been removed from the rebuilt source profile. The candidate rejects selector 8, clears its capability bit from standard and other-speed response copies, stores no Sharpness value, and performs no FE84/FE85 writes. Its 1,816-byte image was written to EEPROM and verified by full readback. Cold-boot qualification is still pending: after a USB reset, runtime RAM reported the prior 1,904-byte overlay and UVC requests timed out. See the [removal and installation report](2026-10-08_ms2109-sharpness-removal.html). The following sections preserve the older Sharpness-enabled candidate as historical evidence and do not describe the current EEPROM image.

## Historical Sharpness-enabled candidate

7 October 2026. Offline firmware engineering and instruction-level qualification.

The complete ROM-EDID Sharpness profile fits the existing **2,048-byte EEPROM**. Its declared overlay is **1,994 bytes**, leaving **two bytes free** after the 48-byte header and four checksum bytes. This resolves the previous ROM-profile deficit of 443 bytes. The candidate has since been loaded into volatile RAM for live tests and removed afterward; the EEPROM remains unchanged. See the [RAM qualification report](2026-10-07_ms2109-compact-sharpness-ram-qualification.html). UVC GET/SET and stream tests passed. Type 7 passed through the overlay descriptor path, but the active type-2 response remained `bmControls=0x000F`; a one-byte edit of active descriptor RAM did not alter it. A USB reset clears volatile RAM and reloads the installed EEPROM, so fresh-enumeration qualification of this candidate cannot be done in RAM alone. The active response source and boot-time patch point remain unresolved.

The candidate starts with FE84=`40`, FE85=`00`, exposes standard UVC Processing Unit Sharpness on unit 2/interface 0, and accepts unsigned 16-bit little-endian payloads with values 0–127. Default is 64. The selected byte is retained in the loaded overlay and repaired into the registers after delegated USB requests and common polling callbacks; stage-1 initialization restores 64. Existing calibrated procamp defaults, stereo routing, HID delegation and retained factory video code remain present. Physical lifecycle and no-signal behavior still require qualification.

## Candidate and evidence

- [2 KiB EEPROM candidate](../artifacts/sharpness-firmware/20261007-compact-final/ms2109-sharpness-candidate.bin)
- [Qualification and memory map](../artifacts/sharpness-firmware/20261007-compact-final/qualification.json)
- [Decoded hook listing](../artifacts/sharpness-firmware/20261007-compact-final/decoded-hooks.txt) and [branch audit](../artifacts/sharpness-firmware/20261007-compact-final/branch-audit.json)
- [Test results](../artifacts/sharpness-firmware/20261007-compact-final/tests.txt) and [source/artifact SHA-256 manifest](../artifacts/sharpness-firmware/20261007-compact-final/sha256-manifest.json)
- [Existing calibrated stereo rollback image](../artifacts/ms2109-calibrated-stereo-channel-order.bin)

Candidate SHA-256: `d6c1c53fa43e8f4d622c37022fbd91a6bd093813af81585172750380071da596`.

Rollback SHA-256: `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. This identifies the previously verified image; the device was not reread during this offline pass.

## How it fits

The new profile incorporates the [factory-space replacements](2026-10-07_ms2109-factory-space-report.html): a compact descriptor-copy loop, the byte-identical ROM switch helper, removal of the multiply helper whose callers were replaced, and direct calls to four ROM routines instead of EEPROM wrappers. Their reclaimed regions total 213 bytes. These savings are combined with the following changes; their byte counts are not independently additive because packing and branch distance interact.

- Use the ROM EDID at `7738–7837`, as agreed. The custom EDID and reconstruction code are absent. ROM retains preferred 1080p60 and advertised 720p60; some additional custom video modes disappear. Its audio capability block matches the custom EDID.
- Compare the Processing Unit identity in a guarded loop against pinned ROM bytes instead of eight repeated comparisons.
- Reuse ROM packet-length/accounting helpers `4B5A`, `0DC2` and `0DD9` while retaining descriptor-length bounds, source selection and request-length restoration.
- Save bank-zero registers directly at the stock USB ABI; omit only context saves for registers/flags the compact routines do not change.
- Use shorter stores, nearby rejection/delegation branches, and linker-selected SJMP/AJMP/ACALL encodings. Page-relative calls use the page of the PC after the two-byte instruction.
- Pack complete routines into audited holes and append at `D2B4`, excluding the old checksum bytes from executable payload.

The 14-byte alternate startup/idle fragment remains intact. Timing tables, IRQ code, packet headers and JPEG markers remain present. The original custom-EDID and uncompacted ROM-EDID builders retain their previous exact overlay hashes and their oversize refusal behavior.

## Memory layout

| Range | Purpose |
|---|---|
| `CC00–D3C9` | Declared loaded overlay, 1,994 bytes |
| `CC13–CC19` | Query constants |
| `CC1A` | Current Sharpness value, initialized to 64 |
| `CD52–CE26` | Guarded configuration/other-speed descriptor handler |
| `CE27–CE51` | Shared calibrated matrix helper |
| `CF5E–CFAB` | Compact factory descriptor-copy routine |
| `CFAC–D030` | USB classification and SET_CUR handler |
| `D201–D228` | FE84/FE85 repair |
| `D229–D237` | Preserved factory EDID-upload helper behavior |
| `D2B4–D336` | Query handler, completion and context restoration |
| `D337–D3A3` | Common startup/polling callback |
| `D3A4–D3C9` | CC10 caller dispatcher |
| `D800–DCBA` | Proposed descriptor-response scratch buffer, 1,211 bytes |
| `C020–C021` | Stock ROM EP0 staging buffer |

The image has header hook flags `07`; both checksums are regenerated and validated. The overlay checksum is `16AA`. The two unused EEPROM bytes are `FF` padding, outside the declared code and checksum fields. Internal packing holes are distinct from that two-byte end margin.

## Verification and remaining qualification

All **71 repository tests pass**. The final suite executes generated 8051 instructions and pinned ROM routines. It covers all 128 settings and queries, malformed requests, descriptor packet boundaries and lengths, guarded delegation, context restoration, exact ROM EDID upload, retained calibration/audio writes, factory copy/switch behavior in the final packed overlay, and page-boundary call/jump encoding. Both retained profile hashes are checked. The independent radare2 audit decodes 437 instructions and checks 97 branch/call destinations against instruction boundaries or pinned ROM entries. A separate builder CLI invocation reproduced the candidate byte-for-byte; all source/artifact manifest hashes were verified.

This establishes the tested offline contracts, not hardware timing. The harness models the exercised instruction subset; it does not model full interrupt timing, USB peripherals or every arithmetic flag. The bank-zero calling convention, global ownership of reclaimed space and descriptor scratch, interrupt stack headroom/reentrancy, and short or interrupted OUT transfers still need qualification. No live device writes were made.

Next, qualify those runtime assumptions and perform the already authorized reversible RAM tests, followed by native/scaled captures and recovery tests. EEPROM installation remains a separate approval step; Linux V4L2 and Windows VideoProcAmp discovery and lifecycle acceptance follow installation. This candidate is not a claim of completed hardware acceptance.

## Reproduction

Use a new output path; the tools preserve existing artifacts.

```sh
python3 tools/qualify_sharpness_offline.py artifacts/sharpness-firmware/new-compact-run --edid-source rom --compact
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/sharpness-firmware/new-compact-candidate.bin --sharpness-profile --sharpness-edid rom --compact-sharpness --rom backups/ms2109-maskrom.bin
```

Both commands are offline. The second emits the EEPROM container, raw overlay and metadata; neither installs firmware.
