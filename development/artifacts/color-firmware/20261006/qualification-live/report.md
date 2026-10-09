# MS2109 color-path qualification capture

Source display profile: HDMI TO USB; chart/source RGB RMSE 0.000.
The getter/control/order trials reopen the UVC handle per format. A separate same-handle trial captures MJPEG then YUY2 before closing the handle. The paired trials record GET_CUR or all GET_CUR/MIN/MAX/RES/DEF calls; reapply-current uses SET_CUR with the same values and verifies restoration.

| Trial | Format | Getter/control profile | Nominal / observed callback fps | YUV RMSE Y/Cb/Cr | YUV range Y/Cb/Cr |
|---|---|---|---:|---|---|
| all-getters-mjpeg-first | yuy2 | GET_CUR/MIN/MAX/RES/DEF / untouched | 5.0 / 4.98 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| all-getters-mjpeg-first | mjpeg | GET_CUR/MIN/MAX/RES/DEF / untouched | 30.00003000003 / 30.97 | [0.5325893638630029, 1.025577126511337, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| all-getters-yuy2-first | yuy2 | GET_CUR/MIN/MAX/RES/DEF / untouched | 5.0 / 4.98 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| all-getters-yuy2-first | mjpeg | GET_CUR/MIN/MAX/RES/DEF / untouched | 30.00003000003 / 31.43 | [0.5325893638630029, 1.0259649562264357, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| get-cur-only-mjpeg-first | yuy2 | GET_CUR only / untouched | 5.0 / 5.00 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| get-cur-only-mjpeg-first | mjpeg | GET_CUR only / untouched | 30.00003000003 / 31.24 | [0.5325893638630029, 1.0259649562264357, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reapply-current-mjpeg-first | yuy2 | GET_CUR only / reapplied current values | 5.0 / 4.99 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reapply-current-mjpeg-first | mjpeg | GET_CUR only / reapplied current values | 30.00003000003 / 29.83 | [0.5325893638630029, 1.025577126511337, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reconnect-attempt-4-cycle-1 | yuy2 | GET_CUR only / untouched | 5.0 / 5.01 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reconnect-attempt-4-cycle-1 | mjpeg | GET_CUR only / untouched | 30.00003000003 / 31.06 | [0.5325893638630029, 1.0264309460018288, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reconnect-attempt-4-cycle-2 | yuy2 | GET_CUR only / untouched | 5.0 / 5.00 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reconnect-attempt-4-cycle-2 | mjpeg | GET_CUR only / untouched | 30.00003000003 / 30.89 | [0.5325893638630029, 1.0264309460018288, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| reconnect-attempt-4-cycle-3 | yuy2 | GET_CUR only / untouched | 5.0 / 5.00 | [27.466183495445815, 43.12886149175559, 40.764120826088295] | [[0.0, 255.0], [36.0, 254.0], [5.0, 254.0]] |
| reconnect-attempt-4-cycle-3 | mjpeg | GET_CUR only / untouched | 30.00003000003 / 30.30 | [0.5325893638630029, 1.0259649562264357, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| same-handle | yuy2 | GET_CUR only / untouched | 5.0 / 4.99 | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |
| same-handle | mjpeg | GET_CUR only / untouched | 30.00003000003 / 30.49 | [0.5325893638630029, 1.0259649562264357, 1.0416310754881282] | [[0.0, 255.0], [1.0, 254.0], [1.0, 254.0]] |

Superseded reconnect captures are retained in `raw/` but excluded from these metrics: reconnect-attempt-3-cycle-1, reconnect-attempt-3-cycle-2, reconnect-attempt-3-cycle-3. They used the earlier normal-level chart setup, which let the menu bar cover chart patches.

## Reconnect startup frames

| Cycle | Format | First frame YUV RMSE Y/Cb/Cr | Following frames median RMSE (temporal span) | Per-frame Y/Cb/Cr RMSE in capture order | Display profile generation |
|---|---|---|---|---|---|
| reconnect-1 | yuy2 | [34.690815940204764, 28.26330397648929, 31.894482947990976] | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] (span 0.0) | 0:34.7/28.3/31.9; 1:0.6/1.0/1.1; 2:0.6/1.0/1.1; 3:0.6/1.0/1.1; 4:0.6/1.0/1.1; 5:0.6/1.0/1.1; 6:0.6/1.0/1.1; 7:0.6/1.0/1.1 | 1 |
| reconnect-1 | mjpeg | [0.5325893638630029, 1.0264309460018288, 1.0402396283873592] | [0.5325893638630029, 1.0264309460018288, 1.0435822849098384] (span 0.5) | 0:0.5/1.0/1.0; 1:0.5/1.0/1.0; 2:0.5/1.0/1.0; 3:0.5/1.0/1.0; 4:0.5/1.0/1.0; 5:0.5/1.0/1.0; 6:0.5/1.0/1.0; 7:0.5/1.0/1.0 | 1 |
| reconnect-2 | yuy2 | [61.42277677493093, 79.83455836242756, 68.71584867994207] | [0.5648374335446714, 1.0361465160583088, 1.0552561188203102] (span 0.0) | 0:61.4/79.8/68.7; 1:0.6/1.0/1.1; 2:0.6/1.0/1.1; 3:0.6/1.0/1.1; 4:0.6/1.0/1.1; 5:0.6/1.0/1.1; 6:0.6/1.0/1.1; 7:0.6/1.0/1.1 | 2 |
| reconnect-2 | mjpeg | [0.5325893638630029, 1.0264309460018288, 1.0402396283873592] | [0.5325893638630029, 1.0264309460018288, 1.0435822849098384] (span 0.5) | 0:0.5/1.0/1.0; 1:0.5/1.0/1.0; 2:0.5/1.0/1.0; 3:0.5/1.0/1.0; 4:0.5/1.0/1.0; 5:0.5/1.0/1.0; 6:0.5/1.0/1.0; 7:0.5/1.0/1.0 | 2 |
| reconnect-3 | yuy2 | [79.39564561405223, 91.40405767811839, 76.52016701121669] | [0.5747466591174446, 28.792841727568824, 24.862049090278287] (span 255.0) | 0:79.4/91.4/76.5; 1:86.8/73.2/78.3; 2:79.4/91.4/76.5; 3:86.8/73.2/78.3; 4:101.8/50.1/53.3; 5:0.6/1.0/1.1; 6:0.6/1.0/1.1; 7:0.6/1.0/1.1 | 3 |
| reconnect-3 | mjpeg | [0.5325893638630029, 1.025625717582141, 1.0402396283873592] | [0.5325893638630029, 1.0264309460018288, 1.0435822849098384] (span 0.5) | 0:0.5/1.0/1.0; 1:0.5/1.0/1.0; 2:0.5/1.0/1.0; 3:0.5/1.0/1.0; 4:0.5/1.0/1.0; 5:0.5/1.0/1.0; 6:0.5/1.0/1.0; 7:0.5/1.0/1.0 | 3 |

AVFoundation BGRA auto-conversion RGB RMSE: 7.752 codes; channel RMSE [7.625350060270457, 7.912929490713284, 7.714257295747919].
AVFoundation packed YUV BT.709/full per-channel RMSE: [0.5648374335446714, 1.0361465160583088, 1.0552561188203102].
The best tested YUV-to-BGRA model was 709_limited: 0.381 RGB-code RMS from captured BGRA. The BT.709/full decode was 1.378 RMS from the reference but 7.634 from automatic BGRA.
AVFoundation attachments on YUV: {'CVImageBufferColorPrimaries': 'ITU_R_709_2', 'CVImageBufferTransferFunction': 'SMPTE_240M_1995', 'CVImageBufferYCbCrMatrix': 'ITU_R_709_2'}; selected maximum 5 fps, observed 5.00 fps.

Three reconnect cycles were captured. Each format records the first eight frames delivered after stream start following user-confirmed re-enumeration, with no settling delay or picture-control writes. The first frame is reported separately from the following seven; first-frame color gate: failed: one or more first frames exceeded the 1.5-code per-channel YUV RMSE limit. This measures first captured frames after reconnect, not USB-bus SOF frames.

## Stereo audio preservation

Fresh read-only fixture: FE60 remained 01; live audio descriptor reports 2 channels at 48 kHz, with `HDMI TO USB` as the 48 kHz default output. Channel 0 had 995.7 Hz and 0.0% silent windows; channel 1 had 995.7 Hz and 22.1% silent windows. This verifies continuous left and gapped right routing. The strongest inter-channel correlation was at lag -1 sample (0.980); the known one-sample offset remains.
Evidence: [`stereo-current-fe60.wav`](stereo-current-fe60.wav), [`stereo-current-fe60.analysis.json`](stereo-current-fe60.analysis.json), and [`stereo-current-fe60.json`](stereo-current-fe60.json). No register or firmware writes were made.
