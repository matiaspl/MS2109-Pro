# Remaining firmware routes for MS2109 sample alignment

> Date: 2026-10-06. Analysis: ordinary firmware reverse engineering (`flavor = null`).
> Scope: saved ROM/EEPROM analysis, temporary RAM-only traces, and guarded startup-reset tests. No EEPROM writes.
> Result: the first two traces stalled because the `SET_INTERFACE` handler leaked a return address. After fixing it, both trace modes completed and restored their hooks. A routed 1 kHz reference and a deterministic wideband fixture produced non-silent 48 kHz captures. The EP2 reset occurrence flag was set, but the wideband lag remained −1 sample; no firmware alignment fix is validated. Full EEPROM and loaded-code readbacks match the saved image.

Firmware correction remains possible in principle, but the current evidence does not establish a usable sample-control point. The one-shot reset test now runs against a deterministic wideband signal and still peaks at −1, so that candidate is rejected. The saved ROM supports an optional USB-request hook at `CC10`, and its `CC20` interrupt hook runs before the ROM re-arms endpoint 2. Those are investigation points only; neither proves that the CPU can discard or prepend an audio word.

## Findings

### F-101 — The ROM can intercept SET_INTERFACE before stock request handling

- Evidence: E-101, E-102, E-105, E-106, E-107, E-108, E-109. Confidence: high for the saved ROM and the corrected RAM wrapper. The first candidate had a stack leak; the corrected wrapper passed live AVFoundation captures and recorded interface events while a known signal was present. The trace itself is pass-through and did not correct sample phase.
- Location: ROM `4788–4799`, overlay `CC10`, header flag `CBD4.1`.

At `4788`, the ROM tests bit 1 of `XDATA[CBD4]`. If set, it calls `CC10`; otherwise it calls the stock USB request dispatcher at `2AD0`. The current image's flags are `05`, so this USB hook is disabled. A wrapper can inspect the parsed request, then call or tail-jump to `2AD0` to preserve normal control-request processing, including HID access.

The parser at `58C8` stores the setup fields as follows:

| IRAM | Field |
| --- | --- |
| `0B` | bmRequestType |
| `0C` | bRequest |
| `0D:0E` | wValue, high byte then low byte |
| `0F:10` | wIndex, high byte then low byte |
| `11:12` | wLength, high byte then low byte |

For standard `SET_INTERFACE`, the request switch selects `2B2B`, which calls `67F1`. For interface 3, that routine copies `0E` to `3A` and sets bit `16` (IRAM `22.6`). Common completion at `2B9D` consumes that flag and writes the EP0 status bit. Thus `CC10` is earlier than the stock handler's status write. It is not yet a verified audio-DMA start boundary.

**The address is already occupied.** The current overlay uses `CC10–CC1E` for a 15-byte video callback, and its video command path tail-jumps there at `D11E`. Simply enabling `CBD4.1` would run that callback for USB requests. The wrapper checks the exact return address from the ROM's `LCALL CC10` (`4792`); the video's tail jump retains a different caller and goes to a copied callback. For matching setup requests it records telemetry, then delegates to the stock dispatcher at `2AD0`. The original wrapper leaked its `LCALL record_set_interface` frame because that helper jumped into register restoration instead of returning. The corrected helper now returns; offline instruction-level tests cover its stack discipline and both request/video paths, and the corrected wrapper passed live capture startup and teardown.

### F-102 — The USB IRQ hook precedes the EP2-ready write

- Evidence: E-101. Confidence: high for instruction order; endpoint register semantics are partly inferred.
- Location: ROM `2CA4–2CDF`, hook `CC20`.

The interrupt routine snapshots SFR `9C`, `96`, and `97` into IRAM `33`, `32`, and `34`. It then calls `CC20` when `CBD4.2` is set. Later, `IRAM[32].2` gates selection of endpoint bank 2 and `SETB 80.0` at `2CDD`. This places the hook before that re-arm operation. Endpoint initialization also sets the ready bit, so this is not automatically the first-packet boundary.

A trace extension must preserve the current video IRQ behavior, register state, and these status snapshots. Reading an audio FIFO to inspect it may consume data; logging existing IRQ snapshots avoids that ambiguity.

### F-103 — Earlier telemetry proves execution, not an exact count or startup timing

- Evidence: E-103. Confidence: high.
- Location: historical attempt-2 hook at `D42A`; `tools/audio_ram_probe.py`.

