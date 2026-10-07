# MS2109 factory overlay: removable code and space audit

**Follow-up:** these replacements are now integrated into the [compact Sharpness candidate](2026-10-07_ms2109-compact-sharpness-report.md), which fits the 2 KiB EEPROM with 1,994 declared code bytes. The same-length experiment described below remains available as the original isolated audit.

7 October 2026. Offline analysis of the pinned original EEPROM and ROM; no device access. Scope: [scope.md](scope.md). This is a firmware engineering report, with no security-report flavor or import table: both inputs are raw 8051 images. Input hashes are pinned in the [audit](../artifacts/sharpness-firmware/factory-space-audit/audit.json).

**213 bytes can be reclaimed by replacements that passed offline equivalence tests, without deleting a user-facing feature.** The experiment compacts a descriptor-copy routine, substitutes an identical ROM switch helper, removes the now-unused multiply helper and bypasses four call-through wrappers. It also identifies a 14-byte startup/idle fragment unreachable from the reviewed entry points; that fragment is retained and excluded from the 213-byte total. These are holes in a same-length experimental overlay, not an already smaller EEPROM image. Against the ROM-EDID Sharpness prototype's 443-byte excess, perfect reuse of the tested holes would leave 230 bytes still to recover, before any relocation overhead or packing losses.

All **54 repository tests pass**, including five factory-space test methods covering copy equivalence, all 256 switch commands, actual ROM wrapper substitution, multiply semantics and patch boundaries.

## What passed offline tests

| Region | Existing role | Change | Reclaimed bytes |
|---|---|---|---:|
| `CF5E–D039` | Copies a timing table into MJPEG frame descriptors using two lengthy loops | One bounded loop, 78 bytes instead of 220 | **142** |
| `D201–D211` | Multiply helper used by the old copy loops | Both reviewed callers disappear in the rewrite | **17** |
| `D212–D237` | Compiler switch-table dispatcher | Redirect its caller at D03B to identical ROM routine `0910` | **38** |
| `D2A2–D2B1` | Four `LCALL ROM; RET` wrappers | Redirect their callers to `603C`, `5884`, `48E6`, `6069` | **16** |
| **Total** | | | **213** |

The experiment leaves those ranges as `FF` after replacement, making accidental entry easier to detect. It is saved as `compact-experiment.overlay.bin`, not an EEPROM container. It does not incorporate or repack the new Sharpness handler.

### Descriptor-copy rewrite

The source is a 25-byte constant table at CE52:

```text
0A 8B 02 00 05 0A 8B 02 00 15 16 05 00 80 1A 06 00 20 A1 07 00 40 42 0F 00
```

The destination is `C0BF + row*46`. Rows 0–4 receive 25 bytes; rows 5–10 receive the first four bytes. These offsets fall in the eleven MJPEG frame descriptors, at their default frame interval and interval-list fields. The first four bytes encode 166,666 in 100 ns units; the following list contains 166,666, 333,333, 400,000, 500,000 and 1,000,000. Removing this routine would change advertised timing behavior. The compact replacement keeps the data and writes.

Both implementations execute their actual instructions in the local 8051 harness. Across 32 seeded register/table fixtures, the replacement matches the original **ordered sequence of all 320 XDATA writes**: 149 descriptor bytes and 171 DE08/DE09 counter writes. Tests also compare lower IRAM, SP, DPTR, A, B and defined/tested result flags. No ROM memcpy scratch allocation is introduced. The original copy's multiply helper has two reviewed callers, CF95 and D003, both inside the replaced region.

The shorter implementation changes instruction timing. The harness does not model concurrent interrupts, memory-mapped peripheral timing or all arithmetic status flags. The copy tests establish the ordered memory effects and tested register contract, not physical qualification under interrupt nesting.

### ROM substitution and wrappers

`D212–D237` is byte-for-byte equal to ROM `0910–0935`. It consumes its caller's return address as a pointer to an inline switch table, so a naive disassembly of D03E as instructions is misleading. The audit decodes that table explicitly. Execution tests cover all 256 command bytes and compare chosen destination, register context and stack balance before the selected branch runs.

The four wrappers have exactly four bytes each. Their only reviewed overlay callers are:

| Wrapper | Direct ROM destination | Caller |
|---|---|---|
| D2A2 | 603C | D27F, LCALL |
| D2A6 | 5884 | D28A, LJMP |
| D2AA | 48E6 | CCC8, LCALL |
| D2AE | 6069 | CC28, LCALL |

Tests execute the real ROM callees through both routes with eight input-register fixtures each. Ordered XDATA writes, SFR traces except SP transitions, final registers and final stack depth match. The direct route deliberately removes one temporary return address from the stack. Real nesting/timing is still unqualified.

## Further candidates, not credited yet

