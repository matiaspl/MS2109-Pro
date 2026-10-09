# CC10 and the audio rate registers

6 October 2026. This extension traces actual ROM instructions and saved EEPROM bytes. It does not read or modify the connected dongle. See the [reference index](README.html) for pinned identities and evidence terminology.

## Does CC10 need fixing?

**No change is indicated for the reviewed factory and calibrated EEPROM images.** Both have header flags 05, which leaves the USB replacement gate disabled. Their CC10 entry is the same 15-byte table helper, and the original video caller intentionally enters it. Enabling bit 1 without changing this layout would create a bug; leaving it disabled is valid.

The saved experimental USB trace wrapper already contains the fix for a separate, real bug: its `record_set_interface` subroutine must RET to its LCALL caller before the outer wrapper restores saved registers. Earlier versions jumped directly into restoration with the helper return address still on the stack. The corrected wrapper's USB and video paths pass the existing instruction tests. Earlier signal-backed live traces also completed, as recorded in [the experimental report](../2026-10-06_sample-offset-firmware-options.html). They did not fix audio sample alignment.

### What the factory CC10 actually does

The table can now be identified more precisely as the **EDID upload path**:

1. Factory overlay D118 loads R3:R2:R1 = FF:CD:52, then tail-jumps to CC10 at D11E.
2. CC10 stores that pointer in XDATA DE05–DE07, calls ROM 6345 and returns. R3 is the generic-pointer space tag, R2:R1 the address.
3. ROM 6345 saves the pointer in C54E–C550 through helper 08E7 and sets F819 bit 0 through 7018.
4. At 6354 it reloads the pointer, sets R4:R5 = 0100 (256 bytes), R6:R7 = FB00 (destination), and calls generic byte-copy routine 5038.
5. Routine 5038 reads through generic-pointer helper 0492 and writes through 7011. For tag FF, 0492 reaches MOVC, so the source is CODE CD52–CE51. Destination writes cover XDATA FB00–FBFF.
6. ROM 6365 clears F819 bit 0 through 000E/65CD and returns. It clears the bit rather than restoring its entry value.

The original image's 256 source bytes begin `00 FF FF FF FF FF FF 00`; both 128-byte blocks have zero additive checksum. Together with the CODE source and 256-byte copy, this strongly identifies FB00–FBFF as the EDID storage aperture and F819.0 as an associated upload/access control. **Its electrical behavior, DDC visibility during writes, and exact vendor bit name are still inferred.** No HPD timing contract is established here.

The helper uses shared RAM C54E–C550 and C5EE–C5F6, as well as the masked-write helper's scratch C5B2/C5B3. It is not a general-purpose reentrant callback and should not be invoked from an arbitrary interrupt while those services are active.

### If USB interception is added later

A clean replacement firmware should give the EDID helper a separate entry and redirect its known caller, reserving CC10 for USB request handling. The existing temporary trace instead multiplexes by checking the stacked return address 4792, produced by the exact ROM `LCALL CC10` at 478F. That technique is tied to this ROM revision; it is not a universal calling convention.

The USB path must delegate unhandled requests to 2AD0 and return correctly to the ROM continuation. Misrouting this path can also break HID access used for restoration. No new wrapper or EEPROM patch is needed for the currently reviewed flags-05 layout.

## FE62–FE67: exact software format

ROM entry 3E78 takes an unsigned 32-bit value in **R4:R5:R6:R7**, most significant byte first. It stores it at C568–C56B in big-endian order. A second 32-bit value already resides at C56C–C56F, also big-endian. The routine writes the low 24 bits of each value as follows:

| Register | Source | Meaning in normal reviewed callers |
|---|---|---|
| FE62 | C56B | Input-rate bits 7:0 |
| FE63 | C56A | Input-rate bits 15:8 |
| FE64 | C569 | Input-rate bits 23:16 |
| FE65 | C56F | Output-rate bits 7:0 |
| FE66 | C56E | Output-rate bits 15:8 |
| FE67 | C56D | Output-rate bits 23:16 |

The two register triples are little-endian integers, not six independent tuning coefficients. The normal call paths use sample rates in Hz, as shown by the 48000 output constant and the standard-rate results of classifier 3F9B. “Input” and “output” describe their inferred rate-conversion roles; physical resampler implementation and register latch timing remain unknown.

The full instruction path is equivalent to:

```text
C568_u32_be = R4:R5:R6:R7
F809 = F809 | 0x80
FE62..FE64 = little_endian_24(C568_u32_be)
FE65..FE67 = little_endian_24(C56C_u32_be)
if C568_u32_be == C56C_u32_be:
    FE61 = FE61 | 0x08
else:
    FE61 = FE61 | 0x01
    FE61 = FE61 & 0xF7
```

