# MS2109 F92C experiment — no-signal condition invalidated

**Correction from the user:** HDMI was not disconnected during this run. The no-signal condition was therefore not established. The black-frame observations remain valid captures but cannot establish behavior without HDMI. The requested repeat is pending physical disconnection.

The authorized temporary F92C comparison completed and normal HDMI video recovered after reconnection. F92C=20 and F92C=30 both produced the same black output on the tested AVFoundation YUY2 path. The baseline was already black, so this does not demonstrate bar removal or identify a bar selector. No EEPROM writes occurred; complete before/after reads were identical.

## Method and evidence

The run proceeded on an earlier confirmation of HDMI disconnection, but the user subsequently corrected that statement: HDMI had remained connected. The [probe](../tools/probe_no_signal_f92c.py) saved the original register, captured baseline/20/30/restored stages, checked readback and restored in `finally`. Only XDATA F92C was explicitly written, via HID B6. USB stream negotiation is performed by AVFoundation. No picture-control SET_CUR or audio experiment was requested by this probe.

The capture selected `usb video` by name, requested 1920×1080 YUY2 at 5 fps and saved four-second FFV1 recordings. FFmpeg output was explicitly set to 5 fps because AVFoundation advertised an implausible nominal time base/rate. Each file contains 20 output frames; this is not a raw USB continuity measurement and does not establish 20 distinct device frames.

| Stage | F92C readback after write / after capture | Frame result |
|---|---|---|
| Baseline | 20 / 20 | Black |
| Requested 20 | 20 / 20 | Identical black |
| Requested 30 | 30 / 30 | Identical black |
| Restored | 20 / 20 | Identical black |

Every decoded frame in the four recordings has MD5 `c5105c8504014cec18324ce1a79758be`. The last-frame PNGs also match exactly. FEBA remained 00. Procamp registers remained FE90–FE93 `ee959300`, shadow C6A0 `eeff950000009300`, and flags CBD4/CBD5 `0510`.

The full EEPROM SHA-256 before and after is `83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82`. After HDMI reconnection, a new frame visibly contained the source desktop and HID confirmed F92C=20 with the same controls/flags. Thus capture and source recovery were verified, not merely a successful register write.

- [Register/EEPROM journal](../artifacts/no-signal-f92c/trial-01/result.json)
- [Frame comparison](../artifacts/no-signal-f92c/trial-01/comparison.json)
- [No-signal frame](../artifacts/no-signal-f92c/trial-01/f92c-30.png)
- [Recovered HDMI frame](../artifacts/no-signal-f92c/trial-01/hdmi-recovered.png)
- [Recovered register state](../artifacts/no-signal-f92c/trial-01/hdmi-recovered.json)

Evidence → finding → path: verified 20/30 readbacks and identical decoded frames → changing F92C bit 4 alone had no visible effect in this state → user disconnects HDMI, native capture starts, temporary write, capture/readback, restore, user reconnects, image recovery.

## Limits and next step

This tests native AVFoundation-delivered YUY2 only. Raw USB YUY2 and MJPEG were not captured, so format-dependent fallback remains unresolved. No bars appeared in the baseline; do not label the black output a successful bars-to-black patch. FEBA=08 remains an untested upstream candidate, and no synthetic audio path was enabled. A useful next step is to reproduce the bars in the user's usual capture mode before testing FEBA or other pattern controls.

## Trial 02 — repeat after confirmed physical disconnection

The user explicitly confirmed HDMI physically unplugged with USB connected. The same bounded test was rerun into a new `trial-02` directory. All four captures completed, with 20 output frames each. Every decoded frame had the same MD5 as above and all last-frame PNGs were identical black. F92C=20 and 30 both read back as requested immediately after the write and after capture. Original F92C=20 was restored, the full EEPROM hash remained unchanged, and calibrated picture controls and hook flags were preserved.

This repeat establishes the negative result under the user-confirmed no-HDMI condition for native AVFoundation YUY2. It still does not identify a bars selector or establish MJPEG/raw USB behavior. No FEBA writes or audio synthesis were attempted.

- [Trial 02 register and EEPROM journal](../artifacts/no-signal-f92c/trial-02/result.json)
- [Trial 02 frame comparison](../artifacts/no-signal-f92c/trial-02/comparison.json)

After the user confirmed HDMI reconnection, a new capture visibly showed the source desktop. HID readback confirmed F92C=20, FEBA=00 and unchanged picture controls/hook flags. Recovery is verified for trial 02. Evidence: `artifacts/no-signal-f92c/trial-02/hdmi-recovered.png` and `hdmi-recovered.json`.
