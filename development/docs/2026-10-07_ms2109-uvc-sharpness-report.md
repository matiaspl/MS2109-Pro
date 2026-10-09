# MS2109 standard UVC Sharpness: offline implementation and qualification

Date: 7 October 2026. Report type: firmware reverse engineering; no vendor/security-report flavor.

**Current status (8 October 2026):** UVC Sharpness has been removed from the rebuilt control-repair candidate. Its volatile RAM qualification stopped before any write because loaded runtime bytes differed from EEPROM; the candidate is not installed. See the [removal report](2026-10-08_ms2109-sharpness-removal.md). The Sharpness-enabled implementations and results below are historical evidence and do not describe the current profile.

The two previous implementation gates are resolved offline: the generated handler consumes two-byte SET_CUR payloads through the stock ROM FIFO reader, and serves guarded Sharpness-enabled configuration descriptors while preserving the stock-selected source. The complete prototype implements the agreed 0–127 range, default 64, FE84 mapping and FE85=0 repair. All 36 repository tests pass. It requires **2,614 code bytes**, exceeding the existing 1,996-byte code budget by **618 bytes**, so no EEPROM candidate was emitted. This deficit measures the current implementation; it does not prove that further compaction is impossible. No device RAM, EEPROM or flash was accessed during this pass.

## ROM-only EDID option

At the user's request, a separate offline variant now uses the default ROM EDID directly. It redirects the factory D118 pointer from `FF:CD:52` to `FF:77:38` while retaining the factory upload routine. No EDID delta or reconstruction buffer is needed. The vacated custom-table area holds the common/calibration hook, repair routine, factory-helper fallback and query/state bytes. The original custom-EDID profile still produces exactly the same overlay hash recorded below.

| Profile | Code bytes | Deficit against 1,996 | Unused bytes in former EDID region |
|---|---:|---:|---:|
| Custom EDID | 2,614 | 618 | 4 |
| ROM EDID | **2,439** | **443** | 22 |

The measured saving is **175 bytes**, not 256: the custom profile already stored a compressed delta and reused much of its table area for executable code. The ROM variant retains 22 bytes of unused space in that region. This layout is not claimed to be the smallest possible packing.

Both ROM EDID blocks have valid checksums; its preferred detailed timing is 1920×1080p60 at 148.5 MHz, and its video block includes 1080p60 and 720p60. The audio capability block is byte-identical to the custom EDID (`09 07 07`). The custom video list includes additional VIC bytes `5F 64` and an extended video block `0E 61 60 66 65` absent from ROM; base display/range fields and the HDMI vendor block also differ. Consequently, switching EDIDs changes what the HDMI source is offered, even though the desired 1080p60 and 720p60 timings remain available. USB capture-format descriptors and the calibrated/audio firmware settings are separate and retained.

The full suite now passes **49 tests**, including the same handler/descriptor/calibration tests for both layouts. The ROM variant executes the actual factory pointer setup and ROM upload, verifies FB00–FBFF equals ROM `7738–7837`, and confirms DD00–DDFF is untouched. It remains offline-only and over budget; no physical reconnection, source-mode selection or capture qualification was performed.

Evidence: [ROM variant qualification](../artifacts/sharpness-firmware/20261007-rom-edid/qualification.json), [decoded hooks](../artifacts/sharpness-firmware/20261007-rom-edid/decoded-hooks.txt), [49-test log](../artifacts/sharpness-firmware/20261007-rom-edid/tests.txt), and [source/artifact hash manifest](../artifacts/sharpness-firmware/20261007-rom-edid/sha256-manifest.json). These extend E-002/E-003/E-004 and F-003: the new measured deficit is 443 for the optional ROM profile; the prior custom-profile evidence remains valid for its original build. P-001 is unchanged except the factory EDID route directly selects ROM instead of reconstructing a table. Observation date: 2026-10-07; confidence high for offline behavior and size, physical behavior unqualified.

Reproduce with a new output directory:

```sh
python3 tools/qualify_sharpness_offline.py artifacts/sharpness-firmware/new-rom-edid-run --edid-source rom
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/sharpness-firmware/new-rom-candidate.bin --sharpness-profile --sharpness-edid rom --rom backups/ms2109-maskrom.bin
```

The second command refuses output with `deficit 443 bytes`. No EEPROM image is emitted by either command.

## Scope and inputs

The user's approved plan authorizes building and reversible RAM qualification, with installation deferred to separate authorization. See [scope.md](scope.md). This pass uses local saved ROM/EEPROM files, generated code and offline tests only; network access is unnecessary. The size gate was reached before live qualification.

