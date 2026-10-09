# Registers and firmware state

Return to the [reference index](README.html). This is a selected programming map, not an exhaustive silicon register list. `R/W` below describes accesses observed in code or prior experiments, not guaranteed access permissions. Unknown reset values and side effects are intentionally not filled with guesses.

## XDATA peripheral registers

For every explicit XDATA access in FE00–FEFF, including helper-mediated masked updates, see the [complete static FE-range inventory](../2026-10-08_reverse-ms2109-fe-register-audit-report.html).

For the non-FE control and peripheral accesses—including direct F0xx/F1xx/F5xx/F8xx sites and sparse helper-mediated F9xx/FAxx/FDxx/FFxx addresses—see the [non-FE live and static audit](../2026-10-08_reverse-ms2109-nonfe-register-audit-report.html). These addresses do not form one uniformly usable RAM bank: some are firmware state, some are mode fields, and some are command or streaming ports. Their prior-byte value does not guarantee that writing it back reverses a hardware side effect.

| Address | Working name | Access / encoding | Evidence and confidence |
|---|---|---|---|
| F800–F802 | Silicon identification | Read; expected A7 10 9A on the target | Observed and checked by `tools/ms2109_hid.py`; not three independently decoded revision fields |
| FE90 | Brightness | Written as signed 8-bit; UVC shadow is signed 16-bit | ROM 4D54 and prior color experiments; verified write target |
| FE91 | Contrast | Written as byte; shadow is nonnegative 16-bit | ROM 4D54; verified write target, not a general transfer-function specification |
| FE92 | Saturation | Written as byte; shadow is nonnegative 16-bit | ROM 4D54; verified write target |
| FE93 | Hue | Written as signed byte; shadow is signed 16-bit | ROM 4D54; verified write target |
| FE60 | Audio word/channel control | Value 01 produced corrected channel routing in the prior qualified patch | Observed result; complete bitfield unknown; does not establish sample alignment |
| FE61 | Audio rate/path control | Equal rates: OR 08; unequal: OR 01 then AND F7 | Exact operations verified; physical bit meanings remain inferred |
| FE62–FE64 / FE65–FE67 | Input/output rate values | Two little-endian 24-bit integers, copied from 32-bit big-endian state | ROM 3E78 executed offline; [full mapping](audio-rate-and-cc10.html) |
| F809 bit 7 | Rate setup control | Set before FE62–FE67 writes; not cleared in 3E78 | Verified software operation; hardware function unresolved |
| FE80 bit 0 | Video mode / horizontal-detail flag candidate | ROM helper 6A74 updates the bit from IRAM 20.0. A live `01→00` change reduced X-varying line-pair contrast in native and scaled captures, without moving corner markers. It produced a response close to FE84=`40`, but is not proven to be the same control. | ROM path and live response verified; hardware label unresolved; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) |
| F9A0 bit 0 | Scaler-enable candidate | ROM helper 6F6D sets bit 0; 6F35 reads it in video-mode paths. MS2107 source labels it `scaler_enable`. The 00/01 chart captures were identical at 1080p and unchanged in chart regions at 720p; a zero write did not clear it until USB reset. Treat as enable/status state, not a demonstrated bypass switch. | Static ROM, cross-family source, and live capture; see [scaler/sharpness investigation](scaler-and-sharpness.html) |
| FE81–FE83 | Unresolved video bytes | ROM audit found no direct access. Live bit-0 probes found no clear response from FE82/FE83; FE81's small response was close to capture variation. Other bits were not tested. | Purpose unresolved; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) |
| FE84 | Horizontal detail / resampling parameter candidate | ROM mode setup writes a caller byte directly to FE84. Prior selected-value sweeps showed frequency-dependent X-detail response; the current `7A→40` probe lowered X-varying contrast at native and scaled capture while preserving measured flat fields and corner geometry. Cross-family source calls it `vin_hscale_lo`. | Active control path; width/height and exact coefficient/comb-filter semantics are not established; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) and [scaler notes](scaler-and-sharpness.html) |
| FE85 | Horizontal phase / resampling candidate | ROM setup clears bit 1 with mask `02`; prior native pattern tests show phase response, and current live probes changed high-frequency patterns without moving corner markers. Cross-family source calls it `vin_hscale_hi`. | Strong horizontal-path evidence; not an input-size field; exact arithmetic unresolved; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) |
| FE86–FE8D | Unresolved video bytes | ROM audit found no direct access. Only bit 0 was probed live; it caused no clear response above capture variation in the tested modes. | Purpose unresolved; untested bits and timings remain open; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) |
| FE8E.0/.4, FE8F.0/.4 | Video luma/mode flag candidates | ROM updates these bits from a shared internal mode flag. Live FE8E changes alter gray levels/contrast; FE8F.0 changes levels in the 720p output path, while FE8F.4 had no clear effect. Individual bits were isolated; paired states were not tested. | Active, mode-dependent image path; field encoding unresolved; see [live FE80–FE8F probe](../2026-10-08_ms2109-fe80-fe8f-live-probe.html) |
| F819 bit 0 | EDID upload/access control candidate | Set before 256-byte copy, cleared afterward | ROM 6345; bit function inferred |
| FB00–FBFF | EDID storage aperture | Receives CODE CD52–CE51 through ROM 5038 | Static copy trace and EDID block checksums |
| F1F8 | Audio class control bit | Existing analysis follows a one-bit SET_CUR/GET_CUR path | Inferred UAC mute mapping; not PCM sample storage |
| F1FA–F1FF | Video/signal handshake state | Used by factory IRQ state machine | Firmware use established in prior analysis; hardware behavior and ownership incomplete |
| F900–F9FF | Video/timing candidate group | Many direct and helper-mediated accesses | Discovery grouping only; do not assign uniform register semantics to the range |

