# Registers and firmware state

Return to the [reference index](README.md). This is a selected programming map, not an exhaustive silicon register list. `R/W` below describes accesses observed in code or prior experiments, not guaranteed access permissions. Unknown reset values and side effects are intentionally not filled with guesses.

## XDATA peripheral registers

| Address | Working name | Access / encoding | Evidence and confidence |
|---|---|---|---|
| F800–F802 | Silicon identification | Read; expected A7 10 9A on the target | Observed and checked by `tools/ms2109_hid.py`; not three independently decoded revision fields |
| FE90 | Brightness | Written as signed 8-bit; UVC shadow is signed 16-bit | ROM 4D54 and prior color experiments; verified write target |
| FE91 | Contrast | Written as byte; shadow is nonnegative 16-bit | ROM 4D54; verified write target, not a general transfer-function specification |
| FE92 | Saturation | Written as byte; shadow is nonnegative 16-bit | ROM 4D54; verified write target |
| FE93 | Hue | Written as signed byte; shadow is signed 16-bit | ROM 4D54; verified write target |
| FE60 | Audio word/channel control | Value 01 produced corrected channel routing in the prior qualified patch | Observed result; complete bitfield unknown; does not establish sample alignment |
| FE61 | Audio rate/path control | Equal rates: OR 08; unequal: OR 01 then AND F7 | Exact operations verified; physical bit meanings remain inferred |
| FE62–FE64 / FE65–FE67 | Input/output rate values | Two little-endian 24-bit integers, copied from 32-bit big-endian state | ROM 3E78 executed offline; [full mapping](audio-rate-and-cc10.md) |
| F809 bit 7 | Rate setup control | Set before FE62–FE67 writes; not cleared in 3E78 | Verified software operation; hardware function unresolved |
| FE80 bit 0 | Mode-dependent video input flag candidate | ROM helper 6A74 copies internal flag 20.0 into the masked update path for FE80 bit 0. The live post-boot value was 01. Exact hardware effect unresolved. | Static ROM; see [scaler/sharpness investigation](scaler-and-sharpness.md) |
| F9A0 bit 0 | Scaler-enable candidate | ROM helper 6F6D sets bit 0; 6F35 reads it in video-mode paths. MS2107 source labels it `scaler_enable`. The 00/01 chart captures were identical at 1080p and unchanged in chart regions at 720p; a zero write did not clear it until USB reset. Treat as enable/status state, not a demonstrated bypass switch. | Static ROM, cross-family source, and live capture; see [scaler/sharpness investigation](scaler-and-sharpness.md) |
| FE84 | Horizontal-scale low byte / active resampling candidate | ROM mode setup writes one caller byte directly to FE84 (`6F3F–6FB4`, `6FA3–6FA9`); HID B6 writes and reads it as a byte. MS2107 uses the pair as `vin_hscale_lo/hi`. At 720p, selected RAM-only values from `00` through `FF` were accepted and read back; response changed smoothly across `7F/80/81`, so bit 7 is active in this test. This establishes an 8-bit storage/control path, but not that all 256 codes are unique. The 8px stripe contrast rose from 0.145443 (`00`) to 0.333640 (`FF`); 4px contrast peaked near `B0` then eased. Flat-field Y stayed 16/232/117. At native 1080p, temporary `40` produced source-render stripe levels and 0.329513 contrast at 32/16/8/4/2px under startup procamp −18/149. In a matched 720p test, `40` reduced X-varying captured contrast against `7A` at all sampled pitches, while Y-varying response stayed effectively unchanged. The comparison reference was an AppKit render rather than an HDMI framebuffer, so pixel-perfect source-to-capture identity and whether `40` is neutral remain unresolved. Exact coefficient and comb-filter semantics remain unresolved. | Strong cross-family evidence plus repeatable live frequency-response change; see [scaler/sharpness investigation](scaler-and-sharpness.md) |
| FE85 | Horizontal-scale high byte / phase candidate (probable) | ROM setup clears bit 1 with mask `02` through `6A83–6A89 → 697C → 000E → 65CD`; it does **not** write value `02`. Live post-boot read was `00`. MS2107 labels FE85 `vin_hscale_hi` and clears the same bit with `&= 0xFD`. In native 1080p-in→1080p-YUY2 tests with FE84=`40`, every tested value with FE85 bit 1 set (`02,03,06,07,0A,0B,0E,0F,12,13,16,17,1A,1B,1E,1F,FF`) reverses the phase of the 2px B1 bars and 1px C1 grid: B1 MAE falls from 103.780 to 0 after a ±1px reference shift, while C1 MAE falls from 215.5 to 0.5. Values with bit 1 clear preserve phase; FE85=`00` gives zero B1 2px ROI error. Other high bits add small changes to detail response. Recommend `00` as the boot-aligned native candidate, not as a decoded universal setting; the candidate is not unique. The fresh run matched direct AppKit codes, while an earlier native session matched a full-to-limited Y model, so keep level mapping attached to each measurement. | Strong cross-family/init-sequence evidence and repeatable native phase response; exact arithmetic and HDMI level path remain unresolved; see [scaler/sharpness investigation](scaler-and-sharpness.md) |
| F819 bit 0 | EDID upload/access control candidate | Set before 256-byte copy, cleared afterward | ROM 6345; bit function inferred |
| FB00–FBFF | EDID storage aperture | Receives CODE CD52–CE51 through ROM 5038 | Static copy trace and EDID block checksums |
| F1F8 | Audio class control bit | Existing analysis follows a one-bit SET_CUR/GET_CUR path | Inferred UAC mute mapping; not PCM sample storage |
| F1FA–F1FF | Video/signal handshake state | Used by factory IRQ state machine | Firmware use established in prior analysis; hardware behavior and ownership incomplete |
| F900–F9FF | Video/timing candidate group | Many direct and helper-mediated accesses | Discovery grouping only; do not assign uniform register semantics to the range |

