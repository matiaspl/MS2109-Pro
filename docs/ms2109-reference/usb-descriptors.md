# USB descriptor response paths

Return to the [reference index](README.md). This page records one pinned MS2109 ROM revision and one live RAM probe.

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
