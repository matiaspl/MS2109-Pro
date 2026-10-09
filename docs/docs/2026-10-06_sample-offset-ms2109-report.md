# MS2109 sample-offset repair investigation

> Date: 2026-10-06. Analysis: ordinary firmware reverse engineering (`flavor = null`).
> Status: a routed HDMI tone and deterministic wideband reference now produce non-silent native captures. The baseline remains at lag −1. The guarded EP2 reset's occurrence flag was set, but the candidate also remained at −1, so the tested firmware candidate is rejected. No firmware alignment fix is validated; no EEPROM write occurred.
> Reassessment: the probe's `reset_trigger_count` is an occurrence flag, not a counter. An [offline follow-up](2026-10-06_sample-offset-firmware-options.html) fixes a leaked helper return frame in the trace wrapper. The corrected CC10/CC20 trace records ROM event ordering, not the first packet boundary; the signal-backed wideband run confirms that the trace and reset do not correct the phase.

The MS2109 starts its stereo audio stream with a half-frame: the first 16-bit word belongs to the right channel. Linux corrects this by dropping the first two bytes once per stream. Raw USB evidence and new FE60=01 native macOS captures retain the one-sample lag. A deterministic wideband HDMI fixture makes the distinction clear: the reference itself peaks at zero lag, while the live no-hook stream peaks at −1 (`0.978962` versus `0.000458` at zero). The public MS2109 EEPROM firmware source has no audio sample-copy routine, so it does not provide a direct software point for removing that word. The corrected RAM monitor observed alternate setting 1 and set its endpoint-2 reset occurrence flag, but the wideband candidate still peaked at −1 (`0.981998` versus `0.000064` at zero). This polling-reset candidate is rejected; its timing relative to the first packet was not established.

## Scope and target