For these rows, see [original firmware analysis](../2026-10-05_reverse-ms2109-report.md), [producer phase-control report](../2026-10-06_ms2109-producer-phase-control-report.md), and the targeted ROM excerpts. Historic probe values are not power-on defaults. Calibration-specific brightness/contrast/saturation settings belong in calibration reports, not in a chip reset-value column.

## ROM EDID table (CODE space)

The mask-ROM image contains a 256-byte default EDID at CODE `7738–7837`. Its base block's first detailed timing descriptor is **1920×1080p60** (148.5 MHz pixel clock, 2200×1125 totals); the CTA extension lists VIC 16 (1080p60) and VIC 4 (720p60). Both 128-byte checksums are valid. This directly disproves “the ROM default EDID tops out at 720p” for this ROM revision. It does not prove which EDID is active when a board's EEPROM customization path is enabled; the MS2109 supports EEPROM-provided custom EDID. The table is EDID data, not a scaler register or a description of USB capture-output sizes.

The attached unit's `HDMI TO USB` output was also observed at 1920×1080@60, with 1280×720@60 available as a selectable mode. That confirms this host can drive both modes through this unit, but the EDID alone cannot establish whether an internal resampling stage exists. See the [matched input/output scaler test](scaler-and-sharpness.md#edid-and-the-720p-to-1080p-scaling-claim) for the evidence boundary.

## XDATA descriptors, shadows and workspace

| Address | Meaning | Encoding / ownership | Evidence |
|---|---|---|---|
| C4C5 | Audio format channel count | One descriptor byte; 02 for the existing stereo patch | Existing builder and saved descriptor reads |
| C4C9–C4CB | Audio descriptor sample frequency | 24-bit little-endian; 80 BB 00 = 48000 | Existing builder and saved enumeration |
| C6A0–C6A1 | Current brightness | Signed 16-bit little-endian | ROM 4D54 |
| C6A2–C6A3 | Current contrast | Nonnegative 16-bit little-endian | ROM 4D54 |
| C6A4–C6A5 | Current hue | Signed 16-bit little-endian | ROM 4D54 |
| C6A6–C6A7 | Current saturation | Nonnegative 16-bit little-endian | ROM 4D54 |
| C2A4 / C43B | Color descriptor record starts in saved RAM layout | Qualified builder checks six-byte descriptor before patching its matrix field | `tools/build_patch.py`; layout-specific, not hardware registers |
| C584 | Last normal callback command | Byte copied from R7 before CC00 is called | ROM 6FAC; newly byte-verified |
| C5B2–C5B3 | Shared register-helper address scratch | Big-endian address saved by 65CD | ROM 65CD; newly byte-verified |
| C54E | Loader attempt counter | Set to zero, incremented before attempts 0 and 1 | ROM 5F19 |
| C54F–C556 | Loader/validator shared workspace | Meanings change between routines: mode, pointers, lengths and sums | ROM 34A6 / 28F5 / 5E11; not persistent user configuration |
| C77E | Loader eligibility/status selector | Loader attempts reads when value equals 1 | ROM 5F19; upstream detection semantics not fully mapped |
| C788 | Image-validation status | 0 initialized; 1 oversized code; 2 header checksum mismatch; 3 code checksum mismatch | ROM 28F5 |
| CBD0–CBFF | Loaded EEPROM header | See image format; CBD4 contains hook bits | ROM 34A6 / 682E |
| DE05–DE07 | Factory table pointer scratch | R3, R2, R1 stored in order by CC10 | Original EEPROM CC10 |
| DE0B | Factory normal-command scratch | R7 stored by CC00 | Original EEPROM entry; patch preserves displaced operation |
| DE0C | Factory signal-state scratch | State-machine byte used by IRQ handler | Original overlay and existing analysis |

