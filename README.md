# MS2109-Pro

MS2109-Pro is firmware for an MS2109 HDMI-to-USB capture device. It sends video to a computer as a standard UVC camera and audio as a USB audio input.

## What this firmware fixes

| Original device behavior | Firmware change | Result |
| --- | --- | --- |
| The 1080p MJPEG descriptor offered 60 fps, outside the tested operating profile. | Replaces the 60 fps interval with a duplicate 30 fps entry. | Apps list 30, 25, 20, and 10 fps at 1080p MJPEG. The default is 30 fps. |
| The high-speed descriptor reported BT.601, while the tested output matched BT.709. Neutral controls produced Y 16–235 and Cb/Cr about 16–239 on the test chart. | Reports BT.709 and loads calibrated brightness, contrast, saturation, and hue values. | The tested chart reached Y 0–255 and Cb/Cr 1–254. Set the host pipeline to BT.709 full range. |
| With the tested HDMI source, USB left/right channel order did not match source left/right. | Sets stereo routing and a 48 kHz USB audio stream. | Source left goes to USB left and source right to USB right. A one-sample timing offset remains. |
| The device used the generic `usb video` name. | Writes `MS2109-Pro` into the EEPROM video and audio name records. | After a power cycle, the host reports the USB product name as `MS2109-Pro`. |

These results describe the tested capture device and signal path. They do not establish behavior for every MS2109 board or HDMI source.

## Quick start

1. Connect an HDMI source to the capture device.
2. Connect the device to your computer by USB.
3. Open your video or streaming application.
4. Select **MS2109-Pro** as the camera and audio input.
5. Select a video format and frame rate that match your project.
6. Check the image with color bars or a waveform monitor before recording or streaming.

The device was tested with macOS. It uses standard UVC video and USB audio interfaces, but each operating system and application can expose different settings.

## Video modes

The capture device provides YUY2 and MJPEG video. YUY2 sends uncompressed 4:2:2 video. MJPEG sends compressed JPEG frames.

At 1920×1080, MJPEG supports 30, 25, 20, and 10 fps. The device advertises two 30 fps entries, so some applications can show 30 fps twice. The default rate is 30 fps.

Other resolutions and frame rates depend on the device descriptors and your application. Select a mode that both the HDMI source and capture application support.

## Color setup

The high-speed YUY2 and MJPEG descriptors report the BT.709 color matrix. The firmware targets full-range video. On the tested color chart, it produced Y values from 0 to 255 and Cb/Cr values from 1 to 254.

The USB video descriptor does not signal full or limited range. Set the capture application and downstream video path to interpret the signal as BT.709 full range when those options are available. Check the result with bars or scopes. Incorrect range handling can make blacks look gray or clip highlights.

MJPEG decoders can ignore the BT.709 metadata and use their own color defaults. Confirm the decoded image in the application you use for production.

The measurements cover one tested HDMI source and a 96-patch chart. They do not qualify every source, input format, or color value.

## Picture controls

The firmware loads these values at startup:

| Control | Startup value |
| --- | ---: |
| Brightness | 110 (signed value −18) |
| Contrast | 149 |
| Saturation | 147 |
| Hue | 0 |

The standard UVC control requests remain available. This firmware does not add a Sharpness control.

## Audio

The USB audio input is stereo at 48 kHz. The tested HDMI source's left channel goes to USB left, and its right channel goes to USB right. A one-sample timing offset remains between channels.

Select **MS2109-Pro** as the audio input in your capture application. Check channel order and sync with your own source before a production.

## Limits to plan for

- The USB video descriptor does not identify full or limited range. Set the host pipeline to match the signal.
- The firmware does not add a UVC Sharpness control or change the hardware scaler.
- The measured one-sample audio timing offset remains.
- Color measurements cover one device, one HDMI source, and a 96-patch chart. Other HDMI input formats and sources can behave differently.

## Firmware image

The firmware file is a 2 KiB EEPROM image for the MS2109 capture device.

| File | Size | SHA-256 |
| --- | ---: | --- |
| [`firmware/ms2109-pro.bin`](firmware/ms2109-pro.bin) | 2,048 bytes | `f55da7863def4ee19d338d07ae75024244316bd6226d87018f301db23f9226b7` |

Use this image only with an MS2109 device. Before you update EEPROM, save a full backup and make sure the image matches your device and programming method.