The writes occur in the listed order. F809 bit 7 is set before the rate bytes and is not cleared by this routine. The comparison uses **all 32 bits**, although only 24 bits reach the hardware triples. High-byte disagreement can therefore select the unequal branch even when both register triples are identical.

The equal branch leaves FE61 bit 0 unchanged. Thus FE61 = 09 at equal rates is consistent with this routine; it is not evidence that bits 0 and 3 cannot coexist. The unequal branch sets bit 0 and clears bit 3 in two separate read/modify/write operations. Other FE61 bits are preserved in the modeled instruction path.

Calling bit 3 “equal-rate/bypass selection” and bit 0 “conversion enable” is a plausible hypothesis, not a verified hardware specification. No write here identifies a one-word skip or serializer phase adjustment.

### Common register values

These are outputs of offline execution of the actual saved ROM, with output rate fixed to 48000:

| Input rate (Hz) | FE62 FE63 FE64 | FE65 FE66 FE67 |
|---|---|---|
| 32000 | 00 7D 00 | 80 BB 00 |
| 44100 | 44 AC 00 | 80 BB 00 |
| 48000 | 80 BB 00 | 80 BB 00 |
| 88200 | 88 58 01 | 80 BB 00 |
| 96000 | 00 77 01 | 80 BB 00 |
| 176400 | 10 B1 02 | 80 BB 00 |
| 192000 | 00 EE 02 | 80 BB 00 |

### Where the values come from

Three direct call sites to 3E78 were found in the lower-ROM byte scan and then reviewed at valid instruction boundaries:

| Call site | Input value | Output value | Context |
|---|---|---|---|
| 4CD7 | C564–C567 loaded by 0866 | 48000 stored at C56C by the inline-constant helper | Nonzero classified rate; source measurement/state at C562–C563 enters classifier 3F9B |
| 570F | C54E–C551 loaded by 0866 | 48000 stored at C56C | Changed, nonzero classified rate; source path 6C4C reads F83D then calls arithmetic helper 04F3; classifier is 3F9B |
| 67E4 | Immediate 0000BB80 | Immediate 0000BB80 at C56C | Fallback/equal-rate setup; followed by normal command 12 |

Zero classifier results in the first two paths select 67D2, which sets both values to 48000 before calling 3E78. The output-role inference is therefore stronger than the earlier generic “rate parameters” description.

**Disassembly trap:** helper 088A consumes four inline constant bytes after its LCALL and resumes after them. At 4CCD, 5705 and 67D8 those bytes are `00 00 BB 80`. A naïve linear disassembler renders them as NOP/NOP/CJNE and loses the next instruction boundary. They are data, not conditional branches. A complete classifier/measurement calibration and every other user of C568/C56C remain outside this extension; these globals are reused elsewhere and should not be assumed permanent dedicated rate variables.

## Evidence and validation

- [Targeted ROM excerpts](../../artifacts/programmer-reference/rom-excerpts.txt): 3E78, helpers 0866/087E, 1E5A, 080F, CC10 consumer 6345 and copy routine 5038, plus correctly aligned caller continuations.
- [Byte evidence](../../artifacts/programmer-reference/evidence.json): 25 pinned signatures, including five new rate/EDID signatures.
- [CC10 audit](../../artifacts/programmer-reference/cc10-audit.json): exact ROM gate, calibrated-image helper/caller and disabled USB-hook bit.
- [Rate execution results](../../artifacts/programmer-reference/audio-rate-execution.json): actual ROM instruction execution, register-write order and standard-rate examples.
- [Rate tests](../../tests/test_audio_rate_rom.py): distinct-byte values verify byte order/truncation; all 256 initial FE61 values are checked on equal and unequal paths; a differing high byte verifies the 32-bit comparison. These tests model registers as memory, not peripherals or interrupt timing.
- [CC10 regression tests](../../tests/test_audio_usb_hook_execution.py): corrected SET_INTERFACE helper return, ordinary USB delegation, relocated EDID/video return and IRQ trace paths.

Reproduce from the repository root:

```sh
python3 tools/build_programmer_reference.py --disassemble
python3 tools/audit_audio_rate_rom.py
python3 tools/audit_audio_usb_hooks.py
python3 -m unittest discover -s tests -p 'test_audio_rate_rom.py' -v
python3 -m unittest discover -s tests -p 'test_audio_usb_hook_execution.py' -v
```

Nine test methods passed, including 512 FE61 initial-state subcases. Static decoding and execution agree. No hardware timing, audible conversion quality, unsupported-rate behavior or audio-phase repair is claimed.
