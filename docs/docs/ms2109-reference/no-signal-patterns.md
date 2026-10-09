# No-signal bars and synthetic audio

6 October 2026. Static analysis of the saved ROM, factory overlay and calibrated EEPROM, combined with the bounded live F92C probe documented below.

## Live follow-up

The [F92C experiment](../2026-10-06_no-signal-f92c-report.html) was repeated after explicit confirmation that HDMI was physically unplugged. F92C=20 and 30 both read back correctly and produced identical black native YUY2 frames; register restoration, unchanged EEPROM and video recovery after HDMI reconnection were verified. The earlier run was invalidated because HDMI had remained connected. The valid repeat shows that changing F92C alone did not make bars appear in the tested AVFoundation YUY2 path; it does not rule out another capture format or an initialization-time dependency.

The follow-up [FEBA sweep](../2026-10-06_ms2109-feba-pattern-sweep-report.html) resolved the main selector: FEBA=00 gives black and FEBA=08 gives SMPTE-like color bars in the same no-signal YUY2 path. All values 00–1F were tested and documented. This directly supports the user's observation that EEPROM startup code changed the no-signal output: the installed image leaves FEBA at 00, whereas the upstream reconstruction writes 08.

A separate [signal-on test](../2026-10-06_ms2109-feba-signal-on-report.html) confirms FEBA=08 does not overlay bars on a valid HDMI picture. FEBA remained 08 through capture, while the active picture stayed pixel-identical to baseline. This indicates that FEBA chooses the no-signal fallback pattern; a separate force-pattern path has not been identified.

## What is known about the bars

XDATA **FEBA bits 4:0** are experimentally confirmed as a no-signal pattern selector on this board. The observed map is in the [sweep report](../2026-10-06_ms2109-feba-pattern-sweep-report.html). F92C remains a video-init setting; changing only bit 4 from 20 to 30 did not change black output with FEBA=00.

| Path | Verified instruction behavior | Interpretation limit |
|---|---|---|
| ROM 3F59 → 6F5B | Writes F92C = 30 | Part of video initialization; does not by itself prove bars enabled/disabled |
| Factory overlay D08B | Writes F92C = 20 | Handler D082 serves normal commands 01 and 0B |
| Factory overlay D091 | Writes E33C–E33F = F5 0F 00 00 | Adjacent configuration; not demonstrated palette or pixel data |
| ROM 3F66 → 6EED | R7=0; masked write clears FEBA bits 4:0, preserving bits 7:5 | Live sweep confirms the low field changes the internal no-signal pattern |
| Installed calibrated EEPROM, command 01 | Writes F92C = 20, then continues with FE20 / helper / C697 setup | Differs from the ROM's F92C=30; no FEBA write in this handler |
| Installed calibrated EEPROM, command 0B | Writes F92C = 20 and E33C–E33F = F5 0F 00 00 | No FEBA write in this handler |
| Upstream custom assembly, commands 01 and 0B | Also writes FEBA = 08; labels F92C=20 and FEBA=08 as color-bar enable | FEBA=08 bar output is now live-confirmed on this board; exact silicon field name remains unknown |

The local upstream source is `upstream/macrosilicon_firmware/ms2109/eeprom/crt0_ms2109.asm`. At its command-01 handler (around lines 435–443) and command-0B handler (around lines 503–519), it writes FEBA=08 in addition to F92C=20. Byte inspection of the installed 2,048-byte calibrated EEPROM confirms the F92C=20 and E33C block instructions but finds no `MOVX` store of FEBA=08. Its TODO also lists no-signal pattern customization as unfinished. Its USB-display test-pattern tool concerns a host-generated display path and does not establish an MS2109 internal capture-pattern API.

The factory signal-dependent path at D1BA compares C6B1:C6B2 with C6C6:C6C7 and checks C6AA bit 0. Failed checks pass R7=1 to CE6B; the other branch passes zero. CE6B adjusts width/timing-related registers. This is evidence of fallback configuration, not proof that this argument directly selects the visible bar image. Neither reviewed routine uploads an arbitrary bitmap.

The bars come from an internal pattern generator selected through FEBA, rather than an EEPROM bitmap. FEBA=08 gives color bars when HDMI is absent; the generator does not replace a valid HDMI picture in the tested path. FEBA also selects solid fields, grids and grayscale ramps. The evidence does not establish whether custom pixels or text can be uploaded.

## Can the bars be replaced?

- **Black, a solid field, or another built-in pattern:** confirmed through FEBA values 00–0C and 0D–10; see the [full observed map](../2026-10-06_ms2109-feba-pattern-sweep-report.html).
- **Custom text, logo or full test card:** no framebuffer upload, OSD or arbitrary-pattern interface has been identified. EEPROM code patchability does not establish pixel-generation capability.
- The successful experiment used temporary RAM writes, restored FEBA=00, and verified the EEPROM stayed byte-for-byte unchanged. MJPEG and raw USB remain untested. Persistent firmware changes should be considered separately after reviewing which boot command should set FEBA=08 and preserving the fallback mode expected by the device.

The path for exposing FEBA as a host control is assessed in [UVC pattern controls](uvc-pattern-controls.html). The ROM descriptor graph currently has no Extension Unit, and Windows/Linux have different UI behavior for vendor XU controls.

## Can a 1 kHz tone accompany the bars?

Mathematically, a 48 kHz stream needs a 48-sample repeating sine table:

```text
sample[n] = round(A * sin(2*pi*n/48)), n = 0..47
```

One 16-bit mono cycle uses 96 bytes, or 192 bytes if stored as interleaved identical stereo. Continuous 48 kHz, 16-bit stereo delivery needs 192000 payload bytes per second. The small table is not the bottleneck: the chip needs a clocked sample source and a route into endpoint 2 while HDMI is absent.

The reviewed audio ROM configures rate values FE62–FE67 and services endpoint readiness; it does not expose a CPU PCM copy loop or a known tone-generator command. Prior experiments with the candidate FIFO port AD did not establish a usable sample-injection path. No evidence establishes that the 8051 can sustain that stream through AD, nor that a suitable timer/DMA loop exists. Absence from the reviewed firmware does not prove the silicon lacks a test-tone mode.

Three possible implementation routes remain unqualified: a built-in audio test generator, a repeating hardware buffer/DMA source, or CPU-fed USB audio after its endpoint mode and FIFO contract are recovered. FE62–FE67 specify rates; setting them to 1000 would not synthesize a 1 kHz waveform.

## Reproduce the static findings

From the repository root, using radare2:

```sh
r2 -q -a 8051 -b 8 -c 's 0x3f42; pd 40; s 0x6f5b; pd 4; s 0x6eed; pd 5' backups/ms2109-maskrom.bin
r2 -q -a 8051 -b 8 -m 0xcc00 -c 's 0xd03a; px 35; s 0xd082; pd 24; s 0xd1ba; pd 42; s 0xce6b; pd 120' artifacts/original-code.bin
```

The dispatch table following LCALL D212 contains embedded data; do not decode it as instructions. The evidence path is ROM video init → normal command 01/0B → factory register override, and signal checks → CE6B fallback configuration. Hardware validation remains open. See [audio register mapping](audio-rate-and-cc10.html) and [the producer-path investigation](../2026-10-06_ms2109-producer-phase-control-report.html).
