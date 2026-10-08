# USB descriptor response paths

Return to the [reference index](README.md). This page records one pinned MS2109 ROM revision and one live RAM probe.

**Current name update (8 October 2026):** the upstream [qoaimei MS2109 generator](https://github.com/qoaimei/ms21xx-firmware/blob/master/ms21xx_firmware/generate.py) writes the video name into the EEPROM header field at `0x10` and audio at `0x20`, then recomputes checksums. Both records are now set to `MS2109-Pro` in the installed image; the 1,816 code bytes are unchanged. The complete readback matches SHA-256 `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`. A CBF0 RAM edit did not alter string 4 in the running session and was restored. The device has not yet been physically power-cycled after this header update, so the host-visible names remain pending verification. See the [name-update report](../2026-10-08_ms2109-usb-name-header-report.md).

## Product string

The ROM's device descriptor at XDATA `C688` has `iProduct = 2`. The standard GET_DESCRIPTOR path dispatches string index 2 through ROM `0D07–0D24` and eventually transfers XDATA `C636` through the common EP0 routine at `0E3C`. However, `C636` is a generated response buffer, not the authoritative product-name source. ROM code at `0x2340–0x236D` rebuilds the UTF-16LE response before transfer. The mask-ROM code table at `CBE0` contains `0A 75 73 62 20 76 69 64 65 6F FF…` (the “usb video” source). A runtime probe that changed XDATA `CBE1–CBE9` did not affect a fresh raw EP0 response, so the complete initialization/source flow still needs tracing.

The initial candidate wrote an intended 22-byte “MS2109-Pro” descriptor to `C636` in startup stage 1. ROM then rebuilt the buffer, so this write did not change the live product string. The corrected stage-2 candidate repairs `C636` after the ROM descriptor builder has run.

## Live RAM result

After installing the candidate and physically power-cycling, the live header read `A55A07C905…` and declared 1,993 code bytes. The calibrated startup state and both color-record patches were present, but `C636` and raw EP0 still returned “usb video”. A separate reversible XDATA source-buffer edit also left the product string unchanged; the buffer was restored exactly. The EEPROM was read twice and matched candidate SHA-256 `543d35dc33ff9f0bf60fe24066032c56aa40b23b7c2b58207c7afdb955f41961`. Full measurements are in [the post-power-cycle check](../../artifacts/ms2109-pro-name/20261007/post-power-cycle-ram-check.json).

The cold-boot result rules out host-side descriptor caching as the sole explanation. The candidate boots and runs its calibrated callback, but does not rename the device. A corrected firmware must alter the ROM descriptor-generation path or its source before the first descriptor transfer. Do not treat this candidate as a successful product-name build.

## Corrected volatile RAM qualification

The ROM boot sequence runs the stage-1 callback and then invokes the descriptor builder at `0x22DC`, which explains why the original startup write was overwritten. The corrected image moves the descriptor write into the stage-2 polling callback, after that builder. During RAM-only qualification, the poll callback changed `C636` from the ROM-generated “usb video” string to the exact UTF-16LE “MS2109-Pro” descriptor. Raw EP0 returned that string before and after a USB bus reset, and the candidate overlay remained loaded across the reset.

The corrected candidate SHA-256 is `b0b25243c155086bb0b96d41a5927104a3f04a8a1f5a3ae3930568943f5690d7`; it is 2,048 bytes with 1,993 declared code bytes. RAM snapshots were restored and EEPROM remained at the previously installed image (`543d35dc…f41961`). This qualifies the descriptor on the live RAM path; the corrected image has not yet been installed in EEPROM. See the [qualification record](../../artifacts/ms2109-pro-name/20261007/stage2-ram-qualification-usb-reset-02.json) and [candidate report](../2026-10-07_ms2109-pro-name-candidate.md).

See the [name-candidate report](../2026-10-07_ms2109-pro-name-candidate.md), [live probe record](../../artifacts/ms2109-pro-name/20261007/product-name-ram-probe-02.json), and [probe script](../../tools/probe_product_name_ram.py).

## UVC MJPEG video endpoint

The immutable CODE high-speed configuration template at `0x7111` (1,211 bytes) and a saved RAM-backed configuration copy at XDATA `0xC03A` both expose MJPEG format index 1 and YUY2 format index 2 on VideoStreaming interface 1. Their endpoint descriptors match, but their MJPEG frame interval tables differ. A fresh read-only EP0 GET_DESCRIPTOR(Configuration) returned 1,211 bytes with SHA-256 `9262bf79c4a7e48179eee260a277fc97143e2025e181d64da091b1e7cf724e86`. Its full contents match the saved `0xC03A` copy except descriptor-relative byte `0x0041`; the MJPEG frame records and endpoint descriptors match byte-for-byte. Offset `0x0041` is the low byte of the Processing Unit `bmControls` bitmap: live EP0 returns `0x1F`, while the saved CODE/XDATA templates contain `0x0F`, so Sharpness remains advertised. This reports descriptor state only and does not establish a visible sharpness effect. The live 1920×1080 MJPEG frame defaults to 166,666 (about 60 fps), rather than the CODE template's 333,333 (about 30 fps). The prior pointer read and unsuccessful one-byte EP0 reflection probe are historical results; the new raw response resolves which interval table is currently returned. Both formats share IN endpoint `0x83`; the host selects its capacity through interface alternate settings. Endpoint descriptors in the saved copy at `C44A`, `C45A`, and `C46A` are isochronous (`bmAttributes=0x05`) with `bInterval=1`:

| Interface alternate | `wMaxPacketSize` | High-speed transactions | Payload capacity per 125 µs microframe |
|---:|---:|---:|---:|
| 1 | `0x0320` | 1 × 800 bytes | 800 bytes |
| 2 | `0x0C00` | 2 × 1,024 bytes | 2,048 bytes |
| 3 | `0x1400` | 3 × 1,024 bytes | 3,072 bytes |

At 1920×1080, the CODE template at `0x7181` defaults to 333,333 (about 30 fps) and lists `333333, 400000, 500000, 1000000, 2000000` (about 30, 25, 20, 10, and 5 fps). The saved XDATA copy at `0xC0AA` defaults to 166,666 (about 60 fps) and lists `166666, 333333, 400000, 500000, 1000000` (about 60, 30, 25, 20, and 10 fps). A prior runtime pointer read returned XDATA `C03A`, but a RAM edit there did not alter the raw EP0 response. Both copies declare `dwMaxBitRate=196,608,000` bit/s, equal to the endpoint-3 alternate's theoretical 3,072-byte-per-microframe capacity. The firmware initializes USB endpoint bank 3 with SFR `A2:A3 = 00:14` while selecting bank 3; this agrees with the largest descriptor alternate, although the complete SFR bit semantics are not decoded.

An existing raw USB capture negotiated MJPEG 1920×1080 at interval `333333` (~30 fps), `max_payload_bytes=3072`, and `max_frame_bytes=4147200`. Its eight JPEG frames were 86,497 or 86,637 bytes. This is consistent with alternate 3 and gives no indication of a video-endpoint capacity mismatch in that capture. The live descriptor supports 30 fps as well as advertising a 60 fps default; 60 fps stream throughput has not been dynamically qualified. The `dwMaxVideoFrameBufferSize`/libuvc `max_frame_bytes` value is a per-frame buffer bound; it is not the endpoint packet size.

The raw live type-2 response and parsed frame/endpoint summary are saved at [mjpg-live-config-descriptor.bin](../../artifacts/ms2109-repair/20261007/mjpg-live-config-descriptor.bin) and [mjpg-live-config-descriptor.json](../../artifacts/ms2109-repair/20261007/mjpg-live-config-descriptor.json). The query issued GET_DESCRIPTOR only; no USB reset or device writes were performed.

The separate Other-Speed template at `75CC` has a reduced 640×480 MJPEG profile and endpoint `0x83` alternates with packet sizes 192, 512, 700, and 800 bytes. See the [focused firmware report](../2026-10-07_mjpg-endpoint-firmware-report.md) for raw evidence and limits. These endpoint descriptors govern USB transport. They do not describe the HDMI-to-video scaling that determines whether pixels fit inside the captured frame.
