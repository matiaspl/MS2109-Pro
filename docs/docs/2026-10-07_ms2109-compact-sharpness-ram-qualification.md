# MS2109 compact Sharpness RAM qualification

7 October 2026. Live volatile-memory qualification of the compact ROM-EDID candidate. The candidate was removed after the run; the external EEPROM was not written.

## Result

The Sharpness USB query/set path and video streams passed in RAM. Overall status is **partial** because the active configuration response stayed at Processing Unit bitmap `0x000F`, while the other-speed response returned `0x001F`. The active descriptor's XDATA byte and candidate scratch area were both probed; neither showed a working post-enumeration patch path. A USB reset clears the RAM candidate and reloads the installed EEPROM, so candidate discovery cannot be verified by a RAM-only re-enumeration.

The live EEPROM was 2,048 bytes, declared code length `0x079E`, flags `0x05`, and SHA-256 `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`, matching the known calibrated stereo rollback image. A second two-read EEPROM backup was saved as [live-prequal-eeprom.bin](../artifacts/sharpness-firmware/20261007-compact-final/live-prequal-eeprom.bin).

The candidate image hash was `d6c1c53fa43e8f4d622c37022fbd91a6bd093813af81585172750380071da596`. The tool saved the affected RAM ranges, disabled callback gates during code staging, loaded the 1,994-byte image into RAM, initialized selected state to 64/FE84=`40`/FE85=`00`, then enabled flags `07` for the tests.

## Live UVC results

| Operation | Result |
|---|---|
| GET_CUR / MIN / MAX / RES / LEN / INFO / DEF | `4000 / 0000 / 7f00 / 0100 / 0200 / 03 / 4000` |
| SET_CUR 0 | Accepted; GET_CUR `0000`, FE84=`00`, FE85=`00` |
| SET_CUR 64 | Accepted; GET_CUR `4000`, FE84=`40`, FE85=`00` |
| SET_CUR 127 | Accepted; GET_CUR `7f00`, FE84=`7f`, FE85=`00` |
| SET_CUR 128 | Stalled; GET_CUR remained `7f00`, FE84 remained `7f` |
| Existing brightness GET_CUR | Delegated successfully; response `eeff` |
| Active configuration type 2 | 1,211 bytes received; PU `bmControls=000f` in this session |
| Other-speed configuration type 7 | 355 bytes received; PU `bmControls=001f` |
| 1920×1080 YUY2 stream | Two frames at 5 fps; opened and completed |
| 1280×720 YUY2 stream | Two frames at 10 fps; opened and completed |
| Sharpness after both stream starts | GET_CUR remained `7f00` |

The descriptor probe uses libusb `control_transfer` with standard device-recipient `GET_DESCRIPTOR` requests (`bmRequestType=0x80`, request 6). macOS's libusb backend submits EP0 control transfers through `DeviceRequestAsyncTO`, which Apple documents as [sending a USB request on the default control pipe](https://developer.apple.com/documentation/iokit/iousbdeviceinterface182/1558785-devicerequestasyncto). Type 2 returned `bmControls=0x000F`; type 7 returned `0x001F`. A follow-up read found that type 2 left the candidate scratch bytes (`29 05`) unchanged, while type 7 populated the scratch buffer and changed its bitmap to `1F 00`.

The live XDATA pointer `C002:C003` was `C03A`, and the active descriptor bytes at `C03A` matched the descriptor header. Its PU bitmap byte is at `C07B`. A reversible one-byte RAM probe changed `C07B` from `0F` to `1F`, but a further raw type-2 EP0 read still returned `0F`; the byte was restored. ROM's normal active-config transfer helper `4B10` reads its source pointer from `C002:C003`, but the current raw response did not reflect a post-enumeration edit to that buffer. The exact response source or snapshot point remains unresolved; the test does not prove a host-cache explanation or a viable boot-time patch point.

A controlled `libusb_reset_device` then forced USB re-enumeration. It cleared the volatile `C07B` edit and the device returned with the original EEPROM image and `C07B=0F`; EEPROM SHA-256 remained unchanged. Therefore this reset cannot be used to enumerate the RAM candidate: it reloads the installed EEPROM before the host enumerates. A fresh-enumeration qualification of the Sharpness image requires an EEPROM-installed candidate, which remains a separately authorized step. Details are in [active descriptor RAM probe](../artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-xdata-probe.json) and [USB reset/re-enumeration probe](../artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-reenumeration-probe.json). The type-7 result still demonstrates that the candidate's guarded copy path can set bit 4 in the other-speed descriptor.

The stream test checked successful opens and frame delivery at both sizes. It did not compare a known chart or evaluate image quality. Linux V4L2 discovery, Windows VideoProcAmp discovery, HDMI loss/recovery, and fresh-enumeration active descriptor discovery remain untested.

## Restoration

After each completed run, the qualification tool restored all 12 snapshotted RAM ranges and their readbacks matched exactly. The two descriptor probes restored `C07B` to `0F`. Callback flags returned to `05`. Two complete EEPROM readbacks matched each other and the original SHA-256. No EEPROM write command was issued. The detailed records are [final RAM qualification](../artifacts/sharpness-firmware/20261007-compact-final/ram-qualification-final.json), [prior descriptor scratch probe](../artifacts/sharpness-firmware/20261007-compact-final/ram-qualification-descriptor-cache-probe.json), [active descriptor RAM probe](../artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-xdata-probe.json), [USB reset/re-enumeration probe](../artifacts/sharpness-firmware/20261007-compact-final/active-descriptor-reenumeration-probe.json), [two-read EEPROM backup](../artifacts/sharpness-firmware/20261007-compact-final/live-prequal-eeprom.bin), and [source/artifact hash manifest](../artifacts/sharpness-firmware/20261007-compact-final/sha256-manifest.json).

The first cleanup attempt had a local read-call bug after it had written the snapshots back; a separate restoration pass then verified all ranges and EEPROM before the subsequent qualification. An initial 5 fps 720p capture request also failed because that mode is tested at 10 fps. The final run used the successful 10 fps mode. The early records are retained for audit.

## Reproduction and recovery

The [qualification tool](../tools/qualify_sharpness_ram.py) verifies the live EEPROM hash, refuses to proceed on a different image, uses HID RAM writes only, and restores saved ranges in `finally`. The [recovery tool](../tools/restore_sharpness_ram.py) can restore a saved JSON snapshot if a process exits before cleanup. A USB power cycle also reloads the unchanged EEPROM image.