The authorized target remains the attached `534d:2109` dongle and its saved EEPROM/ROM images, as described in [scope.md](scope.html). The inspected EEPROM image is `artifacts/ms2109-calibrated-stereo-channel-order.bin`, SHA256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`; it contains a 1,950-byte code section with 46 bytes free. Two experimental hooks were installed in RAM and restored after capture. No EEPROM write occurred. A post-test full readback confirmed that the EEPROM and loaded code still match this image.

The public source checkout was pinned at `70434570fdcf6dcf742919826ba98fd9f8614c5d`. Its `crt0_ms2109.asm` is pure 8051 assembly; the EEPROM image and mask ROM have no executable import/export table, and ROM calls use absolute addresses. IDA was unavailable in the local tool index; static inspection used radare2 6.2.2 and the reproducible `rasm2` size audit described below.

## Findings

### F-001 — The defect is a one-time half-frame at stream start

- Severity: `n/a_re`; category: device streaming behavior.
- Evidence: E-002, E-003, E-004.
- Confidence: high. Status: validated for the observed raw USB and macOS paths.
- Location: MS2109 audio stream startup, USB endpoint 82 (endpoint 2).

The raw endpoint capture contains 4,096 packets with no transfer failures. Its first packet lengths are 0, 256 and 248 bytes; lengths of 188, 190, 192, 194 and 196 bytes also occur later. Packet boundaries therefore cannot be treated as stereo-frame boundaries. Correlation of the raw endpoint capture peaks at lag −1 (`0.999789`) rather than zero (`0.991212`). With FE60=01 active, known-tone captures continue to show channel 0 continuous and channel 1 gapped. The original startup capture peaked at lag −1 (`0.977100` versus `0.969087` at zero lag); the corrected-reset baseline peaked at −1 (`0.982316` versus `0.974255` at zero), and its candidate also peaked at −1 (`0.976818` versus `0.968848` at zero; E-008). The new wideband baseline/reset results are sharper and agree with that earlier evidence (E-010).

The upstream Linux ALSA change identifies the same fault as an initial right-channel half-frame and sets a two-byte stream adjustment. Its capture path consumes those bytes once across the incoming stream, rather than dropping two bytes from every USB packet. See the [MS2109 ALSA patch](https://patches.linaro.org/patch/266712/) and the current [ALSA capture path](https://github.com/torvalds/linux/blob/master/sound/usb/pcm.c). This is strong evidence for the required correction semantics, but it does not itself supply a firmware implementation.

### F-002 — The public EEPROM firmware does not contain a sample-processing hook

- Severity: `n/a_re`; category: firmware architecture.
- Evidence: E-001, E-005.
- Confidence: high for the inspected source and ROM paths; this does not prove the silicon has no undocumented control.
- Status: candidate finding; no safe firmware data-path patch point is verified.
- Location: `upstream/macrosilicon_firmware/ms2109/eeprom/crt0_ms2109.asm`; ROM routines around `0x61A1`, `0x2CDA`, and `0x67F1`.

The pinned EEPROM source reconstructs command, video, and initialization hooks but contains no audio sample-copy or PCM packetizer routine. The ROM setup at `0x61A1` programs endpoint 2 registers; the ROM path at `0x67F1` stores interface 3's alternate setting in IRAM `0x3A`. Endpoint 2 appears hardware-driven in the available disassembly. The previous RAM experiments with endpoint address adjustment, FIFO reads/insertion, FE61 rate gating and a mid-stream FIFO reset did not correct alignment; DMA-gated insertion and mid-stream reset disrupted delivery. Their outcomes are recorded in the [earlier investigation](2026-10-05_reverse-ms2109-report.html).

The radare2 assembly-size audit produces 1,983 bytes for the pinned source, against a maximum code payload of 1,996 bytes in a 2 KB EEPROM image. That leaves 13 bytes if used as a standalone image, while replacing the current calibrated image would also replace its already-qualified settings. This is a size/layout comparison using `rasm2`, not a verified SDAS8051 target build or a drop-in firmware image.

### F-003 — The tested polling-reset candidate did not correct alignment

- Severity: `n/a_re`; category: experiment.
- Evidence: E-005, E-007, E-008.
- Confidence: high that this tested implementation did not correct the observed Mac capture; count and first-packet timing were not measured.
- Status: rejected; do not integrate this reset candidate.
- Location: normal-hook main-loop observation of IRAM `0x3A`; endpoint 2 bank 2, CSR `0x80`.

The first probe placed its IRAM `0x3A` monitor after the mailbox idle return, so normal main-loop calls skipped it. That control-flow error explains its occurrence flag of zero. The corrected 199-byte probe polls before the mailbox path and, when armed and observing IRAM `0x3A` equal to 1 with its latch clear, selects endpoint bank 2 and writes CSR `0x80` as `0x0D`, `0x0D`, then `0x05`. It restored its temporary code, hook, and mailbox. The corrected probe reached this path at least once and kept the expected channel order, but the strongest correlation remained at lag −1 rather than zero. The telemetry writes a constant 1, and the latch can re-arm after another alternate-setting transition; exact count and timing before the first packet are unproven. CSR semantics remain inferred. Do not integrate this candidate into EEPROM firmware, but do not generalize its failure to all producer-start or phase-reset mechanisms.

## Evidence

### E-001 — Pinned public firmware size and entry audit

- Observed: 2026-10-06.
- Source: `upstream/macrosilicon_firmware/ms2109/eeprom/crt0_ms2109.asm`, commit `70434570fdcf6dcf742919826ba98fd9f8614c5d`.
- Content SHA256: `9a90c6f23d1e80114ce1bd187867e24207845b0005e7f0808e48e769e7f2b962`.
- Reproduction: `rtk proxy python3 -B tools/audit_upstream_firmware.py --reference-image backups/ms2109-original.bin --reference-image artifacts/ms2109-calibrated-stereo-channel-order.bin`
- Result: 1,983 assembled bytes; 1,996-byte maximum; 13 bytes free standalone. Current image: 1,950 code bytes; 46 bytes free. The script itself has SHA256 `0fbc277a21d77fc2d558c8f7ec5368d45dd7518a75457f1a2384f0927100b57d`.

### E-002 — Raw USB capture before CoreAudio framing

- Observed: 2026-10-05.
- Source: `artifacts/audio-usb-start2.pcm`, `artifacts/audio-usb-start2-packets.csv`, and `artifacts/audio-usb-start2-analysis.json`.
- Content SHA256: PCM `0164980d3f6580e2b83774b907d25f36718f0a41c9639df8e745293baf5b37af`; packet CSV `5391f3dd07b45f8b28dc61361cc9422a41558f9b02778e614d5292eefe3604f6`; analysis JSON `1bad71c4d26d7389367e5a0074e4a10f4e5289ebd643fd66325844a4f1b661b7`.
- Reproduction: `rtk proxy python3 -B tools/analyze_audio.py artifacts/audio-usb-start2.wav --output artifacts/audio-usb-start2-analysis.json`
- Result: 4,096 completed endpoint packets, zero failures, 786,352 PCM bytes, peak lag −1. The capture predates FE60=01; it establishes the raw stream framing and lag, not the later channel-selector state.

### E-003 — Lag remains after the qualified channel-order setting

- Observed: 2026-10-06.
- Source: `artifacts/channel-order-startup.wav` and `artifacts/channel-order-startup.analysis.json`.
- Content SHA256: WAV `6367ad8bcadc57c0925b1a710a42bbfd352a437ad98795b4da44cef02a161ea4`; analysis JSON `b39a79c8467e1f241eb73558d1d61e1151638f78470e72ef61d7b732dbc495d7`.
- Result: 48 kHz, FE60=01, continuous channel 0, gapped channel 1; peak lag −1 at `0.977100`, compared with zero-lag `0.969087`.

### E-004 — Linux documents and implements the two-byte stream correction

- Source: Hector Martin's [ALSA MS2109 patch](https://patches.linaro.org/patch/266712/) and the upstream Linux [`pcm.c`](https://github.com/torvalds/linux/blob/master/sound/usb/pcm.c).
- Content hash: n/a (public source reviewed online).
- Observation: the patch sets a two-byte stream offset for `534d:2109`; the capture routine consumes the adjustment from the beginning of the stream across isochronous packets.
- Reproduction: inspect the linked patch and `retire_capture_urb()` in `sound/usb/pcm.c`.

### E-005 — ROM endpoint and alternate-setting routines

- Source: `backups/ms2109-maskrom.bin`, SHA256 `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`.
- Reproduction: `rtk proxy r2 -q -a 8051 -b 8 -m 0x0000 -c 's 0x61a1; pd 24; s 0x2cda; pd 18; s 0x67f1; pd 24' backups/ms2109-maskrom.bin`
- Observation: `0x61A1` sets up USB endpoint banks and CSRs; `0x67F1` copies the audio alternate-setting value to IRAM `0x3A`. This is static evidence only; register semantics remain partly inferred.

### E-006 — Initial HDMI stimulus preflight was unavailable

- Observed: 2026-10-06.
- Source: `system_profiler SPAudioDataType -json` output from this pass.
- Content hash: n/a.
- Result: the `SPAudioDataType` `_items` list was empty at the initial preflight, so that attempt was paused. After the user reconnected the audio route, E-008 records a successful baseline and candidate run.

### E-007 — RAM candidate control flow and offline tests

- Source: `tools/audio_ram_probe.py`, `tools/test_audio_stream_start_reset.py`, and `tests/test_audio_ram_probe_code.py`.
- First candidate hook SHA256: `69ffc5bb327a7a93b8964e57dda9681a1dd86c15ca6e3de10af0975d80c10b68` (199 bytes).
- Result: the original hook placed the stream monitor after the mailbox idle return. The monitor did not run; the occurrence flag was 0 and lag remained −1. The initial 13 offline tests checked branch bounds but missed that reachability defect.

### E-008 — Corrected RAM monitor triggers, but the reset does not align audio

- Observed: 2026-10-06, after the user's HDMI reconnection.
- Source: `artifacts/audio-stream-start-reset-attempt2-baseline.wav`, `artifacts/audio-stream-start-reset-attempt2-candidate.wav`, both analysis files, and `artifacts/audio-stream-start-reset-attempt2-candidate.json`.
- Content SHA256: baseline `a5551fb9d9ad6d9aa83483d9ee8d63a321e87b9a55455ada644c4813779074b6`; candidate `ef9ca46d9c104694395e9378835cf24def5d38515e343e3463feeeb271170141`; hook `8fe6492a562e843fbaceeeb06c5d2ab45e4d754d4d620a585e1ba3d78fd0b7b8`.
- Reproduction: `python3 tools/test_audio_stream_start_reset.py --experiment --run-id attempt2`; offline checks: `python3 -B -m unittest discover -s tests -v`.
- Result: the baseline reproduced lag −1 at correlation `0.982316` (zero lag `0.974255`). The corrected monitor's occurrence flag was 1, proving execution at least once; its historical `reset_trigger_count` label overstates the measurement. Candidate lag remained −1 at `0.976818` (zero lag `0.968848`), channel order remained correct, and rate was 48 kHz. The guarded test exited 2 as designed. Candidate/baseline WAV durations were about 7 seconds; full delivery continuity was not qualified. The hook was restored; no EEPROM write occurred.

### E-009 — Post-experiment firmware and EEPROM unchanged

- Observed: 2026-10-06, immediately after E-008.
- Source: `artifacts/audio-stream-start-reset-attempt2-post-check.json`.
- Reproduction: `python3 tools/verify_color_startup.py --image artifacts/ms2109-calibrated-stereo-channel-order.bin --output artifacts/audio-stream-start-reset-attempt2-post-check.json`.
- Result: complete EEPROM read matched the expected SHA256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`; the loaded header and all 1,950 code bytes matched. The calibrated controls, BT.709 descriptors, and FE60=01 remained active.

