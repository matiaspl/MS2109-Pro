# Original deep-color EDID advertisement

A reversible baseline–deep-color–baseline comparison on 2026-10-12 used direct display-native RGB patches, fixed B−17/C148/H0/S146, and two stable raw libuvc YUY2 frames per condition. Frames were analyzed in memory; only statistics and metadata were saved.

| Straight-line RMS, codes | Baseline | Original deep-color flags | Baseline repeat |
|---|---:|---:|---:|
| Y | 0.4027345465 | 0.4027345465 | 0.4027345465 |
| Cb | 0.4460672214 | 0.4460672214 | 0.4460672214 |
| Cr | 0.4460672214 | 0.4460672214 | 0.4460672214 |

Every sampled channel mean matched exactly (maximum difference 0 codes). All channel spans remained 253 codes, from 1 to 254, with no new clipping or monotonicity failures.

The RAM candidate changed EDID offset 162 from 0x81 to 0xB9 and offset 255 from 0xBD to 0x85 (checksum). macOS source-visible readback matched the candidate during capture and baseline after restoration. Candidate SHA-256: `502ed39a4eb936d007df71a7087ae2ebe0dea6c47c71abc1eb8dada271b69ac5`. Baseline SHA-256: `07ccaf28aa9524d78d17f26bc80b225e9dc93cffde7e92ab84341d2baf84d26d`. EEPROM remained unchanged during qualification.

Advertising deep color did not change the measured raw response. Actual HDMI wire bit depth was not established; EDID readback does not prove deep-color transport selection.

The release builder now retires the complete 74-byte gate-aware EDID callback at overlay address 0xD349 (EEPROM offset 1913), replacing it with RET and unreachable NOP padding. This removes both EDID writes and gate operations while preserving addresses, overlay length and the other fixes. The code checksum is recalculated. The pinned predecessor remains unchanged for reproducibility. The rebuilt EEPROM image has not been flashed or cold-boot validated.

Local evidence is retained under `artifacts/deep-color-native-20261012/`: captures, source readbacks, candidate byte diff, qualification report and waveform SVG. Exact firmware changes are recorded in `firmware/ms2109-pro.json`.