| Input | SHA-256 |
|---|---|
| Original 2,048-byte EEPROM, `backups/ms2109-original.bin` | `37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1` |
| Saved ROM, `backups/ms2109-maskrom.bin` | `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8` |
| Calibrated stereo rollback image | `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82` |

The binaries are raw 8051 firmware, with no PE/ELF import table. ROM addresses are hard-coded ABI dependencies, pinned by the complete ROM hash. Tools: radare2 6.2.2 +0 abi:142 @ darwin-arm_64; Python 3.14.7. The instruction harness is project-local; it models the exercised instruction subset and carry, not a complete 8051 peripheral system, parity/overflow/auxiliary-carry behavior or interrupt timing.

## Build and memory accounting

| Component | Bytes |
|---|---:|
| Retained original code and former checksum bytes | 1,720 |
| Appended common hook, shared calibration helper, CC10/USB/descriptor code and state | 894 |
| Total loaded code | **2,614** |
| Maximum code in the 2,048-byte EEPROM | **1,996** |
| Deficit | **618** |
| Hypothetical image length including 52-byte overhead | 2,666 |

Inside the existing 256-byte custom-EDID region, the lossless delta takes 124 bytes, its decoder takes 84, and FE84/FE85 repair takes 44; four bytes remain unused. These bytes are already included in the retained 1,720-byte region. Calibration uses one guarded record helper for both color records and both callback stages. Moving repair into the reclaimed EDID space and sharing the per-record guard saved 70 bytes from the first complete prototype.

| Memory range | Purpose |
|---|---|
| `CC00–D635` | Complete offline overlay; larger than the allowed `CC00–D3CB` |
| `CD52–CDCD` | 124-byte ROM-relative EDID delta |
| `CDCE–CE21` | EDID decoder and factory-helper fallback |
| `CE22–CE4D` | Read/compare/write repair routine |
| `D4F4–D4FA` | Query constants |
| `D4FB` | Current Sharpness selection, initial byte 64 |
| `D800–DCBA` | Proposed 1,211-byte descriptor-response buffer |
| `DD00–DDFF` | Proposed 256-byte reconstructed EDID |
| `C020–C021` | Stock ROM EP0 staging area |

The proposed scratch ranges do not overlap one another or the generated overlay. This proves local arithmetic separation only. ROM/interrupt ownership, stack headroom and reentrancy still require audit and hardware qualification. The tests exercise a bank-zero ROM ABI with stack starting at `50`; they do not establish worst-case live interrupt stack usage.

The builder now has `--sharpness-profile`, which includes calibrated procamp defaults and stereo routing. It rejects conflicting profile flags and requires the pinned ROM. Its packaging gate runs before file writes, so this oversized implementation produces no `.bin`, `.hook.bin` or metadata image output. If a future implementation fits, the packaging path sets header flags to `07`, recomputes both checksums and validates the 2,048-byte layout; that successful fit path has not been exercised for the present prototype.

## Resolved ROM contracts

### Dispatch and setup fields

ROM `478F` invokes CC10 with return address `4792` when header-loaded `CBD4.1` is set. The factory helper caller at `D118` instead supplies generic pointer `FF:CD:52`. The new dispatcher checks the return address while preserving the original caller context, sends USB traffic to the custom handler, and retains the factory helper route.

ROM `58C8` parses the eight-byte wire setup packet into IRAM `0B–12`: type, request, wValue **high/low**, wIndex **high/low**, wLength **high/low**. It also caches length at XDATA `C000:C001`. Thus Sharpness uses selector `08` at IRAM `0D`, zero at `0E`, entity 2 at `0F`, interface 0 at `10`. The wire wValue is `0800`, wIndex `0200`; the two-byte control payload is little-endian. Mixing these two byte orders would misroute the handler.

### SET_CUR, queries and status

The custom SET path follows ROM `2712`: set SFR `80.6` to acknowledge setup, wait on `80.0`, call `4B69` to prepare generic pointer `01:C020`, and call `62CA` with R7=2. Read C021 first and reject nonzero; then reject C020 bit 7. Only accepted values change the selected byte and FE84; repair also forces FE85 to zero. Set internal completion flag `16` and run `2B8E`.

The query path stages C020/C021, calls `4B69`, and sends R7 bytes through `49C2`. GET_INFO returns one byte `03`; CUR/MIN/MAX/RES/LEN/DEF return two little-endian bytes with values current/0/127/1/2/64. Direction, target selector/entity/interface, reserved low wValue, declared length and value range are checked. Requests for another entity/interface/selector are delegated to stock ROM; malformed requests targeting this control stall without changing the selection.

