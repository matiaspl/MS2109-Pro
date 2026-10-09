# MS2109 measured color probe

Analysis UTC: 2026-10-06T00:03:38.950179+00:00

96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.

| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |
|---|---|---|---:|---|---|
| yuv-yuv | yuvs 5.00 fps | 709 full | 0.800 | [0.0, 128.0, 128.0] | [255.0, 128.0, 128.0] |
| avf420v-yuv | 420v 30.00 fps | 709 limited | 0.740 | [16.0, 128.0, 128.0] | [235.0, 128.0, 128.0] |

## yuv-yuv

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | full | 0.800 | 0.633 |
| 2020 | full | 2.736 | 2.636 |
| 601 | full | 6.437 | 6.296 |
| 709 | limited | 7.047 | 5.466 |
| 2020 | limited | 7.739 | 5.968 |
| 601 | limited | 10.291 | 8.477 |

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.603 YUV codes.

Evidence: [yuv-yuv/capture.json](yuv-yuv/capture.json), [yuv-yuv/analysis.json](yuv-yuv/analysis.json), [yuv-yuv/patches.csv](yuv-yuv/patches.csv).

## avf420v-yuv

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | limited | 0.740 | 0.583 |
| 2020 | limited | 2.412 | 2.351 |
| 601 | limited | 5.611 | 5.514 |
| 709 | full | 7.181 | 5.241 |
| 2020 | full | 7.256 | 5.780 |
| 601 | full | 7.940 | 7.377 |

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.597 YUV codes.

Evidence: [avf420v-yuv/capture.json](avf420v-yuv/capture.json), [avf420v-yuv/analysis.json](avf420v-yuv/analysis.json), [avf420v-yuv/patches.csv](avf420v-yuv/patches.csv).

## Interpretation boundaries

Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.

An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.

No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.

Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m).