### E-010 — Signal-backed traces and wideband reset candidate retain lag −1

- Observed: 2026-10-06.
- Source: `artifacts/audio-prbs-reference-20261006.wav` and generator metadata; `artifacts/audio-reference-capture-20261006-01.*`; `artifacts/audio-usb-hook-trace-pass5.*`; `artifacts/audio-stream-start-reset-prbs20261006-*`.
- Fixture: deterministic 48 kHz S16 stereo xorshift32 sequence, seed `0x21090001`, peak amplitude 3200. Both channels carry identical wideband samples while the right channel is silent for the first 0.5 seconds of each 2-second period. The fixture has correlation 1.000 at zero lag and approximately zero at adjacent lags.
- Reproduction: `python3 -B tools/generate_audio_prbs_reference.py`, then `python3 -B tools/test_audio_stream_start_reset.py --experiment --seconds 8 --run-id <unique-id> --reference artifacts/audio-prbs-reference-20261006.wav`.
- Result: the no-hook AVFoundation baseline peaked at lag −1 (`0.978962`) versus `0.000458` at zero. The reset occurrence flag read 1, confirming the path was reached but not an exact trigger count; the candidate peaked at −1 (`0.981998`) versus `0.000064` at zero. Both captures retained continuous left and gated right channels. The signal-backed pass-through CC10/CC20 trace with the 1 kHz fixture also remained at −1. The test rejected the candidate (exit 2); all temporary RAM code was restored. These new captures are native AVFoundation; raw endpoint 82 was not reacquired with this fixture because the helper requires root or a USB capture entitlement.

