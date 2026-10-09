# Connected MS2109 patch report

Date: 2026-10-05, Europe/Warsaw. Report flavor: ordinary firmware reverse engineering.

The attached dongle's EEPROM now contains neutral procamp startup settings and a 48 kHz stereo audio descriptor. Full EEPROM readback matches the generated image. After the user unplugged/replugged the dongle, live HID reads confirmed neutral startup state and macOS captured 48 kHz stereo. The initial audio-sample alignment bug remains unresolved in firmware. Scaler/sharpening bypass is not implemented.

## Scope and tools

See [scope.md](scope.html). The user directly authorized patching this connected dongle. Work used Python ctypes/HIDAPI, radare2 6.2.2 for 8051 disassembly, and FFmpeg/AVFoundation for prepatch capture. IDA is unavailable in the local tool index, so the equivalent firmware survey and disassembly used radare2.

Upstream revisions:

- A-Dunstan/ms2109_stereo_patch: `e92398a13813b753dc4630eb991f455373c03969`.
- BertoldVdb/ms-tools: `967bb582c20cbe33523f3484d0aaf32801d3a4d9`.

## Evidence

| ID | Observation / source reference | Reproduce | SHA256 |
|---|---|---|---|
| E-device | Native IORegistry device `534d:2109`, product `usb video`, location 34865152. HID silicon ID `a7 10 9a`. | `ioreg -p IOUSB -l -w 0`; `python3 tools/ms2109_hid.py inspect` | n/a |
| E-eeprom | `backups/ms2109-original.bin`, 2048 bytes; two complete reads agree. Magic A55A, 1716-byte code, header sum 6688, code sum 20285. | `python3 tools/ms2109_hid.py backup --output /tmp/ms2109-new-backup.bin` (device contents change after flashing) | `37103dccfc6c5e2062b6d22a0a619729449427270e52ae4332fde0da0f49dfe1` |
| E-imports | Raw 8051 EEPROM code + mask ROM; no executable loader metadata, import or export table. Calls to ROM are absolute 8051 addresses. | `r2 -q -a 8051 -b 8 -m 0xcc00 -c 'pd 12' artifacts/original-code.bin` | n/a |
| E-rom | `backups/ms2109-maskrom.bin`, addresses 0000–CBFF. Temporary USB hook and code restored and checked. | Offline: `r2 -q -a 8051 -b 8 -c 's 0x4d54; pd 60; s 0x31ef; pd 6' backups/ms2109-maskrom.bin` | `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8` |
| E-procamp | RAM C6A0: `f5 ff 94 00 00 00 b4 00`; hardware FE90: `f5 94 b4 00`. | Original values retained in `backups/ms2109-original.json`; live `python3 tools/ms2109_hid.py inspect` | n/a |
| E-audio-before | AVFoundation identifies 96000 Hz mono, float32 delivery; `artifacts/audio-before.wav` is a short host capture. | `ffmpeg -hide_banner -f avfoundation -i ':0' -t 1 -vn -c:a pcm_s16le /tmp/ms2109-audio.wav` (audio index may change) | n/a |
| E-tests | All 32 hook stages executed in an independent small opcode interpreter; checksum corruption rejected; PCM correction passes odd-sized chunks. | `python3 -m unittest discover -s tests -v` | n/a |
| E-post | `artifacts/post-reconnect.json`, `artifacts/audio-after.wav`: neutral current/hardware state and macOS 48000 Hz stereo. Captured PCM peaks L=0, R=0. | `python3 tools/ms2109_hid.py inspect`; same FFmpeg command as E-audio-before after reconnect | n/a |
| E-write | Per-byte and complete 2048-byte readback agrees with `artifacts/ms2109-neutral-stereo.bin`; 93 bytes changed, new code length 1804, hook at D2B8, 84 bytes. | Offline compare `artifacts/ms2109-flashed-readback.bin` against `artifacts/ms2109-neutral-stereo.bin`; builder validates both checksums | `060b9c62becaac5da1d89848bb8d27265c16ee74773791e4fd988b08a2d63954` |

## Findings

### F-procamp