The procamp shadow order is **brightness, contrast, hue, saturation**. Hardware FE90–FE93 order is **brightness, contrast, saturation, hue**. Copying all eight shadow bytes to the four hardware addresses is therefore incorrect both in width and order. Updating only hardware can also leave UVC GET_CUR reporting stale shadow values.

The frequency and channel count are declarations to the USB host. They do not by themselves configure every audio clock, sample boundary or FIFO. Likewise, color descriptor fields describe interpretation; they are not procamp coefficients.

## SFRs and internal state

| Space / address | Meaning in reviewed firmware | Limits |
|---|---|---|
| SFR 81 | Stack pointer | Reset code sets 3C; not generally free for scratch |
| SFR 82 / 83 | DPL / DPH | MOVX and MOVC address register |
| SFR 93 | USB endpoint/bank selector | ROM writes 02 for audio endpoint setup and 03 for video endpoint work; preserve context across operations |
| SFR 80 / 90 | Selected endpoint control/status bytes | ROM EP2 setup writes 05 / 70; full bitfield and write side effects unresolved |
| SFR A2 / A3 | Selected endpoint configuration pair | ROM EP2 setup writes 00 / 01; packet-size interpretation is inferred, not a FIFO pointer |
| SFR AB | Endpoint 0 FIFO access | Setup parser reads request fields through it |
| SFR AD | Candidate endpoint 2 FIFO port | Prior reads/writes did not establish useful audio semantics |
| SFR AE | Endpoint 3 FIFO-like output in factory handler | Factory CD0C writes a 12-byte header-like sequence; CD3C/CD4B emit JPEG marker pairs FF D8 / FF D9. Consistent with video packet/frame handling; not disposable debug output. See the [factory space audit](../2026-10-07_ms2109-factory-space-report.md) |
| IRAM 0B / 0C | Parsed bmRequestType / bRequest | ROM 58C8 reads from AB |
| IRAM 0E | Parsed wValue low byte | Used by SET_INTERFACE path |
| IRAM 32 bit 2 | USB endpoint-2 work flag in reviewed IRQ path | Gates ROM endpoint-ready write after CC20 returns |
| IRAM 3A | Audio interface alternate setting | ROM 6807 copies IRAM 0E when interface equals 3 |
| Bit address 16 | EP0 pending-status flag | Not IRAM byte 16; consumed by common completion path |

Traditional assembler names such as `P0` for SFR 80 can obscure this chip's USB register usage. Distinguish an SFR bit address from an IRAM byte address and from XDATA at the same numeric offset. Keep the bank selector's current value with any SFR measurement; an unqualified “register 80 = 05” is incomplete evidence.

## Factory HID programming transport

The local [transport implementation](../../tools/ms2109_hid.py) uses nine-byte HIDAPI feature buffers, including a leading report-ID byte 00. This is a host API buffer description, not a USB endpoint packet-size claim.

| Command | Operation | Buffer after report ID |
|---|---|---|
| B5 / B6 | XDATA read / write | command, address high, address low, value, 00, 00, 00, 00 |
| C5 / C6 | SFR read / write | command, SFR address, value, 00, 00, 00, 00, 00 |
| E5 / E6 | EEPROM read / write | command, offset high, offset low, value, 00, 00, 00, size selector |

Read requests are sent, then fetched using GET_FEATURE. XDATA/EEPROM reply data is buffer byte 4; SFR data is byte 3. The tool checks command/address echoes. EEPROM size selector is 0 for its 2048-byte mode and 1 for larger mode. Only the original 2048-byte board/image is pinned by this reference; that selector is not a universal EEPROM-type discovery protocol.

A B5 read does not read lower CODE ROM merely because the address is numerically the same. The earlier ROM dump used a temporary executable MOVC helper and copied results into XDATA. The helper's [source](../../tools/dump_rom.py) is historical and explicitly restricted to original firmware; do not run it on a different layout without adapting its save/restore coverage.

## Expanding a register entry

For each new address, record the address space and bank, every confirmed reader/writer, operand width and byte order, observed values with device state, inferred bit meanings, and known side effects. Separate a ROM write constant from a reset default. Promote an indexed byte match only after decoding from a verified instruction boundary and following the consumer. Helper-mediated addresses in R6:R7 and computed addresses will not all appear in the DPTR-immediate index.