The probe writes `1` to `DE2C`; it does not increment a counter. It also clears its transition latch when alternate setting is not 1, allowing another trigger, and can trigger when armed while alternate setting is already 1. Historical JSON calls the value `reset_trigger_count`, but it is an occurrence flag. The observed value proves the reset path was reached at least once. It does not prove exactly one reset or a reset before the first audio packet.

The captured lag of −1 remains valid negative evidence for the tested polling implementation. The wideband replay confirms that the reset path is reached without changing the phase (E-109). This rejects that reset candidate, but does not rule out a producer-side word skip or serializer phase control that has not been identified. Historical binaries, capture files, and JSON are preserved.

### F-104 — Endpoint sizing is more likely than a movable sample pointer

- Evidence: E-101, E-104. Confidence: inference, not a verified MS2109 register specification.

Endpoint setup writes `A2:A3` as `00:01` for EP2, `00:14` for EP3, and `00:04` for EP4. Those values resemble USB maximum-packet fields (`0100`, `1400`, `0400`) rather than RAM pointers. High CSR `90=70` for EP2 also resembles MUSB's DMA-enable, transmit-mode, and isochronous bits. The earlier A2/A3 adjustment therefore did not establish a two-byte DMA-source advance.

The [Linux MUSB register definitions](https://github.com/torvalds/linux/blob/master/drivers/usb/musb/musb_regs.h) support this comparison: TXCSR includes DMAENAB `1000`, MODE `2000`, ISO `4000`, FLUSHFIFO `0008`, and FIFONOTEMPTY `0002`. This is evidence for a hypothesis, not permission to apply a different chip's register writes. CPU reads from a transmit FIFO also need not discard data from its USB transmit side.

## Candidate corrections

The stock-routing model documented by the [Linux MS2109 patch](https://patches.linaro.org/patch/266712/) is:

```text
Uncorrected words:  R(-1), L0, R0, L1, R1, L2, R2, ...
Drop first word:          [L0, R0] [L1, R1] [L2, R2] ...
Prepend one word: [0, R(-1)] [L0, R0] [L1, R1] [L2, R2] ...
```

| Route | What would make it work | What remains unknown |
| --- | --- | --- |
| Prepend one 16-bit dummy word | Insert it before the first DMA payload and transmit it as part of the continuous stream; alignment follows after one partly invalid stereo frame | Whether CPU FIFO writes coexist with DMA, survive its start, and fit the first packet without overflow or an isolated short packet |
| Discard the orphan word at the producer | Advance or inhibit the actual PCM producer by exactly one word before USB framing | No source pointer, word-skip control, or CPU-readable PCM path is verified |
| Reset the serializer's channel phase | Restart the audio producer in a known left-first phase | The relevant reset/lane-phase control has not been identified; FE60/FE61 names and proximity are insufficient |
| Firmware packetizer | Maintain continuous word/frame state and emit aligned PCM | CPU access to samples, buffering, and timing at 192 kB/s are unproven |

The dummy-word route is worth testing first if a clean producer boundary can be established. It needs no steady-state sample copying. Earlier midstream insertion did not test this initial condition, but its delivery failures mean DMA/FIFO ownership must be established first. A request hook alone cannot guarantee that the producer has stopped or the FIFO is empty.

**Channel routing must be tested together with phase.** FE60=`01` is the current channel-order workaround. Adding or removing one word changes pairing, so a successful phase correction may require restoring stock FE60=`10` or otherwise adjusting routing. Holding FE60=`01` fixed could leave a phase-corrected stream with reversed channels. The word diagram above assumes stock routing.

Packet boundaries remain irrelevant to stereo-frame alignment: apply a correction once at the established stream start, not once per USB packet. Linux's existing two-byte workaround must be disabled or accounted for when testing firmware that already corrects this fault.

## Next steps

1. **Correlate raw USB with the known fixture:** the 1 kHz and wideband references now reach the dongle, and the wideband native capture confirms lag −1 before and after the reset candidate. Compare endpoint 82 bytes from the same fixture to the native PCM to confirm the fault remains upstream of CoreAudio in this exact run. This was not repeated here: the macOS helper detaches the USB driver and requires root or a USB capture entitlement. [E-109]
2. **Relate the events to packet samples:** the combined trace logs one EP2-ready observation before any `SET_INTERFACE`, one after alt 1, then another after alt 0. These are ROM service observations, not guaranteed DMA boundaries or direct packet timestamps. The trace does not identify which observation precedes the first sample. [F-102, E-108, E-109]
3. **Prove control of one word:** only after finding a known producer/FIFO boundary, test initial dummy-word priming or an identified producer-side discard. Do not mark TX-ready before real payload is available. Verify that the correction happens once, does not recur on ordinary packets, and is re-armed only for an established new stream. [F-104]
4. **Qualify the result:** require zero interchannel lag and correct independent channel labels on raw USB and native macOS, plus continuous delivery over repeated starts, power cycles, and HDMI reconnects. Test FE60 jointly. Preserve the calibrated video behavior and rollback path. Linux requires separate handling of its existing adjustment.
5. **Then fit the persistent patch:** the current image has 46 free code bytes, but relocating/reusing routines or reclaiming space is an implementation issue after RAM feasibility. The full public EEPROM source's size is not a fundamental barrier to a compact startup patch.

The corrected trace now has a non-silent reference capture, but it is only a pass-through trace. The startup-reset candidate also retained lag −1 with a one-sample-wideband discriminator. No firmware correction was applied. A producer-side pointer, FIFO priming boundary, or serializer phase control still needs direct evidence before another firmware experiment or persistent patch.

## Evidence and reproduction

- **E-101:** `backups/ms2109-maskrom.bin`, SHA256 `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`. Disassembled as 8051 using radare2 6.2.2. Exact hook, dispatch, alternate-setting, completion, and EP2 signatures are checked by the audit below.
- **E-102:** `artifacts/ms2109-calibrated-stereo-channel-order.bin`, SHA256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. Header flags `05`; the audit checks the existing callback and video caller bytes. The independent local reference `upstream/ms2109_stereo_patch/MS2109_stereo_fix.cpp` also labels bit 1 as a possible USB-command hook; the saved ROM provides the direct confirmation.
- **E-103:** `artifacts/audio-stream-start-reset-attempt2-hook.bin`, SHA256 `8fe6492a562e843fbaceeeb06c5d2ab45e4d754d4d620a585e1ba3d78fd0b7b8`. At `D42A`, bytes `90 DE 2C 74 01 F0` store a constant 1. Captures and outcomes remain in [the earlier report](2026-10-06_sample-offset-ms2109-report.md#e-008--corrected-ram-monitor-triggers-but-the-reset-does-not-align-audio).
- **E-104:** Linux's primary MUSB register header, linked above; used only for comparative register interpretation. This is not an MS2109 datasheet.
- **E-105:** `artifacts/audio-usb-hook-trace-pass1.json`, `artifacts/audio-usb-hook-trace-pass1-reconnect-baseline.wav`, `artifacts/audio-usb-hook-trace-pass1-reconnect-baseline-analysis.json`, and `artifacts/audio-usb-hook-trace-pass1-replug-check.json`. The unhooked AVFoundation baseline completed with 48 kHz stereo PCM (1.712 seconds written from a 2-second request), but the PCM was digital silence. The pass-1 RAM candidate enabled both `CC10` and the experimental `CC20` wrapper; capture timed out after 26 seconds, then HID restoration timed out. After the user reconnected the dongle, full EEPROM, loaded-header/code, calibrated-control, and FE60 checks passed.
- **E-106:** `artifacts/audio-usb-hook-trace-pass2.json` and `artifacts/audio-usb-hook-trace-pass2-replug-check.json`. This pass enabled the `CC10` wrapper only and left the existing `CC20` vector, code, and flag unchanged. AVFoundation again timed out after 26 seconds; HID restoration timed out. After the user reconnected the dongle, the full EEPROM and loaded-code checks passed. No WAV, event log, or offset measurement was produced.
- **E-107:** `tools/test_audio_usb_hook_trace.py` and `tests/test_audio_usb_hook_execution.py`. Instruction-level replay identified the stack leak: `SET_INTERFACE` branches used `LCALL record_set_interface`, while that helper jumped directly to dispatch and left its return address on the stack. The resulting pops shifted caller state and corrupted the return path. The helper now executes `RET`; tests verify alt-1 logging and stock dispatch, ordinary USB dispatch, relocated-video callback return, and both IRQ event paths. These tests stub ROM routines and do not emulate the MS2109 peripherals.
- **E-108:** `artifacts/audio-usb-hook-trace-pass3.json`, `artifacts/audio-usb-hook-trace-pass3.wav`, `artifacts/audio-usb-hook-trace-pass3-analysis.json`, `artifacts/audio-usb-hook-trace-pass3-post-check.json`, `artifacts/audio-usb-hook-trace-pass4.json`, `artifacts/audio-usb-hook-trace-pass4.wav`, `artifacts/audio-usb-hook-trace-pass4-analysis.json`, and `artifacts/audio-usb-hook-trace-pass4-post-check.json`. The corrected CC10-only capture and combined CC10/CC20 capture both completed six-second AVFoundation sessions and logged events. Pass 4 order: EP2 event `0x21` before any interface request, `SET_INTERFACE` alt 1 (`0x11`), EP2 event `0x22`, alt 0 (`0x10`), then another `0x22`. The baseline and both trace WAV analyses show 100% silent windows and undefined lag correlation. Full EEPROM and loaded-code readbacks after each run match the calibrated image.
- **E-109:** `artifacts/audio-prbs-reference-20261006.wav` and its generator/analysis metadata, `artifacts/audio-reference-capture-20261006-01.*`, `artifacts/audio-usb-hook-trace-pass5.*`, `artifacts/audio-stream-start-reset-prbs20261006-*`, and `artifacts/audio-stream-start-reset-prbs20261006-post-check.json`. The generated 48 kHz wideband reference has identical pseudo-random samples in both channels while the right channel is gated for 0.5 seconds every 2 seconds; the reference itself correlates at exactly 0 lag. On the live no-hook baseline, peak correlation was `0.978962` at −1 and `0.000458` at 0. The reset occurrence flag read 1, confirming the path was reached but not an exact trigger count; peak correlation was `0.981998` at −1 and `0.000064` at 0. Channel continuity/gating passed. The earlier 1 kHz fixture also measured −1 on the baseline and signal-backed CC10/CC20 pass-through trace. Full post-test EEPROM/header/code and calibrated-control checks match the installed image.

Run from the repository root:

```sh
python3 -B tools/audit_audio_usb_hooks.py
```

The script checks artifact hashes and 12 exact byte signatures. It does not import the device driver or open hardware. Its saved result is [audio-usb-hook-audit.json](../artifacts/audio-usb-hook-audit.json). Passing it validates the inspected bytes and the historical flag write, not a firmware fix.

The two stalled runs and the corrected successful runs are recorded in [pass 1](../artifacts/audio-usb-hook-trace-pass1.json), [pass 2](../artifacts/audio-usb-hook-trace-pass2.json), [pass 3](../artifacts/audio-usb-hook-trace-pass3.json), and [pass 4](../artifacts/audio-usb-hook-trace-pass4.json), with post-run firmware checks alongside. The offline assembler and instruction-level checks are:

```sh
python3 -B tools/test_audio_usb_hook_trace.py --audit
python3 -B -m unittest tests.test_audio_usb_hook_execution -v
```

The hook-free baseline and corrected pass-3/pass-4 captures completed. Pass 1 and pass 2 stalled because the first `CC10` wrapper leaked the helper's `LCALL` return frame. The instruction-level regression tests verified the correction before pass 3. Pass 5 then captured the 1 kHz fixture under both hooks and recorded the expected event order. The deterministic wideband baseline and reset candidate both completed; the occurrence flag was set and the peak stayed at −1. Temporary RAM writes were restored, and the post-check confirmed the calibrated EEPROM and loaded code. No EEPROM write occurred.

## Timeline

- 2026-10-06 — Rechecked the earlier negative result; identified the occurrence-flag limitation.
- 2026-10-06 — Verified the optional `CC10` request hook and its conflict with the current video callback.
- 2026-10-06 — Verified that `CC20` precedes the ROM's EP2-ready write; assembled and disassembled a pass-through RAM trace candidate.
- 2026-10-06 — Offline instruction-level replay found and fixed the `SET_INTERFACE` helper's leaked return frame; 16 offline tests passed.
- 2026-10-06 — Corrected CC10-only and CC10-plus-CC20 captures completed. The combined trace observed EP2 events before interface setup, after alt 1, and after alt 0.
- 2026-10-06 — Pass 3 and pass 4 were silent; pass 5 used the routed 1 kHz reference and reproduced lag −1 while logging the same five events.
- 2026-10-06 — A deterministic wideband baseline and RAM-reset candidate both captured cleanly. The reset occurrence flag was set but the candidate retained the sharp −1 peak; the full EEPROM and loaded-code readback passed.