- Severity: n/a_re. Evidence: E-rom, E-procamp, E-tests, E-write, E-post.
- Status: implemented and EEPROM-verified; boot verified; optical acceptance pending. Confidence: high for write targets.
- Location: ROM 4D54–4DB3, ROM 31F2–31F7, hook D2B8.
- ROM 4D54 initializes hardware FE90–FE93 to F5/94/B4/00 and copies these into C6A0–C6A7. Current values are little-endian 16-bit; brightness/hue are signed, contrast/saturation nonnegative. ROM subsequently calls firmware stage 1. The patch writes current state and hardware to brightness 0, contrast 128, hue 0, saturation 128 at this stage.
- This is a neutral gain/offset target, not a measured color calibration. No test chart or levels acceptance was performed.
- ROM 4DB4–4E13 returns hard-coded UVC GET_DEF values (-11/148/0/180). Those replies remain unchanged. Apps that reset to GET_DEF can reapply the old values.

### F-stereo

- Severity: n/a_re. Evidence: E-device, E-audio-before, E-tests, E-write, upstream source.
- Status: descriptor patch EEPROM-verified and macOS enumeration verified. Confidence: high for descriptor fields.
- Location: XDATA C4C5 (channels), C4C9–C4CB (24-bit little-endian frequency), firmware stage 2.
- A-Dunstan's entry trampoline is retained: replace initial `MOV DPTR,#DE0B` with `LCALL D2B8`; appended code restores the displaced instruction and returns. It sets channels to 2 and frequency bytes 80/BB/00 to 48000. The existing 16-bit PCM subframe and payload bitrate remain unchanged.

### F-alignment

- Severity: n/a_re. Evidence: upstream patch comments, Linux quirks.c and pcm.c, E-tests.
- Status: host helper synthetically verified; firmware solution and live L/R acceptance unresolved. Confidence: high for documented issue, unmeasured on this signal.
- The stream contains an extra initial 16-bit word. Linux sets `stream_offset_adj=2`, consumes those two bytes once, and preserves subsequent partial-frame continuity. This is framing, not signedness or floating-point interpretation. Sample types do not remove an inserted word.
- `tools/align_pcm.py` implements the documented correction on raw uncorrected S16_LE stereo. It is not a system audio device/driver and is not automatically applied to OBS. CoreAudio can discard or frame initial samples before host delivery. Known left/right signals and coincident impulses are required before applying a correction to that delivery path.

### F-optional

- Severity: n/a_re. Evidence: E-rom and inspected upstream sources.
- Status: unresolved. Confidence: low for bypass register identities.
- No verified MS2109 scaler-bypass or sharpening-disable controls were established. No candidate register writes were made. Matching input/capture dimensions avoids requesting resizing but does not establish scaler bypass.

## Path

P-patch, path_type=callflow:

1. Identify connected chip and double-read original EEPROM — E-device, E-eeprom.
2. Read ROM with temporary RAM hook; restore original state — E-rom, E-imports.
3. Trace ROM procamp initialization followed by stage 1; append neutral-state writes — E-rom, F-procamp.
4. Extend A-Dunstan stage-2 descriptor writes, preserving displaced DPTR instruction — E-tests, F-stereo.
5. Recompute both checksums, execute stage tests, commit 93 changed bytes and verify full image — E-tests, E-write, E-post.
6. User performed physical power cycle; HID returned C6A0 `0000800000008000`, FE90 `00808000`, and audio descriptor `0b2402010202100180bb00`; AVFoundation returned 48000 Hz stereo — E-post, F-procamp, F-stereo.
7. Pending: signal-based color and audio alignment acceptance. The captured signal was silence in both channels, so it cannot establish order or offset.

Residual risks: EEPROM commits are not atomic under power loss; backup is retained. GET_DEF is unchanged. Descriptor verification does not establish sample ordering or video quality.

## Timeline

On 2026-10-05: downloaded pinned base sources; identified dongle; saved two matching EEPROM reads; captured original host audio format; dumped/restored RAM-only ROM reader; generated/tested patch; wrote and fully verified EEPROM; requested physical unplug/replug. User reconnected the dongle; verified live neutral registers and 48 kHz stereo capture. Both channels of the short recording have zero peak (silence), preventing correlation or channel-order measurements.

## Recovery and sources

Exact restore commands and operational limits are in [README.md](../README.html).

