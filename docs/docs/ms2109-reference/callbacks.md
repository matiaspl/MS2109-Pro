# Callbacks and ROM services

Return to the [reference index](README.html). Addresses in this page are CODE unless another space is named. Instruction-level mappings are verified static; human-friendly peripheral names remain qualified where needed.

## Callback gates

All six gates read XDATA CBD4, the mirror of EEPROM byte 4.

| Bit | Entry | Gate / caller | Behavior |
|---|---|---|---|
| 0 | CC00 | 6EF8 → 6FAC → CC00 | Normal callback. R7 is the command; 6FAC mirrors it to XDATA C584. Returns to ROM. |
| 1 | CC10 | 4788; call at 478F | Replaces ROM USB request handler 2AD0. ROM subsequently clears bit-address 13 and returns. |
| 2 | CC20 | 2CB3; call at 2CBA | Extends USB interrupt processing; subsequent ROM endpoint work still runs. |
| 3 | CC30 | 5254; call at 525B | Replaces the local default branch in ISR 5237, reached from vector 000B. |
| 4 | CC40 | 560C; call at 5613 | Replaces the local default branch in ISR 55EF, reached from vector 0013. |
| 5 | CC50 | 5813; call at 581A | Replaces call to 3269 in ISR 57F6, reached from vector 0023. |
| 6–7 | Unknown | No reviewed gate in this revision | Do not assign an entry by extrapolation. |

The vector locations coincide with conventional 8051 timer/external/serial vectors; the table uses vector addresses because chip-specific peripheral routing is not fully established.

Callbacks entered by LCALL return with RET. The enclosing ROM ISR owns its eventual RETI. ISR prologues at 5237, 55EF and 57F6 save ACC, B, DPH, DPL, PSW and R0–R7, and select bank 0. This does not grant unrestricted use of SFRs, shared XDATA or ROM helper scratch areas. Complete interrupt nesting and reentrancy contracts are not yet recovered.

### The CC10 collision

Follow-up: [CC10 is the EDID upload helper](audio-rate-and-cc10.html). The reviewed flags-05 firmware needs no CC10 patch; the optional trace wrapper already contains its separate stack-return fix.

The original EEPROM has flags 05: bit 1 is clear. Its CC10 implementation saves R3:R2:R1 into XDATA DE05–DE07 and calls ROM 6345. The factory code invokes it with a CODE table pointer (FF:CD:52 in the reviewed image). It is therefore a video/table helper in that image, not an implemented USB request replacement.

If bit 1 is enabled, ROM will enter exactly the same CC10 address for USB control requests. A firmware port must relocate or explicitly multiplex the table helper and install a suitable USB entry. Preserving CC10 bytes and enabling bit 1 is not sufficient. See the existing [USB hook audit](../../tools/audit_audio_usb_hooks.py) for the separately pinned patched-image path.

### Normal commands and timing

| R7 | Site | Meaning supported by this ROM |
|---|---|---|
| 00 | 31AE–31B0 | Boot, after EEPROM loader and 69B0 |
| 01 | 31F5–31F7 | Boot, after 5884 and procamp initialization 4D54; before global interrupt enable at 3203 |
| 02 | 324E–3250 | Polling-loop callback; not a one-time boot stage |
| 03–0C, 0E–15 | See generated candidate index | Immediate command values occur in byte patterns calling/tail-jumping to 6EF8; individual event semantics need further review |

Stage 2 is used by existing patches to reassert descriptors, but the ROM does not make it a dedicated “audio descriptor callback.” The factory hook stores R7 in DE0B and dispatches commands itself. Commands are firmware events, not addresses or function pointers. No exhaustive claim is made for computed command values or for absent 0D.

## Register service ABI

These small ROM routines have been fully read at the listed addresses. The notation R6:R7 means high byte in R6, low byte in R7. These are assembly contracts; an SDCC C call needs an appropriate wrapper.

| Entry | Inputs | Result / side effects |
|---|---|---|
| 700A | R6:R7 = XDATA address | Reads byte with MOVX; returns in A and R7; sets DPTR to address |
| 7011 | R6:R7 = XDATA address, R5 = value | Writes R5 using MOVX; A becomes value; DPTR becomes address |
| 65CD | R6:R7 = address, R5 = mask, R3 = replacement bits | Writes `(old & ~mask) \| (R3 & mask)`; uses XDATA C5B2/C5B3 as shared address scratch; changes A, DPTR, R4, R5, R6, R7 |
| 7018 | R6:R7 = address, R5 = mask | Sets mask bits through 65CD; copies mask into R4 and R3 before tail-call |

65CD is not an interrupt-safe atomic read/modify/write primitive: the instruction stream visibly separates read from write and stores the address globally. An interrupt using the same helper can overwrite that scratch address unless the caller's context prevents it. Reads and writes may also have hardware side effects; the generic helper does not establish that a target is safe for RMW.

## Other identified entry points

| Entry | Role | Evidence / limitation |
|---|---|---|
| 5F19 | EEPROM detect/load/validate coordinator | Traced in [memory and boot](memory-and-boot.html) |
| 34A6 | EEPROM image reader | Copies N+0034 bytes to CBD0; delegates physical reads |
| 28F5 | In-RAM image validator | Length and two additive checksums; status at C788 |
| 682E | Header mirror reset | Fills 48 bytes with FF then clears CBD4/CBD5 |
| 4D54 | Procamp initialization | Writes hardware and current-value shadow; later calls can overwrite a patch |
| 4DB4 onward | UVC default values | Prior ROM analysis identifies fixed GET_DEF constants; current-value patching does not change these |
| 67F1 | SET_INTERFACE handling | Audio interface 3 stores wValue low in IRAM 3A and sets pending-status bit 16 |
| 6345 | EDID upload | Generic pointer R3:R2:R1; copies 256 bytes to FB00 and sets/clears F819.0; [details](audio-rate-and-cc10.html) |
| 4648 / 4CF3 | I²C byte write / read | Existing upstream reconstruction; full local clobber and timing audit pending |
| 6A8C / 6ABA | I²C start / stop | Existing upstream reconstruction; not a guaranteed vendor public API |

Absolute ROM addresses are revision-specific. Helpers at Dxxx in other projects are overlay implementations, not guaranteed services on an uninitialized chip. The generated index lists possible ROM-to-overlay transfers; each needs instruction-boundary and reachability review before it is treated as a required entry.
