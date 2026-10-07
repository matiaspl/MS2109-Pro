# MS2109 measured color probe

Analysis UTC: 2026-10-05T22:34:59.031733+00:00

96 RGB patches on the 1920×1080 HDMI TO USB extended display. Values below are medians of each patch interior across stable frames. A smaller direct YUV residual indicates a closer matrix/range model. Source RGB means the AppKit render in the active display profile; late white-point adjustments can change the HDMI pixels.

| Run | Active format | Best direct model | YUV RMSE (codes) | Gray black Y/Cb/Cr | Gray white Y/Cb/Cr |
|---|---|---|---:|---|---|
| native-avf420v | 420v 30.00 fps | 709 limited | 6.307 | [30.0, 128.0, 128.0] | [218.0, 128.0, 128.0] |
| srgb-avf420v | 420v 30.00 fps | 2020 limited | 6.121 | [30.0, 128.0, 128.0] | [217.0, 128.0, 128.0] |

## native-avf420v

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 709 | limited | 6.307 | 4.559 |
| 2020 | limited | 6.366 | 5.007 |
| 601 | limited | 6.944 | 6.379 |
| 601 | full | 12.817 | 10.690 |
| 2020 | full | 13.218 | 10.140 |
| 709 | full | 13.374 | 9.892 |

Mac color state: `{"api": "CoreBrightness private API; interpretation guarded by runtime type encoding", "night_shift_api_auto_enabled": true, "night_shift_api_limitation": "BlueReductionEnabled=0 was observed during the user-confirmed enabled baseline. The dictionary mapping does not establish visual effect activity.", "night_shift_api_reported_enabled": false, "night_shift_api_sun_schedule_allowed": true, "night_shift_configured_cct_kelvin": 4100, "night_shift_effect_state_verified": false, "night_shift_status_hex": "01000100000000001600000000000000070000000000000000000000000000000100000000000000", "night_shift_status_read_ok": true, "night_shift_strength": 0.5, "previous_incorrect_night_shift_active": 1, "status_field_validation": "Dictionary field mapping only; visual effect activity not verified.", "status_type_encoding": "B24@0:8^{?=BBBi{?={?=ii}{?=ii}}QB}16", "true_tone_enabled": false, "user_reported_color_state": {"night_shift_enabled": false, "true_tone_enabled": false}, "user_reported_timeline": "After disable event"}`.

Source render/reference RMSE: 0.000 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.505 YUV codes.

Evidence: [native-avf420v/capture.json](native-avf420v/capture.json), [native-avf420v/analysis.json](native-avf420v/analysis.json), [native-avf420v/patches.csv](native-avf420v/patches.csv).

## srgb-avf420v

| Matrix | Range | Direct YUV RMSE | RGB gain fit, holdout YUV RMSE |
|---|---|---:|---:|
| 2020 | limited | 6.121 | 4.875 |
| 709 | limited | 6.233 | 4.736 |
| 601 | limited | 6.356 | 5.670 |
| 601 | full | 12.111 | 10.170 |
| 2020 | full | 12.874 | 10.270 |
| 709 | full | 13.189 | 10.298 |

Mac color state: `{"api": "CoreBrightness private API; interpretation guarded by runtime type encoding", "night_shift_api_auto_enabled": true, "night_shift_api_limitation": "BlueReductionEnabled=0 was observed during the user-confirmed enabled baseline. The dictionary mapping does not establish visual effect activity.", "night_shift_api_reported_enabled": false, "night_shift_api_sun_schedule_allowed": true, "night_shift_configured_cct_kelvin": 4100, "night_shift_effect_state_verified": false, "night_shift_status_hex": "01000100000000001600000000000000070000000000000000000000000000000100000000000000", "night_shift_status_read_ok": true, "night_shift_strength": 0.5, "previous_incorrect_night_shift_active": 1, "status_field_validation": "Dictionary field mapping only; visual effect activity not verified.", "status_type_encoding": "B24@0:8^{?=BBBi{?={?=ii}{?=ii}}QB}16", "true_tone_enabled": false, "user_reported_color_state": {"night_shift_enabled": false, "true_tone_enabled": false}, "user_reported_timeline": "After disable event"}`.

Source render/reference RMSE: 0.288 RGB codes. Maximum temporal patch span: 0.0 YUV codes. Empirical affine model holdout residual: 0.533 YUV codes.

Evidence: [srgb-avf420v/capture.json](srgb-avf420v/capture.json), [srgb-avf420v/analysis.json](srgb-avf420v/analysis.json), [srgb-avf420v/patches.csv](srgb-avf420v/patches.csv).

## Interpretation boundaries

Neutral gray must have Cb≈128 and Cr≈128 under both 601 and 709. A colored gray ramp therefore needs an explanation beyond a simple 601/709 inverse mismatch. Source-profile conversion, Night Shift/True Tone, input negotiation, and receiver processing are separate stages.

An arbitrary fitted 3×3 transform can fit either standard matrix by absorbing their difference. The direct models and the constrained RGB-gain holdout model are reported separately to avoid that false inference.

No firmware, picture-control registers, display profiles, display modes, or white-point settings are changed by this probe. Capture-session format negotiation is temporary. ScreenCaptureKit framebuffer reference is saved only if Screen Recording permission is already granted; otherwise the reference is the AppKit render.

Matrix equations: [Linux V4L2 color documentation](https://docs.kernel.org/userspace-api/media/v4l/colorspaces-details.html). macOS configuration-lock sequence follows [FFmpeg AVFoundation acquisition](https://github.com/FFmpeg/FFmpeg/blob/master/libavdevice/avfoundation.m).