- [Requested base patch](https://github.com/A-Dunstan/ms2109_stereo_patch)
- [MS-tools research](https://github.com/BertoldVdb/ms-tools)
- [Procamp EEPROM-hook discussion](https://github.com/BertoldVdb/ms-tools/issues/16)
- [Linux MS2109 stream-offset quirk](https://github.com/torvalds/linux/blob/master/sound/usb/quirks.c)
- [Linux capture offset application](https://github.com/torvalds/linux/blob/master/sound/usb/pcm.c)

## Follow-up: reversed audio channels

E-user-channel-order (2026-10-05): the user reports “the audio channel order is
reversed” after reconnecting the patched dongle. Source: direct user observation;
content hash: n/a. This confirms the channel-order symptom on the user's capture
path, but does not measure relative timing. F-alignment remains unresolved in
firmware; the descriptor patch did not correct channel order.

A later live device enumeration exposed no MS2109 audio/video device, so no new
dongle audio measurement was possible. An index-based capture selected the
MacBook microphone after indices changed; that generated file was removed and
is excluded from evidence. Future capture must select the confirmed dongle by
name and fail when it is absent.

## Live tone identification and correction

E-tone: the user supplied a continuous 1 kHz signal on source left and a signal
with silence gaps on source right. Capture was selected by device name:

```sh
ffmpeg -hide_banner -f avfoundation -i ':usb video' -t 12 -vn -c:a pcm_s16le artifacts/audio-identification.wav
python3 tools/analyze_audio.py artifacts/audio-identification.wav --output artifacts/audio-identification-analysis.json
python3 tools/correct_wav.py artifacts/audio-identification.wav artifacts/audio-identification-corrected.wav
python3 tools/analyze_audio.py artifacts/audio-identification-corrected.wav --output artifacts/audio-identification-corrected-analysis.json
```

The raw capture's channel 0 contains gaps (5.62% of 50 ms windows below 1% of
maximum RMS); channel 1 remains continuous (0% silent windows). Both peak at
3277 S16 units. This establishes reversed channel order against the user-supplied
channel-identification signal. The strongest local lag correlation is
`corr(raw_ch0[n], raw_ch1[n-1]) = 0.99157`, versus 0.98358 at zero lag.

E-tone-corrected: dropping the first 16-bit word from the interleaved recording
puts the continuous signal on left and the gapped signal on right. Strongest
correlation is then at zero lag (0.99158). The correction is
`L[n]=raw_R[n]`, `R[n]=raw_L[n+1]`. It is verified for this capture path.

F-live-alignment: severity n/a_re; evidence E-tone, E-tone-corrected, E-user-channel-order;
status validated for the recorded host signal, not implemented in firmware;
confidence high for order and moderate for attributing the measured phase to
the device (source channel phase was not independently measured).

The AVFoundation recording contains about 8.9 seconds of PCM in a 12-second
wall-clock capture, and global spectral peak is approximately 995 Hz. Capture
continuity/clock accuracy was not qualified by this experiment. Correlation was
measured only in 50 ms windows where both tones were active, excluding edges.
No claims about long-duration audio reliability are made.

E-tone-repeat: a separate four-second capture restarted the audio stream and
reproduced the same result: gapped channel 0, continuous channel 1, strongest
correlation at lag -1 (0.99005 versus 0.98202 at zero lag). Results are saved in
`artifacts/audio-identification-repeat-analysis.json`. This supports a repeatable
half-frame rotation on this path, rather than a single recording's boundary error.

E-causal-filter: FFmpeg `pan=stereo|c0=c1|c1=c0,adelay=1S|0S` was applied to the
measured raw capture. The result has continuous left, gapped right and maximal
local correlation at zero lag (0.99157). Results are stored in
`artifacts/audio-identification-live-filter-analysis.json`. Unlike the WAV
rotation helper, this implementation is causal: left is delayed by one sample
rather than right requiring one sample of lookahead. It is suitable for live
processing on the same uncorrected path, with one sample of shared latency
relative to the lookahead formulation. No firmware update was made.

## Firmware alignment investigation and rejected RAM candidates

The user explicitly requested a device firmware fix and warned that the firmware
may itself be buggy. Host correction does not satisfy that request.

Static evidence from the saved ROM:

- ROM 61A1 selects USB bank 2 through SFR 93, programs A2/A3 to 0100,
  lower CSR 80 to 05, and upper CSR 90 to 70.
- ROM 2CDA sets bank 2 CSR bit 0 on endpoint 2 interrupts. No sample-copy
  loop was identified for this endpoint. The observed path appears hardware driven.
- ROM 67F1 stores audio SET_INTERFACE alternate setting in IRAM 3A;
  no audio sample conversion or FIFO repositioning appears in this routine.
- ROM 3E78 programs FE62..FE67 from input/output sample-rate state and
  sets FE61 bit 0 in one rate-conversion path, bit 3 in the other. Exact
  hardware bit semantics remain inferred.
- FIFO port AD is inferred from ROM accesses to AB for endpoint 0 and AE
  for endpoint 3. Its audio read/write behavior is not qualified.

This does not establish a C signedness bug. There is no identified software
conversion whose data type can simply be changed. Silicon register semantics
and startup packet framing remain unresolved. Linux's current source independently
documents initial alignment and sets a two-byte stream adjustment:
[quirks-table.h](https://github.com/torvalds/linux/blob/master/sound/usb/quirks-table.h),
[quirks.c](https://github.com/torvalds/linux/blob/master/sound/usb/quirks.c).
These are host workarounds, not firmware implementations.

| RAM candidate | Evidence | Result |
|---|---|---|
| A2/A3 0100 to 0102 | `tools/test_audio_endpoint.py`; capture timed out | Rejected; appears packet sizing rather than a FIFO address. Restoring 0100 recovered capture. |
| Read AD twice during capture | `audio-fifo-read2.wav`, JSON and analysis | No channel/lag change. Returned 0000. |
| Insert one zero word through AD | `audio-fifo-insert2.wav`, analysis | No channel/lag change. Lag -1 remains strongest in active quarter-second blocks before and after. |
| Toggle FE61 bit 0 off for 20 ms, then restore | `audio-rate-gate.json`, WAV and analysis | Readback 09 to 08 to 09; no correction. |
| Gate inferred endpoint DMA bit 4 of upper CSR, insert word, set ready, restore CSR | `audio-fifo-dma-insert2.wav`, JSON and analysis | Rejected: poor delivery followed by pipeline stall. No valid corrected tone. |
| Flush lower CSR twice and restore ROM startup CSR 05 | `audio-after-fifo-reset.wav`, analysis | Data delivery resumed, but tone became discontinuous/garbled; not a valid restoration. |

Every temporary common hook was restored to CC00 `12D2B8`. EEPROM was never
written during these experiments. E-probe-restoration:
`artifacts/audio-probe-restoration.json` records a complete EEPROM read matching
the qualified image SHA256 `060b9c62becaac5da1d89848bb8d27265c16ee74773791e4fd988b08a2d63954`,
hook flags 05 and FE61 09.

The user subsequently power-cycled the dongle. E-powercycle-recovery:
`audio-recovered-after-powercycle.wav` and analysis confirm clean approximately
1 kHz tones, with original gapped channel 0 and continuous channel 1. Peak
correlation again occurs at lag -1 (0.99477 versus 0.98670 at zero).
Live startup reads again confirmed neutral procamp and stereo descriptor.
This recovers the known pre-experiment behavior; it does not fix alignment or
qualify delivery continuity (3.189 seconds of PCM in the four-second capture).

At that stage, the next required evidence was raw USB startup packet lengths/content before
CoreAudio framing. `tools/capture_audio_usb.c` is compiled with warnings as
errors and captures endpoint 82 into PCM plus packet CSV, preserving submission
order. It detaches/re-attaches only the targeted 534D:2109 device's audio driver,
which may re-enumerate the entire device on macOS. It makes no EEPROM/RAM writes.
Current live preflight opens the USB device but reports audio driver active;
capture fails with `LIBUSB_ERROR_ACCESS (-3)`. `sudo -n true` reports that a
password is required. Thus packet capture has not run and firmware startup
correction is still unvalidated. macOS capture requires root or an entitlement,
as confirmed by [libusb's Darwin backend](https://github.com/libusb/libusb/blob/master/libusb/os/darwin_usb.c).

### Raw capture tool retry

The user ran the first raw capture with sudo and reported successful driver
reattachment. Its output contains zero PCM bytes and a CSV header only, so no
packets were captured. The tool suppressed transfer-submission errors in its
drain path; the exact USB error was not recorded. Successful reattachment is
not evidence of successful capture.

Read-only live descriptor inspection confirmed high-speed USB, audio interface
3 alternate 1, endpoint 82, isochronous attributes 05, maximum packet size 256
and interval 4 (1 ms). The old capture queued eight 512-packet transfers,
scheduling over four seconds ahead. Revised capture queues eight 64-packet
transfers and reuses them for 4096 packets total, keeping only 512 ms queued.
Excessive advance scheduling is a suspected cause, not a verified diagnosis
of the unrecorded submission error. Every submission/completion failure and
the capture exit/packet count are now printed.

`tests/test_usb_capture_queue.c` exercises the actual callback/queue with mock
USB submissions. It passes out-of-order completion and slot reuse through all
4096 packets, preserves an initial two-byte packet, checks queue bounds and
verifies failed submissions do not increment the pending count. This is
synthetic validation only. The subsequent live retry is described below.

### Successful raw USB capture

The user ran the revised capture with sudo. `audio-usb-start2.log` reports
4096 completed packets, zero failures, and successful driver reattachment.
The PCM file contains 786352 bytes. Packet lengths were 192 bytes for 4061
packets; the remainder were 0 (1), 256 (1), 248 (1), 190 (8), 194 (8),
188 (9), and 196 (7). The first three lengths were 0, 256, 248. Therefore this
capture does not isolate the standalone initial two-byte packet.

`audio-usb-start2.wav` reproduces the reversed order before CoreAudio:
channel 0 has the source's gaps, channel 1 is continuous. Active-tone
correlation peaks at lag -1 (0.999789 versus 0.991212 at zero). The measured
tone is 1000.10 Hz. Half-stereo-frame packet lengths also occur during the
stream, establishing that packet boundaries cannot be assumed to align to
four-byte stereo frames. Changing the host PCM signedness cannot correct
these stream/channel framing problems.

### Mac HDMI source and persistent channel-order correction

The original external audio source was removed. The user connected this
Mac's HDMI output to the dongle. Live system_profiler inspection identified
`HDMI TO USB` as the default stereo HDMI sound output at 48000 Hz.
`mac-hdmi-reference.wav` supplies continuous left 1 kHz, with a 500 ms silence
gap on right every two seconds. Both tones have equal phase when active.

Temporary FE60 tests with a valid reference produced:

| FE60 | USB channel 0 | USB channel 1 |
|---|---|---|
| 10 hex | Gapped right source | Continuous left source |
| 11 hex | Gapped right source | Gapped right source |
| 20 hex | Silence | Continuous left source |
| 01 hex | Continuous left source | Gapped right source |

These observations support interpreting the two nibbles as source channel
selectors. The swap-only retry now requires a non-silent baseline before
writing a candidate and records playback status. Its baseline peak was 3277;
01 hex corrected channel identification, and restoring 10 hex restored the
reversed order. Earlier all-silent trials, including a silent restored
capture, are inconclusive and are not evidence against either setting.

The corrected channel order still has its best correlation at lag -1;
this register does not correct the one-sample offset. CoreAudio captures
also deliver less PCM duration than wall time and do not qualify continuity.

`build_patch.py --channel-order` adds FE60=01 to the existing stage-2 hook.
The 90-byte hook retains neutral procamp and the stereo descriptor. Opcode
execution tests cover all 32 stage values, including the new register write.
The image `ms2109-neutral-stereo-channel-order.bin` was flashed with 15
changed-byte writes against an exact expected-current image, then fully
read back and verified: SHA256
`bd7edac83659f9d20d0b308469a618df58f773ace820c98fc169384ddb8063e2`.
The preceding EEPROM image is preserved as
`backups/ms2109-neutral-stereo-before-channel-order.bin`.
The user power-cycled the dongle. `channel-order-startup-verification.json`
records a matching full EEPROM readback, FE60=01, entry 12D2B8, neutral current
procamp state `0000800000008000`, hardware `00808000`, and stereo descriptor
`0b2402010202100180bb00`. No runtime register writes were used for this check.
`channel-order-startup.wav` then confirmed continuous channel 0 (no silent
50 ms windows) and gapped channel 1 (21.4 percent silent windows). Both peaks
were 3277. Best active-tone correlation remains at lag -1 (0.97710 versus
0.96909 at zero). The capture contains 3.531 seconds of PCM for a four-second
capture and does not establish delivery continuity. Sample alignment remains
unresolved; no scaling or sharpening changes have been applied.
