# MS2109 color science and conversion search

Date: 2026-10-05, Europe/Warsaw. Report flavor: ordinary firmware reverse engineering.

The saved MS2109 ROM contains explicit color metadata and hardware picture controls. Its MJPEG and YUY2 descriptors declare **BT.709/sRGB primaries, BT.709 transfer characteristics, and SMPTE 170M / BT.601 matrix coefficients**. A hardware RGB-to-YCbCr path is strongly indicated by the supported input and output formats. This search did not identify its coefficient table, a verified matrix-selection register, a gamma LUT, or an 8051 pixel-conversion routine.

These are offline findings. No USB device was opened, no registers or EEPROM were written, and no video frames were captured during this search. The actual input format, output levels, conversion matrix, chroma filtering, and transfer behavior remain unmeasured.

## Scope and provenance

The user requested a search for signs of color science and color conversions. The existing [scope](scope.html) identifies the MS2109 project. This follow-up examines its saved ROM, original EEPROM overlay, local patch builder, and downloaded reference sources.

- ROM: `backups/ms2109-maskrom.bin`, 52,224 bytes, saved CODE addresses `0000–CBFF`.
- ROM SHA256: `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`.
- Original EEPROM SHA256: `37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1`.
- Original overlay: `artifacts/original-code.bin`, loaded at CODE `CC00`; SHA256 `912a3e060aa5a94af4db7e7245afba62a8e5707785f38fefc1e0cafca1863f6a`.
- Tools: radare2 6.2.2 and Python standard library. The metadata analyzer checks the exact ROM hash before applying these offsets.

`rabin2` sees the input as raw data and cannot recover its architecture from a file header. The disassembly explicitly selects 8051, 8-bit. There is no import/export table; firmware calls use absolute ROM addresses. The survey is saved in `artifacts/color-analysis/rom-survey.txt`.

## Findings

### F-color-metadata: output color declaration

Severity: n/a_re. Status: observed in saved templates. Confidence: high for decoded bytes; current host enumeration is unverified. Evidence: E-rom, E-metadata, E-uvc-definitions.

Walking complete USB configuration descriptors, rather than searching for isolated byte patterns, identifies these records:

| Configuration/template CODE address | Format | Color descriptor CODE address | Bytes |
|---|---|---|---|
| `7111`, configuration type `02` | MJPEG | `737B` | `06 24 0D 01 01 04` |
| `7111`, configuration type `02` | YUY2, 16 bits/pixel | `7512` | `06 24 0D 01 01 04` |
| `75CC`, other-speed configuration type `07` | MJPEG | `7665` | `06 24 0D 01 01 04` |
| `C03A`, configuration image within the saved dump | MJPEG | `C2A4` | `06 24 0D 01 01 04` |
| `C03A`, configuration image within the saved dump | YUY2, 16 bits/pixel | `C43B` | `06 24 0D 01 01 04` |

The `C000–DFFF` region is RAM-backed. These `C03A` records are bytes preserved in the earlier dump, not a new read of the currently running device.

The six-byte record decodes as:

| Field | Value | Meaning |
|---|---|---|
| bLength | `06` | Six bytes |
| bDescriptorType | `24` | Class-specific interface descriptor |
| bDescriptorSubType | `0D` | Color matching |
| bColorPrimaries | `01` | BT.709 / sRGB primaries |
| bTransferCharacteristics | `01` | BT.709 transfer |
| bMatrixCoefficients | `04` | SMPTE 170M matrix |

The [Linux UVC definitions](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/video.h) specify the fields and enumerations. [Linux color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html) describes the SMPTE 170M Y′CbCr transform as the BT.601 transform. Primaries, transfer, and matrix are separate properties; this combination does not itself establish an erroneous conversion.

The descriptor has no quantization-range field. It cannot establish full versus limited range. It also does not contain numeric matrix coefficients or execute a transform. Changing this metadata alone would change the declaration, not prove a change to the pixels.

### F-procamp: hardware gain, offset, saturation, and hue controls

Severity: n/a_re. Status: observed in ROM and patch source. Confidence: high for locations and writes. Evidence: E-procamp, E-patch, E-metadata.

| Control | Hardware XDATA register | Current-value RAM | Original startup | Patch startup |
|---|---|---|---|---|
| Brightness | `FE90` | `C6A0–C6A1` | `F5`, signed −11 | 0 |
| Contrast | `FE91` | `C6A2–C6A3` | `94`, 148 | 128 |
| Hue | `FE93` | `C6A4–C6A5` | `00`, 0 | 0 |
| Saturation | `FE92` | `C6A6–C6A7` | `B4`, 180 | 128 |

ROM `4D54–4DB3` initializes these registers and copies/sign-extends the values into RAM. ROM `51E4–5236` applies pending current-value changes back to the hardware. Boot calls initialization at `31F2`, then the EEPROM stage-1 hook at `31F5–31F7`. The local builder writes the four new values in that hook; it does not add a color matrix or LUT. Hard-coded UVC defaults at `4DB4–4E13` remain unchanged, as documented in the [existing patch report](2026-10-05_reverse-ms2109-report.html).

