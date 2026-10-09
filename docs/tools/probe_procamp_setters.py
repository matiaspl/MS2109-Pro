#!/usr/bin/env python3
"""Reversibly verify live UVC brightness/contrast/hue/saturation SET_CUR."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ms2109_hid import Device

CONTROLS = {
    "brightness": {"selector": 2, "signed": True},
    "contrast": {"selector": 3, "signed": False},
    "hue": {"selector": 6, "signed": True},
    "saturation": {"selector": 7, "signed": False},
}


def next_value(current: int, minimum: int, maximum: int) -> int | None:
    if current < maximum:
        return current + 1
    if current > minimum:
        return current - 1
    return None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UVC:
    def __init__(self):
        self.lib = C.CDLL("/opt/homebrew/lib/libusb-1.0.dylib")
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p, C.c_uint16, C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [C.c_void_p, C.c_uint8, C.c_uint8,
            C.c_uint16, C.c_uint16, C.POINTER(C.c_ubyte), C.c_uint16, C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc:
            raise RuntimeError(f"libusb_init failed: {rc}")
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx, 0x534D, 0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError("Could not open enumerated MS2109 for UVC control requests")

    def transfer(self, bm: int, request: int, selector: int, payload: bytes = b"") -> dict:
        length = len(payload) if bm == 0x21 else 2
        buf = (C.c_ubyte * max(1, length))()
        for index, value in enumerate(payload):
            buf[index] = value
        rc = self.lib.libusb_control_transfer(self.handle, bm, request,
            selector << 8, 0x0200, buf, length, 3000)
        return {"return_code": int(rc), "data_hex": bytes(buf[:max(0, rc)]).hex()}

    def get(self, selector: int, request: int) -> bytes:
        result = self.transfer(0xA1, request, selector)
        if result["return_code"] != 2:
            raise RuntimeError(f"UVC GET selector {selector} request {request:02X} failed: {result}")
        return bytes.fromhex(result["data_hex"])

    def set(self, selector: int, data: bytes) -> dict:
        return self.transfer(0x21, 1, selector, data)

    def close(self):
        if getattr(self, "handle", None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self, "ctx", None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def read_eeprom_twice(device: Device) -> bytes:
    size = device.identify_eeprom()
    first, second = device.read("eeprom", 0, size), device.read("eeprom", 0, size)
    if first != second:
        raise RuntimeError("Two EEPROM reads disagree")
    return first


def run(output: Path) -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    device = Device()
    uvc = None
    result = {"scope": "volatile UVC SET_CUR probe; no EEPROM writes",
              "controls": {}, "restoration": {"attempted": False}}
    saved_controls = {}
    saved_ranges = {}
    eeprom_before = None
    try:
        eeprom_before = read_eeprom_twice(device)
        result["eeprom_sha256_before"] = sha(eeprom_before)
        for address, count in ((0xC6A0, 8), (0xFE90, 4)):
            saved_ranges[address] = device.read("ram", address, count)
        result["procamp_ram_before"] = {f"{address:04X}": data.hex()
                                         for address, data in saved_ranges.items()}
        uvc = UVC()
        for name, spec in CONTROLS.items():
            selector, signed = spec["selector"], spec["signed"]
            current = uvc.get(selector, 0x81)
            minimum, maximum = uvc.get(selector, 0x82), uvc.get(selector, 0x83)
            current_value = int.from_bytes(current, "little", signed=signed)
            min_value = int.from_bytes(minimum, "little", signed=signed)
            max_value = int.from_bytes(maximum, "little", signed=signed)
            saved_controls[selector] = current
            candidate = next_value(current_value, min_value, max_value)
            item = {"selector": selector, "signed": signed,
                    "cur_before_hex": current.hex(), "current": current_value,
                    "min": min_value, "max": max_value,
                    "set_supported": None, "cur_after_set_hex": None,
                    "candidate": candidate}
            if candidate is not None:
                sent = uvc.set(selector, candidate.to_bytes(2, "little", signed=signed))
                item["set_request"] = sent
                item["set_supported"] = sent["return_code"] == 2
                if item["set_supported"]:
                    current_after = uvc.get(selector, 0x81)
                    item["cur_after_set_hex"] = current_after.hex()
                    item["cur_after_set"] = int.from_bytes(current_after, "little", signed=signed)
                    item["value_changed"] = item["cur_after_set"] == candidate
            result["controls"][name] = item
            # Restore immediately before moving to the next control.
            restored = uvc.set(selector, current)
            item["restore_request"] = restored
            item["cur_after_restore_hex"] = uvc.get(selector, 0x81).hex()
            item["restored"] = item["cur_after_restore_hex"] == current.hex()
        result["procamp_ram_after_controls"] = {
            f"{address:04X}": device.read("ram", address, len(data)).hex()
            for address, data in saved_ranges.items()}
        result["procamp_ram_matches_after_uvc_restore"] = all(
            device.read("ram", address, len(data)) == data
            for address, data in saved_ranges.items())
        result["status"] = ("passed" if all(item.get("set_supported") and
                                             item.get("value_changed") and item.get("restored")
                                             for item in result["controls"].values())
                            else "failed: one or more UVC picture-control writes did not round-trip")
    finally:
        result["restoration"]["attempted"] = True
        if uvc is not None:
            for selector, value in saved_controls.items():
                try:
                    result["restoration"][f"selector_{selector:02X}"] = uvc.set(selector, value)
                except Exception as exc:
                    result["restoration"][f"selector_{selector:02X}_error"] = str(exc)
            uvc.close()
        for address, data in saved_ranges.items():
            for offset, value in enumerate(data):
                device.exchange(0xB6, address + offset, value)
        result["restoration"]["ram_ranges_match"] = all(
            device.read("ram", address, len(data)) == data
            for address, data in saved_ranges.items())
        eeprom_after = read_eeprom_twice(device)
        result["eeprom_sha256_after"] = sha(eeprom_after)
        result["eeprom_unchanged"] = eeprom_after == eeprom_before
        if not result["restoration"]["ram_ranges_match"] or not result["eeprom_unchanged"]:
            result["status"] = "FAILED: runtime restoration or EEPROM verification failed"
        device.close()
        output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))


if __name__ == "__main__":
    main()