- **14 bytes at D28D–D298 and D2B2–D2B3:** an alternate C-runtime startup clearing IRAM, setting SP=3C, then jumping into an infinite loop. The table-aware graph reaches 773 of 780 decoded instructions from CC00, CC10 and CC20; these seven instructions are the only unreached code. No direct literal call to their entries was found in the saved ROM. This is a strong dead-code candidate, but the graph is not a proof about every possible computed ROM entry.
- **One padding byte at CC1F.** In the Sharpness profiles, CC10 already jumps to a replacement dispatcher, also leaving the remaining 12 bytes of the old CC10 helper as a possible reuse area. Do not count the padding twice.
- **Four old checksum bytes at D2B4–D2B7:** currently retained for compatibility with the original append strategy. A new layout could omit this obsolete pair, while retaining the real checksums at the end of the new image.
- **22 bytes already unused inside the former EDID region** of the ROM-only Sharpness prototype. Reusing that existing slack requires packing; it is not an additional feature deletion.

These candidates have not been removed from the experimental overlay. Their references, entry assumptions and placement costs need review before they are credited as image-size savings.

## Keep these blocks

The factory IRQ block at CC20 is not expendable logging. At CD0C it writes a 12-byte header-like structure to SFR AE; at CD3C/CD4B it writes `FF D8` and `FF D9`, the JPEG start/end marker byte pairs. Together with its signal/endpoint state changes, this is consistent with video packet/frame handling. No test supports deleting it.

Retain CE6B–CF5D and D1BA–D200 video configuration, the mode-specific writes in D121–D1B9, and the F92C setup in D082. These are reachable and affect video/timing/no-signal-related state; removing them would change the behavior the plan requires us to preserve. Retain the D238 procamp synchronization routine, which conditionally copies host-control shadows to hardware. Likewise, the EEPROM header is board configuration rather than a general pool of spare bytes.

The available evidence supports reducing redundant implementation, not deleting whole video, audio, programming or no-signal features. The custom EDID has already been made optional in the separate ROM-only prototype.

## Evidence and findings

The [manifest](../artifacts/sharpness-firmware/factory-space-audit/sha256-manifest.json) records artifact and source hashes. All observations are local file/command results from 2026-10-07.

| Evidence | Source | Reproduction |
|---|---|---|
| E-001 | [Table-aware audit, references and unreached instructions](../artifacts/sharpness-firmware/factory-space-audit/audit.json) | `python3 tools/audit_factory_space.py` |
| E-002 | [Original linear listing](../artifacts/sharpness-firmware/factory-space-audit/factory-linear.txt); inline data is not code | See the separate table-aware regions in the auditor; the linear listing is contextual evidence only |
| E-003 | [Compact copy listing](../artifacts/sharpness-firmware/factory-space-audit/copy.txt), [identical ROM switch](../artifacts/sharpness-firmware/factory-space-audit/rom-switch.txt) | `python3 tools/audit_factory_space.py` |
| E-004 | [Execution/regression log](../artifacts/sharpness-firmware/factory-space-audit/tests.txt) | `python3 -m unittest discover -s tests -v` |

| Finding | Status / confidence / severity | Evidence | Location and implication |
|---|---|---|---|
| F-001 | Validated offline / high / n/a_re | E-001, E-003, E-004 | CF5E copy rewrite plus unused multiply frees 159 bytes with tested memory effects preserved |
| F-002 | Validated offline / high / n/a_re | E-001, E-003, E-004 | Switch and wrapper ROM substitutions free 54 bytes with tested call behavior preserved |
| F-003 | Candidate / medium / n/a_re | E-001, E-002 | D28D startup and D2B2 loop appear dead under reviewed roots; not deleted |
| F-004 | Candidate role / high for emitted bytes / n/a_re | E-001, E-002 | CC20 emits header/marker data and changes signal state; retain it rather than treating it as debug-only |

**P-001 — Factory descriptor initialization** (`path_type=callflow`): CC20 tests IRAM33 bit 2 → calls D2AE/ROM6069 → calls CF5E → copies CE52 into eleven descriptor records → returns to CC20. E-001/E-002 establish the route; E-003/E-004 support F-001/F-002 for the replacement. Residual risks are unseen computed entry points, complete interrupt/peripheral behavior and placement of new code in reclaimed holes.

Timeline: decoded factory sections and the inline command table; identified the exact ROM duplicate and unreachable startup fragment; wrote and tested the 78-byte copy routine; compared the four actual ROM callees against their wrappers; ran repository regressions. No hardware operations occurred.

## Reproduce and next step

```sh
python3 tools/audit_factory_space.py
python3 -m unittest tests.test_factory_space -v
python3 -m unittest discover -s tests -v
```

Inputs, outputs and test scope are explicit in [audit_factory_space.py](../tools/audit_factory_space.py) and [test_factory_space.py](../tests/test_factory_space.py). The emitted raw overlay retains the original 1,716-byte length. No checksum-valid smaller EEPROM image is claimed or emitted.

Next, repack generated Sharpness routines into the reclaimed holes and audit every relocated branch/data reference. Additional compaction is still required even with ideal use of the 213 tested bytes. Preserve the installed image and complete reversible RAM, timing and capture qualification before considering EEPROM installation.

Checklist: pinned images checked; table-aware call graph generated; ROM equality established; emitted replacement code executed; original ordered writes compared; 256-way switch and actual ROM callees compared; uncertainty recorded; no device state changed.
