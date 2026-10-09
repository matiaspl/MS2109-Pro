# MS2109 UVC Sharpness removal

**Date:** 8 October 2026  
**Target:** attached MS2109, USB ID `534d:2109`  
**Status:** Sharpness-removal profile cold-boot qualified; the later name-only EEPROM update is also verified after physical reconnect. Both USB name descriptors report `MS2109-Pro`.

## Change

UVC Sharpness is removed from the rebuilt control-repair profile. The profile now:

- clears Processing Unit bitmap bit 4 in guarded copies of standard and other-speed configuration descriptors;
- stalls UVC Sharpness selector 8 requests;
- keeps no Sharpness value and performs no FE84/FE85 writes;
- delegates brightness, contrast, hue, saturation, and unrelated requests to the stock ROM.

FE84/FE85 remain unresolved scale/filter candidates. No visible Sharpness mapping was established, so the firmware does not advertise a Sharpness control.

The compact candidate has a 1,816-byte overlay. Candidate SHA-256 is `bee6059bc398bda76348e4dfe7d3df76fbedd32ac8d5a0d79af97ab3ed382bab`; hook SHA-256 is `f0e9d538f411460fab6cfebcd2bd810e474ffb4dca10b08f8498077bee534b92`. The candidate is at [ms2109-control-repair-candidate.bin](../artifacts/ms2109-repair/20261007/ms2109-control-repair-candidate.bin).

## Offline verification

The targeted offline firmware suite completed 48 tests in 54.841 seconds:

```sh
python3 -m unittest tests.test_sharpness_firmware tests.test_compact_sharpness tests.test_sharpness_rom_edid -v
```

The tests exercise selector rejection, delegation for other controls, guarded descriptor-bit clearing, no FE84/FE85 writes, compact packing, and ROM behavior. A subsequent `py_compile` check on the edited builder, firmware generator, and qualification tools passed. `git diff --check` passed.

## Live qualification safety result

The first RAM qualification stopped at a preflight guard. A later attempt accepted only three repeatable, reviewed runtime differences: `CC1A` held the old Sharpness value, and `D0D8–D0D9` held a runtime-disabled old repair jump. The candidate removes the value and restores the factory helper at that jump.

That second RAM attempt wrote the candidate overlay, then hit an HID I/O timeout during readback. Its restore path also timed out, so it did not complete the UVC or stream checks. A controlled USB reset recovered the original pre-install image; two EEPROM reads still matched SHA-256 `b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8`.

## EEPROM installation and current state

After the user authorized EEPROM writes, `tools/flash_eeprom.py` wrote 680 changed bytes. It verified each byte and then verified the complete image. The new EEPROM readback matches the candidate SHA-256 `bee6059bc398bda76348e4dfe7d3df76fbedd32ac8d5a0d79af97ab3ed382bab`. The pre-install two-read backup is [preinstall-eeprom-backup.bin](../artifacts/ms2109-repair/20261008/preinstall-eeprom-backup.bin), SHA-256 `b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8`.

A subsequent `libusb_reset_device` returned successfully and two EEPROM reads still matched the candidate. At that checkpoint the runtime header still reported 1,904 code bytes while EEPROM declared 1,816, and the RAM overlay did not match the candidate. The post-reset configuration responses returned `0F00` for both descriptor types, but Sharpness GET_CUR and brightness GET_CUR timed out; other Sharpness requests stalled. Those reset-only results were inconclusive. The user later physically unplugged/reconnected the device; that cold boot and the resulting checks are recorded below.

Before the name-only update, string descriptors 2 and 4 both read `usb video`. The live CBF0 RAM edit did not change string 4. The first post-install USB reset did not qualify picture controls or video streaming; the later cold-boot checks are recorded in the following section.

## Name-only EEPROM update

After the user physically unplugged and reconnected the dongle, a read-only qualification confirmed the 1,816-byte Sharpness-removal profile, the four procamp GET/SET paths, and YUY2 stream starts at 1920×1080 and 1280×720. At that point string descriptors 2 and 4 both returned `usb video`.

The upstream [qoaimei MS2109 generator](https://github.com/qoaimei/ms21xx-firmware/blob/master/ms21xx_firmware/generate.py) identifies EEPROM header offsets `0x10` and `0x20` as the video and audio name records. The local builder now sets both to `MS2109-Pro`. The header-only candidate keeps all 1,816 code bytes identical to the installed image. The guarded writer changed 24 bytes, including the two fixed name records and header checksum; its complete readback matches SHA-256 `2c8e7378b6d23c324726b0fc641f9170af92692b00cf272fe59fda43c9f2fdc5`. The live CBF0 RAM probe did not change string 4 and restored the source and response-buffer ranges; EEPROM remained unchanged during that probe. After physical disconnect/reconnect, a read-only qualification verified header names and USB string descriptors 2 and 4 as `MS2109-Pro`; see the [name-header report](2026-10-08_ms2109-usb-name-header-report.md) and [live result](../artifacts/ms2109-repair/20261008/nonfe-post-reconnect-usb-names-20261008.json).

See the [USB name header report](2026-10-08_ms2109-usb-name-header-report.md), [installation record](../artifacts/ms2109-repair/20261008/usb-name-installation.json), and [installed readback](../artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin).

The installation and post-reset records are [eeprom-installation.json](../artifacts/ms2109-repair/20261008/eeprom-installation.json) and [postinstall-basic-qualification.json](../artifacts/ms2109-repair/20261008/postinstall-basic-qualification.json). The fresh post-reconnect UVC control checks are in [nonfe-post-reconnect-picture-controls-20261008.json](../artifacts/ms2109-repair/20261008/nonfe-post-reconnect-picture-controls-20261008.json); both EEPROM readbacks matched the name-updated image.

Qualification evidence: [sharpness-removal-ram-qualification.json](../artifacts/ms2109-repair/20261007/sharpness-removal-ram-qualification.json).
