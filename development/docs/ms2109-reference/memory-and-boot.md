# Memory, boot and persistent storage

Return to the [reference index](README.md). Unless marked otherwise, the instruction paths below are verified static against the pinned inputs.

## Address spaces

| Space / range | Meaning | Access / persistence |
|---|---|---|
| CODE 0000–BFFF | Lower CODE region, treated as ROM in this analysis; includes instructions and constant tables | Instruction fetch / MOVC; no write mechanism established |
| CODE C000–DFFF | RAM-backed overlay, also accessible as XDATA | Instruction fetch / MOVC and MOVX; volatile |
| XDATA C000–CBFF | Descriptors, firmware state, header, workspace | MOVX; not EEPROM and not immutable CODE |
| XDATA CBD0–CBFF | 48-byte EEPROM header mirror | Loaded from EEPROM 0000–002F |
| CODE/XDATA CC00 onward | Loaded firmware body and adjacent checksum bytes | EEPROM offset 0030 maps to CC00 |
| XDATA DE00 onward | Factory overlay working storage, including DE05–DE07 and DE0B/DE0C | Owned by factory firmware; not generally free RAM |
| XDATA E000–FFFF | Peripheral-address candidates in this firmware | Accessed by MOVX; decode and side effects must be established per address |
| IRAM 00–7F | Register banks, bit-addressable state, stack and direct internal RAM | Direct/indirect 8051 data accesses |
| Direct addresses 80–FF | SFR namespace | Distinct from XDATA and from upper indirectly addressed internal RAM |
| EEPROM offsets 0000–07FF | Original board's persistent image | External serial EEPROM accessed through ROM/HID I²C services |

The overlay extent is the existing hardware reconstruction, supported by executed RAM hooks and the loader model. This revision does not independently measure every boundary. A MOVX read at address 0040 is not a CODE read at 0040; use MOVC for CODE. The available snapshot stops before CC00, so factory overlay code is taken from EEPROM, not from that snapshot.

“Flashing” in the project means writing the external EEPROM. No internal flash programming interface, erase-block geometry or flash controller has been established for this chip. EEPROM edits become executable after loading into RAM. Direct writes to the overlay affect the current execution image and do not persist through power loss.

## Image format

| EEPROM offset | RAM destination | Definition |
|---|---|---|
| 0000–0001 | CBD0–CBD1 | Magic A5 5A on this board; existing tools also recognize 96 69 for larger images |
| 0002–0003 | CBD2–CBD3 | Code length N, big-endian |
| 0004 | CBD4 | Hook-enable bitmask; see [callbacks](callbacks.md) |
| 0005 | CBD5 | Additional configuration bits consumed by ROM; not a second interchangeable callback mask |
| 0006–002F | CBD6–CBFF | Board configuration, including string bytes in this image; not universally unused FF padding |
| 0030–0030+N−1 | CC00–CC00+N−1 | Executable overlay body and embedded data |
| 0030+N, +1 | CC00+N, +1 | Big-endian header sum |
| 0032+N, +1 | CC02+N, +1 | Big-endian code sum |

Both sums are additive modulo 65536:

```text
header_sum = sum(EEPROM[0x02:0x30]) & 0xFFFF
code_sum   = sum(EEPROM[0x30:0x30+N]) & 0xFFFF
RAM address = EEPROM offset + 0xCBD0
```

Only the loaded image range follows the offset formula. It is not a mapping of the whole EEPROM into memory. For a 2048-byte image, header plus checksums leave at most 1996 code bytes. This storage limit is stricter than the loader's ROM check.

ROM 34DE–34E4 compares N using carry preset to one and rejects N > 13FC; accepted maximum N is 13FC. It then adds 0034, yielding header + code + four checksum bytes. At that upper bound, copying from CBD0 reaches DFFF. This is a RAM capacity bound, not evidence that this board contains a larger EEPROM. The companion validator at 2914 uses the same bound.

## Reset and load sequence

1. CODE 0000 jumps to 4149. The startup loop clears IRAM 01–7F, sets SP to 3C, and enters the startup-data initializer at 4190. The loop does not explicitly clear IRAM 00.
2. Startup reaches 31A5. It calls 0016, then EEPROM loader 5F19, then 69B0.
3. Loader 5F19 calls 682E to fill CBD0–CBFF with FF and explicitly zero CBD4/CBD5. It performs EEPROM detection/configuration through 6869. If C77E equals 1 it attempts the loading paths with R7 values 0 and then 1, stopping when validation succeeds.
4. Reader 34A6 obtains N from EEPROM offsets 2 and 3, bounds it, and sets destination CBD0 and count N+0034. One path uses bulk reader 5508; the alternate path calls byte reader 6BBA and stores each byte with MOVX. These are two reader paths, not evidence of two physical firmware slots.
5. Validator 28F5 adds header bytes CBD2–CBFF, compares the first trailing checksum, then adds N bytes starting at CC00 and compares the second. C788 is zeroed first; error values are 1 for oversized length, 2 for header sum mismatch, and 3 for code sum mismatch. Success returns carry set; checksum failures return carry clear.
6. After failed validation, 5F19 invokes 682E again. Disabling the header flags prevents gated callbacks; it does not erase already copied overlay bytes. After loader return, startup invokes normal stage 0, later stage 1, and then stage 2 from the polling loop.

The loader **copies first, checks later**. Do not interpret RAM code presence as proof that its header was accepted. C788 describes this validation routine's result; it is not a comprehensive boot-health indicator.

## Programming consequences

A replacement firmware must supply all enabled fixed entry points and every overlay function its own code calls. CC30/CC40/CC50 are only entry conventions when their flags are enabled; in the factory image those addresses can be ordinary instructions inside another handler. Adding a flag without reserving its entry can redirect execution into the middle of code.

Keep checksums outside the declared code length. Appending code beyond the existing body may require preserving old absolute addresses and moving checksums. Validate the image size and every branch target before loading it. The [local builder](../../tools/build_patch.py) illustrates a qualified image-specific implementation; its choices are not a generic silicon ABI.

ROM owns descriptor buffers, interrupt state and shared work areas. Avoid assuming gaps in a saved dump are free merely because they contain zero or FF. A RAM update to code that can be entered concurrently needs an explicit quiescing strategy; a HID write is not an atomic firmware replacement.
