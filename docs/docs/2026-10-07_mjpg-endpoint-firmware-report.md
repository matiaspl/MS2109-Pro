# MS2109 MJPEG endpoint firmware report

> Analysis date: 7 October 2026  
> Analyst: Codex  
> Method: offline descriptor decoding, saved 8051 disassembly, and a read-only live USB GET_DESCRIPTOR request; no device writes or reset occurred

## Summary

The pinned MS2109 firmware advertises MJPEG and YUY2 through the same high-speed isochronous IN endpoint, `0x83`, on VideoStreaming interface 1. Three alternate settings provide 800, 2,048, and 3,072 bytes per microframe. A fresh read-only EP0 configuration-descriptor response advertises a 60 fps default for 1920×1080 MJPEG and matches the saved RAM-backed descriptor copy at `0xC03A` except at byte `0x41`. The immutable CODE template defaults that mode to 30 fps. The existing stream capture negotiated 30 fps with a 3,072-byte payload size, which both tables support; 60 fps is advertised but was not dynamically stream-qualified. ROM endpoint-bank setup writes `0x1400`, matching the maximum alternate descriptor. The reviewed capture shows no obvious MJPEG endpoint-capacity mismatch; this does not establish behavior at every mode, rate, or host.

## Scope and method

This follows the existing MS2109 analysis scope in [scope.md](scope.html): inspect saved firmware and project artifacts, then make a read-only live descriptor request. `backups/ms2109-maskrom.bin` is a 52,224-byte address-indexed CODE-space snapshot through `0xCBFF`; its `0xC000–0xCBFF` tail contains overlay/RAM-backed bytes and is not immutable ROM. The immutable high-speed configuration template is at CODE `0x7111`; a saved RAM-backed copy is at `0xC03A`. A prior live pointer read returned XDATA `0xC03A`, but a one-byte edit there did not affect the raw EP0 response. A later GET_DESCRIPTOR(Configuration) succeeded and returned a 1,211-byte response; the 1920×1080 MJPEG frame intervals match the saved XDATA copy, and that entire response differs from the copy only at offset `0x0041`. The raw response and parsed summary are saved under `artifacts/ms2109-repair/20261007/`. This 8051 image has no PE/ELF import table, so `E-imports` is not applicable. The local tool index reports IDA Pro unavailable, so this focused check used the project's pinned ROM disassembly and a read-only descriptor decoder. No device RAM, EEPROM, or firmware was changed.

## Findings

### F-001 — MJPEG shares high-speed endpoint 0x83 with YUY2

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: E-001, E-002
- confidence: high for descriptor fields
- location: CODE configuration template `0x7111`, saved XDATA copy `0xC03A`, and endpoint setup at ROM `0x61A1`

The 1,211-byte high-speed configuration template at CODE `0x7111` contains MJPEG format index 1 and YUY2 format index 2. A saved RAM-backed copy at `0xC03A` has the same endpoint settings but differs in MJPEG frame intervals. Both formats are on interface 1 and use endpoint address `0x83`. The endpoint descriptors are isochronous IN; alternate settings 1–3 set progressively larger maximum packet capacities. The endpoint is selected by the host through the interface alternate setting, not through a distinct MJPEG-only endpoint.

| Alternate | Raw `wMaxPacketSize` | Transactions per microframe | Payload capacity |
|---:|---:|---:|---:|
| 1 | `0x0320` | 1 × 800 bytes | 800 bytes |
| 2 | `0x0C00` | 2 × 1,024 bytes | 2,048 bytes |
| 3 | `0x1400` | 3 × 1,024 bytes | 3,072 bytes |

