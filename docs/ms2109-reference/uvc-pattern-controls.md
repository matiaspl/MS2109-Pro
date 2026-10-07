# Exposing the MS2109 pattern selector as a UVC control

Return to the [reference index](README.md) and [pattern register findings](no-signal-patterns.md). This is an implementation feasibility assessment based on the saved ROM/EEPROM, a temporary live signal-on FEBA test, and official host-driver documentation.

## What the chip currently exposes

The saved ROM's active configuration descriptor is 1,211 bytes (`wTotalLength=0x04BB`) at CODE `0x7111`. Walking its descriptor chain identifies VideoControl interface 0 with a VC Header, Camera Input Terminal, Processing Unit, and Output Terminal. There is no VideoControl Extension Unit descriptor. The existing Processing Unit exposes standard UVC controls; a vendor pattern selector is not among the enumerated color descriptors.

ROM gate `0x4788–0x4797` chooses between the EEPROM hook at `CC10` (when `CBD4.1` is set) and the built-in USB request handler `2AD0`. The installed EEPROM flags are `05`, so this request hook is disabled. The same `CC10` address is used by the factory video callback: command `08` tail-calls `CC10` with a table pointer, and the callback delegates to ROM `6345`. A custom XU handler must preserve or multiplex that existing call. See [callback mapping](callbacks.md#the-cc10-collision).

## A firmware route

The pattern value is a natural one-byte menu control backed by XDATA `FEBA` bits 4:0. The live signal-on probe showed that setting FEBA=08 while HDMI is active leaves the active HDMI picture unchanged; the control would choose the **no-signal fallback** only. An XU implementation would need to:

1. Add a VideoControl Extension Unit to the UVC descriptor topology, with a stable unit ID, unique GUID, control bitmap and updated descriptor lengths.
2. Route its class-specific interface requests through a custom `CC10` setup handler while preserving the current `CC10` video-table callback behavior.
3. Implement the required XU query requests (`GET_INFO`, `GET_LEN`, `GET_MIN`, `GET_MAX`, `GET_RES`, `GET_DEF`, `GET_CUR`) and `SET_CUR`; validate the menu value before writing FEBA.
4. Test the control across enumeration, streaming, signal loss and recovery. Choosing FEBA=08 during an active HDMI stream did not alter visible pixels, even though FEBA remained 08 through capture.

The XU descriptor is the major gap. A normal EEPROM code change alone cannot make a host discover a control whose entity is missing from the advertised VideoControl graph. The ROM owns the current descriptor table; its request-hook behavior and any feasible way to replace or extend the configuration descriptor need additional static analysis before implementation. The existing CC10 hook can replace request handling, but that fact alone does not prove it can rewrite standard GET_DESCRIPTOR responses safely.

## What Windows and Linux would show

An arbitrary vendor XU does not automatically become a slider or menu in a universal operating-system camera settings page.

| Host | Device-side route | User interface expectation |
|---|---|---|
| Windows | Advertise an XU and implement its query/set requests. Windows exposes XU properties through its UVC/KS interfaces; a vendor proxy or application can present the pattern menu. | The built-in Camera Settings page lists supported standard imaging controls and selected Microsoft-defined extended controls. A custom FEBA menu should be expected in a companion/vendor UI unless it is deliberately represented as a standard control. Microsoft's predefined camera XU control set does not define this MS2109 test-pattern menu. |
| Linux | Advertise and implement the XU. `uvcvideo` supports direct XU queries and runtime mappings from XU fields to V4L2 controls. | After mapping, V4L2-aware tools can present an ordinary menu control. Mapping/setup is host-side and is not guaranteed to appear in every camera application. |

For compatibility, expose the observed patterns as an enumeration menu and preserve the raw FEBA value internally. Avoid repurposing a standard control such as hue or saturation: that would mislabel the feature and risk host software rewriting the value as part of ordinary picture-control initialization.

Microsoft documents XU controls and their GET/SET requirements in [Device Requirements for USB Video Class Extension Units](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/device-requirements-for-usb-video-class-extension-units), and describes host access through the Windows UVC driver in its [USB Video Class Driver Overview](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/usb-video-class-driver-overview). The built-in [Camera Settings page](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/camera-settings-page) lists standard/basic settings. Linux documents [UVC extension units and V4L2 mappings](https://docs.kernel.org/6.0/userspace-api/media/drivers/uvcvideo.html).

## Signal-on result

Two baseline → FEBA=08 → restored sequences were run with HDMI active. In both, baseline and FEBA=08 frames were pixel-identical across the image area. The repeat read FEBA=08 after capture, then restored FEBA=00; the EEPROM was unchanged. See the [live signal-on report](../2026-10-06_ms2109-feba-signal-on-report.md). This supports automatic input-path selection that uses the internal pattern generator only for no-signal output. It does not identify a separate pattern-override bit or prove that such an override exists.