### E-011 — Post-wideband-test firmware and EEPROM unchanged

- Observed: 2026-10-06, immediately after E-010.
- Source: `artifacts/audio-stream-start-reset-prbs20261006-post-check.json`.
- Reproduction: `python3 -B tools/verify_color_startup.py --image artifacts/ms2109-calibrated-stereo-channel-order.bin --output artifacts/audio-stream-start-reset-prbs20261006-post-check.json`.
- Result: complete EEPROM, loaded header, and all 1,950 code bytes match SHA256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`; FE60, procamp, and video descriptors remain at the calibrated values.

## Path

### P-001 — Audio startup and rejected RAM-only reset

- `path_type=callflow`; start: host selects audio interface 3, alternate setting 1; goal: aligned two-channel PCM without a host-side trim.
1. The ROM records the selected audio alternate setting in IRAM `0x3A` — E-005, F-002.
2. Endpoint 82 emits isochronous PCM; captured data shows the initial half-frame and a one-sample peak lag — E-002, E-003, F-001.
3. Linux drops two bytes once at stream start to restore stereo-frame phase — E-004, F-001.
4. The corrected opt-in reset experiment observed alternate setting 1 and reached its EP2 reset path, but both tone and wideband candidates remained at lag −1 — E-008, E-010, F-003.
5. The corrected pass-through trace logged EP2 service before `SET_INTERFACE` alt 1 and after alt 1/alt 0. With a routed tone, it captured non-silent PCM but still did not alter the lag — E-108, E-010.
- Residual risks: endpoint CSR semantics, exact reset count, the first-packet boundary, and the hardware data path remain unresolved; no firmware alignment correction is validated. No EEPROM image contains the trace candidate.

## Reproduction and next step

Run offline checks from the repository root:

```sh
python3 -B tools/audit_upstream_firmware.py --reference-image backups/ms2109-original.bin --reference-image artifacts/ms2109-calibrated-stereo-channel-order.bin
python3 -B -m unittest discover -s tests -v
```

The guarded test requires a unique `--run-id` for each output set. E-010 records a fresh wideband baseline/candidate pair; its zero-lag discriminator confirms the candidate remained at −1 even though the reset occurrence flag was set. Do not promote this reset candidate into EEPROM. The [firmware-options reassessment](2026-10-06_sample-offset-firmware-options.html) records the corrected event-order trace and the remaining need to identify a verified producer/FIFO boundary before proposing another firmware correction.

## Timeline

- 2026-10-05 — Captured endpoint 82 before CoreAudio framing; packet lengths split stereo frames and correlation peaked at lag −1.
- 2026-10-05 — Qualified FE60=01 for channel order; the one-sample lag remained.
- 2026-10-06 — Pinned and audited the public MS2109 source; no audio sample-processing routine was found, and the full source size leaves little standalone EEPROM space.
- 2026-10-06 — The first RAM probe exposed a missed monitor due to its placement after the mailbox idle return. Moving it before that return allowed the reset path to execute, but lag remained −1; the calibrated EEPROM and loaded code were verified unchanged.
- 2026-10-06 — Offline reassessment corrected the count claim: `DE2C=1` is an occurrence flag. USB-request and pre-EP2-ready IRQ hooks provide additional investigation points, documented in the linked follow-up.
- 2026-10-06 — A hook-free AVFoundation capture succeeded but contained digital silence. Two RAM-only trace attempts stalled; after each user replug, complete EEPROM and loaded-code readbacks matched the calibrated image.
- 2026-10-06 — Offline instruction-level replay found the CC10 helper return-frame leak. After replacing its tail jump with `RET`, CC10-only and CC10/CC20 traces completed and recorded alternate-setting/EP2 service order.
- 2026-10-06 — Initial pass-3/pass-4 trace WAVs were silent; a 1 kHz HDMI fixture later reached the dongle and pass 5 captured the expected interface/EP2 event sequence at lag −1.
- 2026-10-06 — A deterministic wideband baseline and reset-candidate capture both peaked sharply at lag −1; the occurrence flag was set but did not align the channels. Full EEPROM and loaded-code readback passed; no sample-offset firmware fix is validated.