| ROM entry | Contract established by trace and execution |
|---|---|
| `49C2` | Generic source R3:R2:R1; R7 byte count. Uses cached length, setup length and remaining bytes to calculate packet offset. Writes FIFO SFR AB. Clobbers A, DPTR, carry, working registers, IRAM `29:2A`, XDATA `C5F9–C5FB`; caller saves context. |
| `62CA` | Generic destination R3:R2:R1; R7 byte count. Reads FIFO SFR AB into the generic destination. Uses XDATA `C5F9–C5FB`, IRAM `28` and working registers. |
| `2B8E` | Uses internal flags `15` (stall), `16` (OUT complete), `14` (special), plus remaining `08:09`; controls endpoint-ready/status SFR bits and clears internal flags. |
| `5038` | Generic copy from R3:R2:R1 to XDATA R6:R7, count R4:R5; used for both bounded descriptor copy and EDID base reconstruction. |
| `6345` | Factory EDID upload: gates F819 bit 0 and copies 256 bytes into FB00–FBFF. |

Core transfer, copy and completion routines execute their actual saved ROM instructions in tests. The harness supplies FIFO bytes and readiness bits. It does not reproduce the hardware side effect of setup acknowledgement, data arrival delays, host cancellation, short OUT packets or interrupt interleaving. Those are material live qualification gates, especially for the synchronous OUT wait.

### Descriptor selection and packet continuation

Active configuration requests use helper `4B10`, which reads the stock-selected pointer at `C002:C003`. Other-speed requests use helper `4B37` and the fixed ROM table at `75CC`. The prototype validates descriptor type/header, one of the reviewed lengths (1,211 or 355), and the eight-byte PU identity/layout record `0B 24 05 02 01 00 00 02` at offset `39`. It copies the selected source and ORs only capability bit `10` at offset `41`. Any guard failure delegates to the stock handler without modifying the source descriptor.

Each response is bounded to min(wLength, table length) and delivered in chunks of at most 64 bytes. The helper needs both setup and cached lengths to compute continuation offsets, so these are temporarily bounded and restored each callback; remaining `08:09` persists between packets. Tests cover 0, 9, 63, 64, 65, 128, exact length, overlength and 65,535-byte requests, including a relocated full-speed configuration source. Byte comparison confirms all fields other than the capability bit are preserved and buffer-edge canaries survive.

### Retained behavior and EDID

The calibration/audio hook is compared against the byte-exact rollback build for 32 callback stages and intact/damaged color records. The retained write sequence is identical after excluding the new selected-state/FE84/FE85 writes. Legacy brightness, contrast, hue and saturation requests run through actual ROM and match direct stock dispatch responses, procamp state and result registers. Audio, streaming and HID routing have context/delegation tests with a trapped ROM entry; their full protocol behavior and physical transport remain untested here.

All original factory code outside CC00's first three bytes, CC10's first three bytes and the 256-byte EDID table remains byte-exact. The original EDID is reconstructed at DD00 from ROM `7738` plus 11 delta runs and uploaded through actual ROM `6345`; all 256 output bytes match, including both checksums. The pinned D118 caller and literal scans identify the known source-table reference. They are not an exhaustive audit of computed references or interrupt reentrancy.

## Evidence, findings and call path

All paths below are relative to this report. Full artifact and source hashes are in the [SHA-256 manifest](../artifacts/sharpness-firmware/20261007-offline/sha256-manifest.json).

| Evidence | Source and observation | Reproduction | SHA-256 |
|---|---|---|---|
| E-001 | [ROM contract listing](../artifacts/sharpness-firmware/20261007-offline/rom-contracts.txt): setup, FIFO, descriptor and completion routines | Run the exporter below; `rom_commands` records the exact ranges | b8d1128933cc7670265a28dbdf50b1fe39a89e968edeb0b8528ecfa3c9ae9f4f |
| E-002 | [Test log](../artifacts/sharpness-firmware/20261007-offline/tests.txt): 36 passing tests, including 12 handler tests | `python3 -m unittest discover -s tests -v` | 859e8eb2a478c2bb9942c0d72aad59783d99b6e01efce90490d41b4634fde91e |
| E-003 | [Qualification/memory manifest](../artifacts/sharpness-firmware/20261007-offline/qualification.json): 2,614 code bytes, 618-byte deficit | Run the exporter below | ae54ca3b7d1541a78ae89850e1ffac48ff2280a7311a51f5b72d49ae5fcb55c3 |
| E-004 | [Decoded hooks](../artifacts/sharpness-firmware/20261007-offline/decoded-hooks.txt) and [branch audit](../artifacts/sharpness-firmware/20261007-offline/branch-audit.json): 153 branch/call destinations checked | Run the exporter below | 005ec15c48884ced16074a1bcbb5a673ad94fca786e49424299522a670a5320f (listing) |
| E-005 | [CLI refusal](../artifacts/sharpness-firmware/20261007-offline/packaging-gate.txt): nonzero exit and no output files | Run the builder command below with a new output filename | 96fec7483ef46fa64242939a71bf27ba749c9b01f7de4ce7fb85a598e2cae51f |

