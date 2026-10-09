# Direct UVC MJPEG capture

The MS2109-Pro was opened directly with libuvc and asked for 1920×1080 MJPEG at 60 fps while the animated frame counter was shown on the HDMI TO USB display. The capture saved raw JPEG payloads, libuvc frame sequence numbers, and host monotonic callback-arrival times.

## Results

- UVC accepted the 60 fps request with interval `166666` (about 60 fps nominal).
- Of 300 libuvc callbacks, 9 contained complete 1920×1080 JPEG images. The other 291 payloads were only four bytes (`FFD8 FFD9`, an empty JPEG marker).
- The 9 complete images had consecutive motion-counter values 492, 498, 504, …, 540. Their callback timestamps were about 100 ms apart, so visible motion reached the USB JPEG payload at about 10 fps in this run.
- Callback delivery itself was about 32 ms apart and libuvc sequence numbers usually advanced by 2. The complete-image callbacks advanced by 6 sequence numbers.
- A separate 1080p30 baseline saved 90/90 complete JPEGs, with consecutive sequence numbers and about 32 ms callback spacing.
- A 1080p50 request was rejected by libuvc as `Invalid mode (-51)` before streaming.

The helper's `pts_seconds` is a host monotonic timestamp taken after saving each callback. It is not a device PTS. In a timing-instrumented repeat, libuvc's `capture_time` field was zero for every frame; `capture_time_finished` tracked host callback time. The libuvc frame structure used here does not expose the raw UVC PTS/SCR values, so this capture cannot establish device PTS behavior.

The capture only read the current brightness/contrast controls; metadata confirms restoration, and no control SET requests were sent. No firmware or EEPROM state was changed.

See [the 60 fps animated capture](direct-uvc-mjpeg-1080p60-animated-20261009/usb-capture.json), [its timing-instrumented repeat](direct-uvc-mjpeg-1080p60-animated-timing-20261009/usb-capture.json), and [the 30 fps baseline](direct-uvc-mjpeg-1080p30-20261009/usb-capture.json). The four-byte marker callbacks are retained as raw `.jpg` files so the empty-payload pattern can be inspected directly.