The processing-unit descriptors at `714A`, `7605`, and `C073` all advertise control bitmap `0x000F`: brightness, contrast, hue, saturation. They do not advertise gamma, white balance, or sharpness. This describes the exposed controls, not the full set of hardware features. The values 0/128/128/0 remain an intended neutral setting, not a measured color calibration.

### F-conversion: hardware conversion is indicated; its implementation is unresolved

Severity: n/a_re. Status: inferred architecture; conversion details unresolved. Confidence: high for input/output capabilities, medium for the architectural inference. Evidence: E-metadata, E-datasheet, E-procamp, E-search.

The manufacturer's [MS2109 datasheet, HJ-BMJL-PD-002 B/0](https://atta.szlcsc.com/upload/public/pdf/source/20241106/63E0CC799512327484A4AEBE801A6447.pdf), lists RGB444 and YCbCr422/444/420 receiver support, and YUV/MJPEG output. The local YUY2 GUID and 16-bit/pixel descriptor establish a packed 8-bit 4:2:2 output declaration. Together, these indicate a conversion/subsampling path for RGB or other chroma layouts when producing YUY2. They do not identify the currently active input mode.

The examined MCU paths configure registers and descriptors. No identified routine processes RGB pixels into Y′CbCr samples, applies an EOTF/OETF, converts a gamut, or performs HDR tone mapping. No confidently identified 601/709/2020 coefficient bank, 1D/3D LUT, or full/limited-range selector was recovered. Conversion may be implemented in hardware with fixed coefficients or automatic mode selection; the present evidence cannot choose between those implementations.

ROM `6CBD`, `6CCD`, `6CDD`, and `6CED` control masks `01` and `10` at `FE8E/FE8F` using helper `697C`. Boot routine `3F0B` calls all four with bit `20.0` set, which clears those masks. The write mechanics are identified, but their purpose and relationship to color processing are unknown. Proximity to the procamp registers is insufficient to call them conversion or bypass controls.

Do not transfer the MS2107 name `video_colorspace_setup` at `6DA0` from `upstream/macrosilicon_firmware/tools/GhidraRename.java` to this chip. That script explicitly targets MS2107; the MS2109 naming script supplies no corresponding color-conversion identification.

### F-edid: input-side color capabilities and gamma metadata

Severity: n/a_re. Status: observed in saved EDID template. Confidence: high for decoded bytes; active DDC contents are unverified. Evidence: E-edid, E-edid-definitions.

ROM `7738–7837` contains a 256-byte EDID, version 1.4, with valid checksums for both 128-byte blocks. Its gamma byte is `78`, giving declared gamma 2.2. The CTA extension starts `02 03 24 F1`; the `20` and `10` capability bits advertise YCbCr444 and YCbCr422. The default path at ROM `6189–618F` passes pointer `FF:77:38` to `6345`; the EEPROM-configured alternative takes a hook at `6182–6184`.

Chromaticity coordinates decoded from the template:

| Component | x | y |
|---|---|---|
| Red | 0.6396484375 | 0.3408203125 |
| Green | 0.287109375 | 0.6103515625 |
| Blue | 0.146484375 | 0.0693359375 |
| White | 0.28515625 | 0.29296875 |

