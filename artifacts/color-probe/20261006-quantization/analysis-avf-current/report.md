# Measured 8-bit quantization ramps

Every code 0..255 on gray and each RGB primary ramp; not exhaustive RGB triplets

Central 8×8 pixels from eight frames give 512 pixel samples per input code. Counts below describe these ramps, not effective bit depth over arbitrary RGB combinations.

| Capture | Ramp | Endpoints Y/Cb/Cr | Unique median Y/Cb/Cr codes | Unique YUV triplets | Adjacent equal triplets |
|---|---|---|---|---:|---:|
| avf-current-decoded | gray | [30.0, 128.0, 128.0] → [218.0, 128.0, 128.0] | [189, 1, 1] | 189 | 67 |
| avf-current-decoded | red | [30.0, 128.0, 128.0] → [69.0, 105.0, 226.0] | [40, 24, 99] | 132 | 124 |
| avf-current-decoded | green | [30.0, 128.0, 128.0] → [164.0, 52.0, 38.0] | [135, 77, 91] | 201 | 55 |
| avf-current-decoded | blue | [30.0, 128.0, 128.0] → [43.0, 226.0, 119.0] | [14, 99, 10] | 106 | 150 |
| avf-current-yuy2 | gray | [16.0, 128.0, 128.0] → [235.0, 128.0, 128.0] | [220, 1, 1] | 220 | 36 |
| avf-current-yuy2 | red | [16.0, 128.0, 128.0] → [62.0, 102.0, 238.5] | [47, 39, 127] | 169 | 87 |
| avf-current-yuy2 | green | [16.0, 128.0, 128.0] → [172.0, 41.0, 26.0] | [157, 104, 124] | 228 | 28 |
| avf-current-yuy2 | blue | [16.0, 128.0, 128.0] → [31.0, 238.5, 117.5] | [16, 127, 22] | 145 | 111 |

Full pixel-code histograms: [histograms.json](histograms.json). Each capture has a CSV containing all 256 levels on each ramp. YUV samples and explicit reconstructed RGB are retained separately.

The RGB reference is the AppKit source render in the active display profile, before late compositor/HDMI processing. JPEG decompression uses YCbCr output with no RGB matrix or range conversion.
