# Native-patch baseline and renderer correction

Both active capture helpers now read `endpoint-pattern.json` and draw integer 16×8 rectangles directly with NSColor in the target display’s native color space. The window uses the same color space. There is no NSImage or PNG renderer. Y/Cb/Cr bands are drawn and sampled in direct top-to-bottom order; the previous PNG inversion compensation is removed.

## Live result

Fixed B−17/C148/H0/S146, source-visible baseline EDID, BT.709 USB descriptors and exact restored EEPROM were verified. Each capture used two stable frames with chart/shape gates and restored runtime controls. No desktop pixels or raw video frames were stored.

| Source renderer | Raw Y RMS | Raw Cb RMS | Raw Cr RMS | Y/Cb/Cr spans |
|---|---:|---:|---:|---|
| Prior untagged PNG / NSImage | 4.514 | 4.855 | 4.763 | 253/223/223 |
| Direct display-native patches | **0.403** | **0.446** | **0.446** | **253/253/253** |

Both raw chroma channels now cover 1–254 with one sample at each observed rail. Luma covers 1–254 with the first two input codes mapping to the same output code; the low plateau is above the 0 rail. There are no extra rail samples under the existing criterion. This remains complementary-ramp qualification, not an exhaustive RGB-cube test.

Native AVFoundation capture of the direct patches also has near-linear luma: RMS 0.425, output 17–234. Cb/Cr RMS are 0.512/0.502, output 16–239. The Composite NTSC attachment is unchanged. Native range conversion is separate from raw libuvc evidence.

## Corrected interpretation

The direct-native baseline reproduces the earlier near-linear behavior without EDID or EEPROM changes. The earlier curvature belonged to the source rendering path; those data did not establish an internal MS2109 transfer error. The exact AppKit/ColorSync conversion responsible was not isolated. Prior gamma-curve fits and metadata workaround claims must be read with this limitation.

The earlier sRGB flag affected the color-managed PNG path. It is not established as a required firmware correction when drawing native RGB codes. Prepared sRGB firmware remains unflashed and suspended from promotion pending native-renderer source-specific requalification. No new persistent firmware change is justified by the prior PNG result alone.

## Reproduce native patches

Build with `sh tools/build_transfer_helpers.sh` on macOS with Homebrew libuvc. The HDMI TO USB display must be 1920×1080, scale 1, with the screen saver inactive. Run the helper outside the shell sandbox with administrator access:

```sh
sudo /private/tmp/transfer_capture firmware/patterns/endpoint-pattern.json /tmp/native-patch-stats.json -17 148 146
```

This captures two raw YUY2 frames in memory and saves patch statistics only. Previous runtime procamp is restored. Native camera metadata capture uses the camera-declared app built by the same script and requires camera permission; its samples may be range converted by AVFoundation. No desktop capture is needed.

Numerical evidence is in `native-patch-baseline.json`. Firmware promotion does not flash the connected device. The release changes only startup values and the code checksum in the pinned qualified baseline; `firmware/base/qualified-eeprom.json` lists exact changed bytes. Preserve a fresh device EEPROM backup before any separately authorized flashing.
