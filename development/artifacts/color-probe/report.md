# MS2109 measured color probe

Analysis UTC: 2026-10-05T21:32:32.748519+00:00

96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.

| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |
|---|---|---|---:|---|---|
| native-nightshift-on | yuvs 5.00 fps | 709 limited | 13.646 | [16.0, 128.0, 128.0] | [212.0, 104.0, 141.0] |
| srgb-nightshift-on | yuvs 5.00 fps | 601 limited | 12.663 | [16.0, 128.0, 128.0] | [212.0, 104.0, 141.0] |

## native-nightshift-on

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | limited | 13.646 | 6.918 |
| 2020 | limited | 13.889 | 8.005 |
| 601 | limited | 14.044 | 9.207 |
| 601 | full | 18.110 | 11.718 |
| 709 | full | 18.424 | 10.038 |
| 2020 | full | 18.498 | 10.867 |

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 5.456 YUV codes.

Evidence: [native-nightshift-on/capture.json](native-nightshift-on/capture.json), [native-nightshift-on/analysis.json](native-nightshift-on/analysis.json), [native-nightshift-on/patches.csv](native-nightshift-on/patches.csv).

## srgb-nightshift-on

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 601 | limited | 12.663 | 7.173 |
| 709 | limited | 12.728 | 5.609 |
| 2020 | limited | 12.798 | 6.454 |
| 601 | full | 16.305 | 9.508 |
| 2020 | full | 17.093 | 9.390 |
| 709 | full | 17.225 | 8.947 |

Source render/reference RMSE: 0.288 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 4.150 YUV codes.

Evidence: [srgb-nightshift-on/capture.json](srgb-nightshift-on/capture.json), [srgb-nightshift-on/analysis.json](srgb-nightshift-on/analysis.json), [srgb-nightshift-on/patches.csv](srgb-nightshift-on/patches.csv).

## Interpretation boundaries

Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.

An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.

No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.

Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m).
