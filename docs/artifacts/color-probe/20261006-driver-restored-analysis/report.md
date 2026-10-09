# MS2109 measured color probe

Analysis UTC: 2026-10-05T22:27:11.383325+00:00

96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.

| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |
|---|---|---|---:|---|---|
| 20261006-driver-restored-yuy2 | yuvs 5.00 fps | 709 limited | 0.759 | [16.0, 128.0, 128.0] | [235.0, 128.0, 128.0] |

## 20261006-driver-restored-yuy2

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | limited | 0.759 | 0.557 |
| 2020 | limited | 2.388 | 2.281 |
| 601 | limited | 5.585 | 5.470 |
| 709 | full | 7.297 | 5.286 |
| 2020 | full | 7.360 | 5.794 |
| 601 | full | 8.022 | 7.377 |

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.551 YUV codes.

Evidence: [20261006-driver-restored-yuy2/capture.json](20261006-driver-restored-yuy2/capture.json), [20261006-driver-restored-yuy2/analysis.json](20261006-driver-restored-yuy2/analysis.json), [20261006-driver-restored-yuy2/patches.csv](20261006-driver-restored-yuy2/patches.csv).

## Interpretation boundaries

Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.

An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.

No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.

Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m).
