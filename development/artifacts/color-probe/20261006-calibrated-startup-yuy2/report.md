# MS2109 measured color probe

Analysis UTC: 2026-10-05T23:54:35.090330+00:00

96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.

| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |
|---|---|---|---:|---|---|
| native-yuv | yuvs 5.00 fps | 709 full | 0.800 | [0.0, 128.0, 128.0] | [255.0, 128.0, 128.0] |

## native-yuv

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | full | 0.800 | 0.633 |
| 2020 | full | 2.736 | 2.636 |
| 601 | full | 6.437 | 6.296 |
| 709 | limited | 7.047 | 5.466 |
| 2020 | limited | 7.739 | 5.968 |
| 601 | limited | 10.291 | 8.477 |

Mac color state: `{"api": "CoreBrightness private API; interpretation guarded by runtime type encoding", "night_shift_api_auto_enabled": 1, "night_shift_api_limitation": "This flag reported zero during the user-confirmed enabled baseline. Do not use it to infer whether Night Shift affects the output.", "night_shift_api_reported_enabled": 0, "night_shift_api_sun_schedule_allowed": 1, "night_shift_configured_cct_kelvin": 4100, "night_shift_effect_state_verified": false, "night_shift_status_hex": "01000100000000001600000000000000070000000000000000000000000000000100000000000000", "night_shift_status_read_ok": true, "night_shift_strength": 0.5, "status_field_validation": "Dictionary field mapping only: AutoBlueReductionEnabled byte 0; BlueReductionEnabled byte 1. Does not establish visual effect activity.", "status_type_encoding": "B24@0:8^{?=BBBi{?={?=ii}{?=ii}}QB}16", "true_tone_enabled": false}`.

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.603 YUV codes.

Evidence: [native-yuv/capture.json](native-yuv/capture.json), [native-yuv/analysis.json](native-yuv/analysis.json), [native-yuv/patches.csv](native-yuv/patches.csv).

## Interpretation boundaries

Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.

An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.

No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.

Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m).