All evidence was observed on 2026-10-07; source type is local command/file. There is no live-device evidence in this bundle. Existing dispatch evidence is extended, not erased.

| Finding | Status, severity, confidence | Evidence | Location and implication |
|---|---|---|---|
| F-001 | Validated offline; n/a_re; high | E-001, E-002 | `62CA/49C2/2B8E`: the stock EP0 contracts support the implemented Sharpness set/query path. Hardware timing remains a residual risk. |
| F-002 | Validated offline; n/a_re; high | E-001, E-002, E-004 | `4B10/4B37` and generated descriptor handler: guarded packet responses preserve selected configuration and unrelated fields. Scratch ownership remains a candidate allocation. |
| F-003 | Validated for this build; n/a_re; high | E-003, E-004, E-005 | Packaging requires 618 fewer code bytes. No flashable candidate exists. This is not a lower bound on all possible implementations. |

**P-001 — Sharpness control call flow** (`path_type=callflow`). Start: ROM USB poll/dispatch calls CC10 with return address 4792. Goal: return a valid control response or change FE84 without replacing unrelated ROM behavior.

1. Multiplex the return address and validate the setup target — E-001/E-004, F-001.
2. SET: consume two FIFO bytes through 62CA, validate, save selection and repair FE84/FE85; GET: stage the selected/query value and send through 49C2 — E-001/E-002, F-001.
3. Complete through 2B8E and restore the custom path's caller registers; delegate unrelated requests to 2AD0 before repair — E-001/E-002, F-001.
4. For descriptors, select the stock source, guard/copy/patch one capability bit and deliver bounded packets — E-001/E-002/E-004, F-002.

Residual risks: FIFO timing and cancellation; real memory/stack/interrupt ownership; lifecycle behavior; platform control discovery; current size excess prevents EEPROM qualification. The executable source and tests provide the reproduction for F-001/F-002; further compaction is the action required by F-003.

Timeline on 2026-10-07: traced SET/GET/completion and descriptor-source contracts; generated the complete handler; executed exhaustive valid control values and boundary descriptor transfers; compacted the shared guard and EDID-region repair routine; ran all regression tests; verified CLI packaging refusal. No hardware action followed the size gate.

## Reproduce and continue

Run from the repository root, with Python 3 and radare2 available:

```sh
python3 -m unittest discover -s tests -v
python3 tools/qualify_sharpness_offline.py artifacts/sharpness-firmware/new-offline-run
```

The exporter requires a new repository-local directory. It creates a raw **offline-only** overlay, decoded hooks, branch audit, ROM listings, qualification JSON, test log and hash manifest. That raw overlay has no EEPROM header/checksum container and must not be supplied to a programmer.

The dedicated build currently fails intentionally, before writing any output:

```sh
python3 tools/build_patch.py backups/ms2109-original.bin artifacts/sharpness-firmware/new-candidate.bin --sharpness-profile --rom backups/ms2109-maskrom.bin
```

Expected error: `Sharpness profile needs 2614 code bytes; 2 KiB EEPROM permits 1996: deficit 618 bytes`.

Next work is a broader code-size pass: the descriptor path and duplicated USB save/restore/dispatch occupy most new bytes, while further reclaiming factory space requires control-flow and table-reference proof. Keep every agreed behavior and validation rule while measuring each reduction. Once the image fits, finish the computed-reference, scratch/stack and interrupt audit before reversible RAM qualification. Then exercise actual USB queries/sets, stock requests, restoration, stream/format changes, HDMI recovery, native/scaled captures and EEPROM readback. Windows/Linux discovery and power-cycle acceptance remain later gates; this pass cannot claim those results.

Rollback remains [ms2109-calibrated-stereo-channel-order.bin](../artifacts/ms2109-calibrated-stereo-channel-order.bin). This pass did not install anything, so rollback was not needed.

Completion checklist: pinned inputs and rollback checked; actual generated and ROM instructions executed; EDID reconstruction exact; retained calibration/audio writes compared; generated branch targets decoded; all tests passed; oversize packaging refused; source/artifact hashes recorded. Hardware and release gates are explicitly incomplete.
