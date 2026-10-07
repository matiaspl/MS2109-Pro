# MS2109 independent programmer reference

Revision 0.5 · 7 October 2026 · reconstructed from one MS2109 ROM revision and one factory EEPROM image.

The MS2109 control firmware uses an 8051 core, immutable CODE, a RAM-backed CODE/XDATA overlay, and an external EEPROM image. ROM loads the image into RAM and calls fixed entry points there. This reference describes that programming interface independently of the local audio/color patches. It is a partial reference, not a vendor datasheet or a complete replacement firmware specification.

Start with [memory and boot](memory-and-boot.md), then [callbacks and ROM services](callbacks.md) and [registers and firmware state](registers.md). Every address includes its address space. Names are descriptive names assigned by this project, not vendor symbols.

New detailed mapping: [CC10 EDID upload and FE62–FE67 audio rates](audio-rate-and-cc10.md).

USB descriptor paths, the corrected stage-2 MS2109-Pro RAM qualification, and EEPROM installation/readback: [USB descriptors](usb-descriptors.md); [RAM qualification](../../artifacts/ms2109-pro-name/20261007/stage2-ram-qualification-usb-reset-02.json); [installation record](../../artifacts/ms2109-pro-name/20261007/stage2-installation.json); [candidate report](../2026-10-07_ms2109-pro-name-candidate.md).

Further investigation: [no-signal bars and synthetic audio](no-signal-patterns.md), including the [UVC pattern-control feasibility assessment](uvc-pattern-controls.md).

Scaler lead: [F9A0, video scaling bytes, and sharpness controls](scaler-and-sharpness.md). F9A0 bit 0 remains an unverified scaler-enable candidate. FE84/FE85 are probable horizontal scaling bytes. FE84 changes scaled-720p spatial response, while native 1080p tests show FE85 bit 1 toggles a one-pixel horizontal pattern phase with FE84=`40`; `FE85=00` is the boot-aligned native candidate, though not uniquely optimal. Capture level comparisons depend on display profile, and an AppKit render is not an HDMI framebuffer. The ROM's default EDID advertises both 1080p60 and 720p60. The compact standard-UVC Sharpness profile uses 1,994 code bytes. RAM GET/SET probes and 1080p/720p stream starts passed; the active descriptor remains unresolved. A USB reset clears the RAM candidate and reloads EEPROM, so fresh-enumeration validation requires a separately authorized EEPROM install. All volatile RAM and the original EEPROM were restored. See the [compact implementation report](../2026-10-07_ms2109-compact-sharpness-report.md), [live RAM qualification](../2026-10-07_ms2109-compact-sharpness-ram-qualification.md), and [offline bundle exporter](../../tools/qualify_sharpness_offline.py).

Static USB evidence: [UVC dispatcher and Processing Unit records](../../artifacts/programmer-reference/uvc-sharpness-dispatch.txt). The transcript includes the ROM request gate, built-in handler branches and the three descriptor copies reviewed for the Sharpness bitmap.

## Evidence and confidence

- **Verified static**: instruction bytes and control flow reviewed in the pinned local image. This proves what this firmware does, not the electrical meaning of every hardware bit.
- **Observed**: hardware measurements linked to their reports, including the current FE84 response and restore checks.
- **Inferred**: a likely purpose based on use; unsuitable as a complete hardware contract.
- **Candidate**: raw byte-pattern match awaiting code/data and control-flow review.

[Generated evidence](../../artifacts/programmer-reference/evidence.json) contains input hashes, 25 checked byte signatures and candidate addresses, plus a checksum-validated decode of the ROM default EDID at CODE `7738`. [Targeted disassembly](../../artifacts/programmer-reference/rom-excerpts.txt) starts at reviewed entry points. The [candidate index](../../artifacts/programmer-reference/candidate-index.md) provides discovery leads; its entries are not all confirmed instructions or registers.

The file named `ms2109-maskrom.bin` is a **CODE-space snapshot through CBFF**. Its C000–CBFF tail is overlay RAM and must not be treated as immutable ROM. Likewise, addresses Dxxx in EEPROM code are RAM-backed functions, even where older source names call them “ROM helpers.” A whole-file linear disassembly can lose alignment at embedded tables; restart disassembly at a verified entry point.

## Reproduce the reference

Run from the repository root with Python 3 and radare2 on PATH:

```sh
python3 tools/build_programmer_reference.py --disassemble
```

The tool reads only saved artifacts, validates the factory image's two checksums, verifies pinned identities and reviewed byte signatures, and rebuilds the evidence/index. It does not import the HID transport or access hardware. Omit `--disassemble` to generate the index without radare2.

| Input | SHA-256 |
|---|---|
| `backups/ms2109-maskrom.bin` | `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8` |
| `backups/ms2109-original.bin` | `37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1` |

The factory EEPROM is 2048 bytes with 1716 code bytes and hook flags 05. The dump is 52224 bytes. These identities scope the reference; they do not identify the image currently installed on a device.

## Findings and evidence paths

| Finding | Evidence | Execution/data path |
|---|---|---|
| EEPROM is copied before validation | ROM 5F19, 34A6, 28F5 | reset → loader → CBD0 header / CC00 code → additive checks → enabled hooks |
| Six dispatch bits have distinct behavior | ROM 6EF8, 4788, 2CB3, 5254, 560C, 5813 | CBD4 bit test → fixed overlay entry → ROM continuation |
| CC10 has two incompatible uses unless firmware multiplexes them | ROM 4788 and original EEPROM CC10 | USB replacement dispatch versus factory video-table helper |
| Register helpers share global scratch RAM | ROM 65CD | save address in C5B2/C5B3 → read → mask → reload address → write |
| Runtime state and peripheral registers need separate definitions | MOVX paths and prior capture reports | firmware shadow/descriptor → hardware programming or USB reply |

Survey/imports equivalent: these are raw 8051 images, with no PE/ELF import or export metadata. Their interfaces are fixed absolute calls, interrupt vectors, MOVX accesses and overlay entries. This revision uses ordinary firmware analysis (`flavor = null`), within [project scope](../scope.md).

## Coverage limits and next mapping work

The boot/load/checksum path, six callback gates and primitive register helpers are traced. The register table is deliberately selective; the generated index contains many additional candidates. Still unresolved are complete callback clobber/reentrancy contracts, computed command callers, full SFR banking and side effects, HDMI receiver/timing bitfields, the exact F9A0 scaler behavior and any sharpness register, and audio FIFO/DMA phase control.

Next useful work is to follow each candidate through its register helper or MOVX consumer, recover reset/write masks, and attach a minimal hardware observation to inferred bitfields. A bulk dump cannot establish clear-on-read, write-one-to-clear or latch timing. Keep those fields unknown until tested.

The older [architecture overview](../ms2109-firmware-architecture.html) illustrates the system, but its patch-specific image details are historical. The pages here are the independent interface reference.

Factory space audit: [213 bytes reclaimable through offline-tested code substitutions](../2026-10-07_ms2109-factory-space-report.md). The IRQ frame/header block is retained; a 14-byte startup/idle fragment is a separate dead-code candidate. Reclaimed holes have not yet been packed into the Sharpness image.