These are advertised sink values. They are not a calibration measurement or evidence of an internal gamma/white-point transform. The EDID contains no extended colorimetry or HDR static-metadata data block. The absence of those advertisements does not prove the hardware cannot receive such signals. Field definitions are available in the [Linux DRM EDID header](https://github.com/torvalds/linux/blob/master/include/drm/drm_edid.h).

### F-reference-conversion: an actual host conversion belongs to MS912x

Severity: n/a_re. Status: observed reference source, excluded from MS2109 implementation claims. Confidence: high. Evidence: E-reference.

`upstream/macrosilicon_firmware/tools/ms_testpattern.py:31` implements a fixed-point RGB-to-YUV conversion:

```text
Y = (16·65536 + 16763·R + 32904·G + 6391·B) >> 16
U = (128·65536 − 9676·R − 18996·G + 28672·B) >> 16
V = (128·65536 + 28672·R − 24009·G − 4663·B) >> 16
```

It clamps each result to 0–255, averages chroma across two pixels, and packs `U,Y0,V,Y1`. This is a BT.601-like limited-range conversion; its exact integer arithmetic returns black `(16,128,128)` and white `(234,128,128)`. The file's header targets MS9123/MS9132 USB display adapters. It is not code executed by the MS2109 firmware or this patch.

## Evidence and reproduction

All local commands below run from the project root and use saved files only.

| ID | Source / observation | Reproduction |
|---|---|---|
| E-rom / E-imports | Saved raw 8051 ROM, hash above; no loader import/export metadata | `shasum -a 256 backups/ms2109-maskrom.bin`; `rabin2 -I -i -E backups/ms2109-maskrom.bin` |
| E-metadata | Complete configuration walks and five color descriptors; `artifacts/color-analysis/metadata.json` | `python3 tools/analyze_color_metadata.py backups/ms2109-maskrom.bin` |
| E-procamp | ROM init/current-value application and nearby unidentified controls; `artifacts/color-analysis/rom-excerpts.txt` | `r2 -q -a 8051 -b 8 -e scr.color=0 -c 'pd 60 @ 0x4d54; pd 48 @ 0x51e4; pd 32 @ 0x6cbd' backups/ms2109-maskrom.bin` |
| E-patch | Exact procamp writes in `tools/build_patch.py:34–36` | `sed -n '30,43p' tools/build_patch.py` |
| E-edid | EDID fields and checksum remainders in metadata JSON; default pointer `7738` | Analyzer above; `r2 -q -a 8051 -b 8 -c 'pd 20 @ 0x6176; px 256 @ 0x7738' backups/ms2109-maskrom.bin` |
| E-search | Keyword search, targeted ROM disassembly, startup-table decoding, original overlay inspection | `rg -n -i --no-ignore -g '!.git' -g '*.py' -g '*.c' -g '*.cpp' -g '*.h' -g '*.asm' -g '*.java' 'colorspace|colorimetry|yuv|ycbcr|rgb|gamma|matrix|coeff|601|709|2020|saturat|hue' tools upstream`; disassembly commands above |
| E-reference | MS912x test-pattern conversion and evaluated samples; `artifacts/color-analysis/upstream-testpattern-values.json` | Inspect `upstream/macrosilicon_firmware/tools/ms_testpattern.py:1–50`; evaluate only its `rgb_to_yuv` function, without importing the USB program |
| E-uvc-definitions | Linux UVC enumeration and descriptor layout | Linked primary source above, read 2026-10-05; content_hash n/a |
| E-edid-definitions | Linux EDID field layout | Linked primary source above, read 2026-10-05; content_hash n/a |
| E-datasheet | Manufacturer input/output capability statements, PDF pages 2, 7–8 | Linked manufacturer document above, read 2026-10-05; content_hash n/a |

Generated evidence SHA256:

```text
metadata.json                    f3768ae0689c22609a4fc5329a0c15d6d9d75833fe701e82e8a8d96f733e21ae
rom-excerpts.txt                 19ae7da62b9eb71cdb67cf118f5158a7cb9f417e25ec394f12d7e6aaad5387ad
rom-survey.txt                   a07536bf00db7a5ebc2f2ff631f5bb76eddd7f8f7b7a430ccb13cb82875a188b
upstream-testpattern-values.json 56dd8c31949cc6b45e7d09b2f163594dd87d005135958bc95d89c667de5cabf6
```

The earlier linear disassembly is a navigation aid. In particular, calls to ROM `088A` consume four inline literal bytes; interpreting those bytes as instructions produces misleading branches. Function boundaries and register writes discussed here were checked against the saved bytes and targeted disassembly. This search is not an exhaustive symbolic analysis of every ROM path.

## Path and validation

P-color, path_type=callflow:

1. Establish the saved raw-ROM identity and import-table equivalent — E-rom/E-imports.
2. Walk the configuration templates, associate color descriptors with MJPEG/YUY2, and decode the fields — E-metadata/E-uvc-definitions, F-color-metadata.
3. Trace boot `31F2 → 4D54`, stage-1 patch writes, and current-value application `51E4 → FE90–FE93` — E-procamp/E-patch, F-procamp.
4. Trace default EDID pointer `6189 → 7738 → 6345` and decode its advertisements — E-edid/E-edid-definitions, F-edid.
5. Compare supported RGB/YCbCr input with YUY2 output and inspect MCU configuration paths — E-datasheet/E-search, F-conversion.
6. Separate the MS912x host conversion from MS2109 firmware evidence — E-reference, F-reference-conversion.

Validation completed: all three USB descriptor walks terminate exactly at their declared boundaries; all five recovered color records equal `06 24 0D 01 01 04`; all three processing-unit bitmaps equal `000F`; both EDID checksum remainders are zero. Reference-function sample evaluation used only the extracted function, without loading its USB imports.

Timeline: on 2026-10-05, inspected the saved local sources and ROM, decoded output descriptors and EDID, checked interpretation against primary definitions, traced hardware control writes, and saved this report and reproducible analyzer.

To determine actual conversion behavior, the useful next measurement is a known HDMI source forced separately to RGB and YCbCr, with black/white ramps and primary-color patches captured as raw YUY2. That would distinguish 601/709 matrix behavior, range scaling, clipping, and chroma filtering. A transfer-function measurement requires a controlled ramp. None of those physical checks was performed here.