All three endpoint descriptors encode `bInterval=1` and `bmAttributes=0x05`. `wMaxPacketSize` uses bits 10:0 for payload bytes per transaction and bits 12:11 for the transaction multiplier; the USB-IF specification describes that encoding for high-speed periodic endpoints ([USB-IF Embedded USB2 supplement](https://www.usb.org/sites/default/files/Embedded%20USB2%20Version%202.0%20Supplement%20to%20the%20USB%202.0%20Specification_0.pdf)).

### F-002 — Live EP0 advertises the saved RAM-backed 60 fps MJPEG table

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: E-001, E-004, E-005
- confidence: high for the returned EP0 descriptor and its frame intervals
- location: CODE MJPEG frame at `0x7181`, saved XDATA copy at `0xC0AA`, active configuration pointer `C002:C003`, live EP0 response

The two 1920×1080 MJPEG frame records differ:

| Source | Default interval | Advertised intervals (100 ns) | Approximate fps |
|---|---:|---|---|
| Immutable CODE frame at `0x7181` | 333,333 | 333,333; 400,000; 500,000; 1,000,000; 2,000,000 | 30; 25; 20; 10; 5 |
| Saved RAM-backed frame at `0xC0AA` | 166,666 | 166,666; 333,333; 400,000; 500,000; 1,000,000 | 60; 30; 25; 20; 10 |

Both saved tables declare a maximum bitrate of 196,608,000 bit/s, matching the theoretical capacity of alternate 3. The fresh 1,211-byte type-2 EP0 response advertises the RAM-backed table's 166,666 default and the same five 1920×1080 intervals. Compared with the complete saved copy at `0xC03A`, the live response differs only at descriptor-relative offset `0x0041`; the frame records are byte-identical. Offset `0x0041` is the low byte of the Processing Unit `bmControls` bitmap: live EP0 returns `0x1F`, while the saved CODE/XDATA templates contain `0x0F`. Thus the current descriptor still advertises the Sharpness bit; this descriptor read alone does not establish a visible sharpness effect. This identifies the currently returned frame-rate table even though the prior one-byte RAM probe did not change the raw EP0 response. It does not prove that the live 60 fps stream sustains that rate.

### F-003 — Existing live MJPEG negotiation matches alternate 3

- severity: n/a_re
- category: reverse_algo
- status: validated
- evidence_ids: E-003
- confidence: high for this recorded capture
- location: `artifacts/color-probe/20261006-original-usb/mjpeg/usb-capture.json`

The saved raw USB capture negotiated format index 1, frame index 1, 1920×1080, interval 333,333 (about 30 fps), `max_payload_bytes=3072`, and `max_frame_bytes=4147200`. Its eight JPEG payloads were 86,497 or 86,637 bytes. The negotiated payload size agrees with endpoint alternate 3. The 30 fps interval is supported in the live table. The large `max_frame_bytes` figure is distinct from the endpoint packet capacity and from the captured compressed JPEG byte count.

### E-001 — Saved ROM descriptors

- observed_at: 2026-10-07
- source_type: file
- source_ref: `backups/ms2109-maskrom.bin`, CODE configuration at `0x7111`, saved XDATA overlay copy at `0xC03A`, MJPEG frame records at `0x7181` and `0xC0AA`, endpoints at CODE `0x7521` onward and saved overlay `0xC44A` onward
- content_hash: file SHA-256 `b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8`; CODE config SHA-256 `e8eaf62fb0559ea6af281cdf0442ec5ea67ec72888735e302909e0299bf3f731`; saved XDATA copy SHA-256 `31dac46d62f4a6b880972980b0f4d85d9f5cb461a6fcb83f0b29292b99ff97de`
- artifact_path: `backups/ms2109-maskrom.bin`
- repro_command: `python3 tools/analyze_color_metadata.py backups/ms2109-maskrom.bin`, `xxd -g1 -s 0x7181 -l 46 backups/ms2109-maskrom.bin`, `xxd -g1 -s 0xc0aa -l 46 backups/ms2109-maskrom.bin`, and `xxd -g1 -s 0xc44a -l 35 backups/ms2109-maskrom.bin`
- raw_excerpt: endpoint bytes `07 05 83 05 20 03 01`, `07 05 83 05 00 0c 01`, `07 05 83 05 00 14 01`; CODE 1080p MJPEG frame defaults to interval `0x00051615` (333333), while the saved XDATA copy defaults to `0x00028B0A` (166666); both have max bitrate `0x0BB80000`.
- linked_workitem: n/a
- supersedes: none

The image is 52,224 bytes. There is no executable-format import table; direct ROM calls and descriptor bytes are the relevant static references for this question.

### E-002 — ROM endpoint-bank setup

- observed_at: 2026-10-07
- source_type: file
- source_ref: `artifacts/rom-disassembly.txt`, ROM `0x61A1–0x61CB`
- content_hash: SHA-256 `61ef16723286e6c9858d1ce6f7439f4831f75c839e813e797e8f793002e3d895`
- artifact_path: `artifacts/rom-disassembly.txt`
- repro_command: `sed -n '13724,13743p' artifacts/rom-disassembly.txt`
- raw_excerpt: ROM `0x61B0` selects bank 3, writes `A2=00`, `A3=14`, then writes endpoint control SFRs `80=05`, `90=70`.
- linked_workitem: n/a
- supersedes: none

### E-003 — Previously captured live MJPEG stream

- observed_at: 2026-10-06
- source_type: file
- source_ref: `artifacts/color-probe/20261006-original-usb/mjpeg/usb-capture.json`
- content_hash: SHA-256 `22c3f9864e583fe169675cef74c845fca514aff4d95677a1760dae5f5324d644`
- artifact_path: `artifacts/color-probe/20261006-original-usb/mjpeg/usb-capture.json`
- repro_command: `python3 -c 'import json; print(json.load(open("artifacts/color-probe/20261006-original-usb/mjpeg/usb-capture.json")))'`
- raw_excerpt: `format_index=1`, `frame_index=1`, `interval_100ns=333333`, `max_payload_bytes=3072`, `max_frame_bytes=4147200`; 8 JPEG frames, 86,497–86,637 bytes each.
- linked_workitem: n/a
- supersedes: none

### E-004 — Prior active-pointer versus EP0 RAM probe

- observed_at: 2026-10-07
- source_type: file
- source_ref: `artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-xdata-probe.json`
- content_hash: SHA-256 `ee4917e9199f3c735086aef57c6b41a076041e1ffa0b06ad5e4d4f69c2f7b81b`
- artifact_path: `artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-xdata-probe.json`
- repro_command: `cat artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-xdata-probe.json`
- raw_excerpt: pointer field read `C03A`; one-byte RAM edit at descriptor bitmap address `C07B` was visible in RAM, but `ep0_reflected_ram_patch=false`; RAM restored and EEPROM unchanged.
- linked_workitem: n/a
- supersedes: none

### E-005 — Fresh read-only live configuration descriptor

- observed_at: 2026-10-07
- source_type: device
- source_ref: USB standard GET_DESCRIPTOR(Configuration), `bmRequestType=0x80`, `bRequest=0x06`, `wValue=0x0200`, `wIndex=0`
- content_hash: raw response SHA-256 `9262bf79c4a7e48179eee260a277fc97143e2025e181d64da091b1e7cf724e86`; parsed summary SHA-256 `1a0c293e14351894c4ef13ffc53a39260418d6814cc2139e0fb8e24aefa8979e`
- artifact_path: `artifacts/ms2109-repair/20261007/mjpg-live-config-descriptor.bin`; parsed summary: `artifacts/ms2109-repair/20261007/mjpg-live-config-descriptor.json`
- repro_command: `cat artifacts/ms2109-repair/20261007/mjpg-live-config-descriptor.json`; raw descriptor captured using `EP0.get_descriptor(2, 2048)` from `tools/probe_uac_descriptor_patch_ram.py`
- raw_excerpt: 1,211 bytes; MJPEG 1920×1080 default interval 166,666 with advertised intervals 166,666, 333,333, 400,000, 500,000, 1,000,000 (100 ns). Shared IN endpoint `0x83`; alternates 1–3 advertise 800, 2,048, and 3,072 bytes per microframe. Compared with saved XDATA `0xC03A`, only descriptor offset `0x0041` differs: the Processing Unit `bmControls` low byte is `0x1F` live versus `0x0F` saved, so Sharpness is advertised.
- linked_workitem: n/a
- supersedes: active-source uncertainty in E-004 for the current returned type-2 descriptor; E-004's historical probe result remains valid

## Path

### P-001 — MJPEG descriptor to USB stream

- path_type: callflow
- start: high-speed VideoStreaming configuration template
- goal: determine the MJPEG transport endpoint and compare it with a recorded stream
- steps:
  1. Read MJPEG format index 1 and its frame index 1 from the VideoStreaming descriptors — evidence E-001, finding F-001.
  2. Follow `bEndpointAddress=0x83` to interface 1 alternate settings 1–3 and decode their packet capacities — evidence E-001, finding F-001.
  3. Compare the CODE and saved XDATA frame intervals with the fresh raw EP0 response — evidence E-001, E-004, and E-005, finding F-002.
  4. Compare the endpoint maximum with the recorded libuvc negotiation and JPEG payload sizes — evidence E-003, finding F-003.
  5. Compare the maximum alternate setting with the ROM's bank-3 setup values — evidence E-002, finding F-001.
- residual_risks: 1080p60 streaming and alternate-setting transitions were not dynamically qualified; SFR A2/A3 semantics are not fully decoded.

## Limits and conclusion

The saved firmware, fresh EP0 descriptor, and existing live capture agree on a 3,072-byte high-speed MJPEG payload capacity. The current EP0 frame intervals match the saved RAM-backed copy, while its only full-descriptor difference from that copy is byte `0x41`; the CODE template has the separate 30 fps default. The recorded 1080p30 capture is consistent with the current descriptor, but it does not qualify 1080p60 throughput, all alternate settings, or future hardware state. I found no static mismatch in endpoint capacity. The endpoint descriptors describe USB transport; they do not define input image scaling or viewport geometry.

Timeline: on 2026-10-07, the saved firmware tables and existing raw MJPEG capture were reviewed. A first read-only libusb open attempt failed before a USB request; a later read-only GET_DESCRIPTOR(Configuration) succeeded and its raw 1,211-byte response was saved. No RAM, EEPROM, firmware, or USB reset operation occurred.