For these rows, see [original firmware analysis](../2026-10-05_reverse-ms2109-report.html), [producer phase-control report](../2026-10-06_ms2109-producer-phase-control-report.html), and the targeted ROM excerpts. Historic probe values are not power-on defaults. Calibration-specific brightness/contrast/saturation settings belong in calibration reports, not in a chip reset-value column.

## Complete static access map for XDATA FE00–FEFF

This inventory covers every explicit FE address found in the immutable ROM, the board's original EEPROM overlay, and the current named EEPROM readback. ROM accesses include both direct DPTR operands and addresses passed through the shared XDATA helpers. It describes firmware behavior, not a complete silicon register specification; arbitrary HID XDATA commands can address locations that the firmware itself does not name.

| Address | Firmware reads and writes | Where and how it is used | Confidence boundary |
|---|---|---|---|
| FE20 | Command latch: write 2B in ROM; write 2A in both original and installed EEPROM overlays | ROM calls 6B3D from 23EB. The routine writes 2B, reads FE22, then writes a result to FE28. The EEPROM command-01 handler at D082 writes 2A before its D27F setup helper. | Command latch is a useful working description. The peripheral function is not identified. |
| FE22 | Read in ROM | 6B43 reads this immediately after FE20=2B; only zero versus nonzero is tested. | Status-input behavior is exact; status meaning is unknown. |
| FE28 | Write 00 or 01 in ROM | 6B47–6B50 writes 00 if FE22 was zero and 01 otherwise. | Response behavior is exact; hardware side effect is unknown. |
| FE60 | Write 01 in installed EEPROM | D304 writes it only in the command-02 path, after declaring two audio channels and 48 kHz in C4C5/C4C9–CB. | Value and call path are exact. Prior qualification observed corrected channel routing; full bitfield and sample alignment remain unknown. |
| FE61 | Read-modify-write selected bits | ROM 3E78 compares the full input/output rates. Equal rates set bit 3. Unequal rates set bit 0 and clear bit 3. Other bits are preserved by the helper path. | Software operations are exact; physical bit labels are inferred. See [audio rate mapping](audio-rate-and-cc10.html). |
| FE62–FE64 | Write three bytes | ROM 3E78 writes the low 24 bits of the input-rate state in little-endian order. | Byte order/data source are verified offline; hardware timing semantics are only partly mapped. |
| FE65–FE67 | Write three bytes | ROM 3E78 writes the low 24 bits of the output-rate state in little-endian order. | Byte order/data source are verified offline; hardware timing semantics are only partly mapped. |
| FE80.0 | Read-modify-write | ROM 6A74 copies IRAM 20.0 into bit 0 through helper 697C during video-mode setup. | The copied flag and masked update are exact. Live `01→00` changes horizontal detail; the function remains unresolved. |
| FE81.0–FE83.0 | No direct ROM access found | Live one-bit probes only; FE81 response was near capture variation, FE82/FE83 had no clear effect. | Other bits and timings remain untested. |
| FE84 | Write one byte | ROM 6FA3–6FA9 writes the current register-bank value; the 6F3F caller supplies 7A. No ROM read of FE84 was found. | Active horizontal-detail/resampling path in live pattern tests. Not decoded as input width/height or sharpness. |
| FE85.1 | Read-modify-write, clear bit 1 | ROM 6A83–6A89 clears mask 02 through 697C; it does not write the value 02. Other bits are retained. | The software operation is exact. A horizontal-scale/phase role is supported by prior tests and cross-family labels, but is not a complete silicon decode. |
| FE86.0–FE8D.0 | No direct ROM access found | Bit 0 toggled live; no clear response above capture variation. | Other bits and timings remain untested. |
| FE8E.0/.4, FE8F.0/.4 | Read-modify-write | ROM updates bits 0 and 4 in each byte from the inverse of IRAM 20.0. | Live probes show FE8E luma/contrast changes and a scaled-mode FE8F.0 level change. Paired flag combinations remain untested. |
| FEB9.0 | Read-modify-write | ROM 6E76–6E80 copies IRAM 20.4 into bit 0. The 3F6B caller sets 20.4; another path copies 20.3 into 20.4 first. | Exact software source is known; hardware function is unresolved. |
| FEBA.4:0 | Read-modify-write | ROM 6EED–6EF5 copies the low five bits of current R7/IRAM 07 into FEBA and preserves bits 7:5. Stage 2 calls this after setting R7 to zero. | Exact mask/source are known. Prior live sweeps identify the field as the no-signal pattern selector; see [no-signal patterns](no-signal-patterns.html). |
| FE90 | Read and write | ROM 4D54 writes default F5, then reads the hardware byte into the brightness shadow. ROM 51F5 and installed EEPROM D248/D2DB also write current/default brightness. | Verified brightness target; signed-byte/16-bit-shadow behavior is covered in the procamp rows above. |
| FE91 | Read and write | ROM 4D54 writes default 94, then reads it into the contrast shadow. ROM 51F5 and installed EEPROM D250/D2DB write current/default contrast. | Verified contrast target. |
| FE92 | Read and write | ROM 4D54 writes default B4, then reads it into the saturation shadow. ROM 51F5 and installed EEPROM D260/D2DB write current/default saturation. | Verified saturation target. |
| FE93 | Read and write | ROM 4D54 writes default 00, then reads it into the hue shadow. ROM 51F5 and installed EEPROM D258/D2DB write current/default hue. | Verified hue target. |

The FE90–FE93 hardware order is brightness, contrast, saturation, hue. The C6A0–C6A7 shadow order is brightness, contrast, hue, saturation. Installed command 01 seeds shadow bytes EE FF 95 00 00 00 93 00 and then writes hardware bytes EE 95 93 00. Installed command 02 writes FE60=01 after setting the two-channel audio descriptor.

No other explicit FE address was found in the reviewed ROM or these EEPROM overlays. The ROM's FE helper arguments occur at 3E92, 3EA4, 3EC3, 3ED0, 3EE7, 3EF0, 3EF9, 3EFF, 6A7C, 6A87, 6CC8, 6CD8, 6CE8, 6CF8, 6E7E, 6EF3, and 6FA7. The complete static inventory and its reproduction steps are in the [FE-range audit report](../2026-10-08_reverse-ms2109-fe-register-audit-report.html).

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
| SFR AE | Endpoint 3 FIFO-like output in factory handler | Factory CD0C writes a 12-byte header-like sequence; CD3C/CD4B emit JPEG marker pairs FF D8 / FF D9. Consistent with video packet/frame handling; not disposable debug output. See the [factory space audit](../2026-10-07_ms2109-factory-space-report.html) |
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
