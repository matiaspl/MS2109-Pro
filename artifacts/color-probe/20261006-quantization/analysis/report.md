# Measured 8-bit quantization ramps

Every code 0..255 on gray and each RGB primary ramp; not exhaustive RGB triplets

Central 8×8 pixels from eight frames give 512 pixel samples per input code. Counts below describe these ramps, not effective bit depth over arbitrary RGB combinations.

| Capture | Ramp | Median endpoints Y/Cb/Cr | Unique median YUV triplets | Unique patch-mean triplets | Unique raw pixel codes Y/Cb/Cr | Adjacent equal medians |
|---|---|---|---:|---:|---|---:|
| avf-current-decoded | gray | [30.0, 128.0, 128.0] → [218.0, 128.0, 128.0] | 189 | 189 | [189, 1, 1] | 67 |
| avf-current-decoded | red | [30.0, 128.0, 128.0] → [69.0, 105.0, 226.0] | 132 | 132 | [40, 24, 99] | 124 |
| avf-current-decoded | green | [30.0, 128.0, 128.0] → [164.0, 52.0, 38.0] | 201 | 201 | [135, 77, 91] | 55 |
| avf-current-decoded | blue | [30.0, 128.0, 128.0] → [43.0, 226.0, 119.0] | 106 | 106 | [14, 99, 10] | 150 |
| avf-current-yuy2 | gray | [16.0, 128.0, 128.0] → [235.0, 128.0, 128.0] | 220 | 238 | [221, 1, 1] | 36 |
| avf-current-yuy2 | red | [16.0, 128.0, 128.0] → [62.0, 102.0, 238.5] | 169 | 174 | [48, 27, 112] | 87 |
| avf-current-yuy2 | green | [16.0, 128.0, 128.0] → [172.0, 41.0, 26.0] | 228 | 233 | [157, 88, 103] | 28 |
| avf-current-yuy2 | blue | [16.0, 128.0, 128.0] → [31.0, 238.5, 117.5] | 145 | 152 | [18, 112, 12] | 111 |
| usb-current-mjpeg | gray | [16.0, 128.0, 128.0] → [235.0, 128.0, 128.0] | 220 | 220 | [220, 1, 1] | 36 |
| usb-current-mjpeg | red | [16.0, 128.0, 128.0] → [62.0, 102.0, 239.0] | 149 | 149 | [47, 27, 112] | 107 |
| usb-current-mjpeg | green | [16.0, 128.0, 128.0] → [172.0, 41.0, 26.0] | 220 | 220 | [157, 88, 103] | 36 |
| usb-current-mjpeg | blue | [16.0, 128.0, 128.0] → [31.0, 239.0, 118.0] | 120 | 120 | [16, 112, 11] | 136 |
| usb-current-yuy2 | gray | [16.0, 128.0, 128.0] → [235.0, 128.0, 128.0] | 220 | 238 | [221, 1, 1] | 36 |
| usb-current-yuy2 | red | [16.0, 128.0, 128.0] → [62.0, 102.0, 238.5] | 169 | 174 | [48, 27, 112] | 87 |
| usb-current-yuy2 | green | [16.0, 128.0, 128.0] → [172.0, 41.0, 26.0] | 228 | 233 | [157, 88, 103] | 28 |
| usb-current-yuy2 | blue | [16.0, 128.0, 128.0] → [31.0, 238.5, 117.5] | 145 | 152 | [18, 112, 12] | 111 |
| usb-ui127-mjpeg | gray | [14.0, 128.0, 128.0] → [232.0, 128.0, 128.0] | 219 | 219 | [219, 1, 1] | 37 |
| usb-ui127-mjpeg | red | [14.0, 128.0, 128.0] → [60.0, 102.0, 239.0] | 152 | 152 | [47, 27, 112] | 104 |
| usb-ui127-mjpeg | green | [14.0, 128.0, 128.0] → [169.0, 41.0, 26.0] | 221 | 221 | [156, 88, 103] | 35 |
| usb-ui127-mjpeg | blue | [14.0, 128.0, 128.0] → [30.0, 239.0, 118.0] | 117 | 117 | [17, 112, 11] | 139 |
| usb-ui127-yuy2 | gray | [14.0, 128.0, 128.0] → [232.0, 128.0, 128.0] | 220 | 236 | [219, 1, 1] | 36 |
| usb-ui127-yuy2 | red | [14.0, 128.0, 128.0] → [60.0, 102.0, 238.5] | 165 | 172 | [48, 27, 112] | 91 |
| usb-ui127-yuy2 | green | [14.0, 128.0, 128.0] → [169.0, 41.0, 26.0] | 229 | 235 | [156, 88, 103] | 27 |
| usb-ui127-yuy2 | blue | [14.0, 128.0, 128.0] → [29.0, 238.5, 117.5] | 145 | 150 | [18, 112, 12] | 111 |

Full pixel-code histograms: [histograms.json](histograms.json). Each capture has a CSV containing all 256 levels on each ramp. YUV samples and explicit reconstructed RGB are retained separately.

The RGB reference is the AppKit source render in the active display profile, before late compositor/HDMI processing. JPEG decompression uses YCbCr output with no RGB matrix or range conversion.
