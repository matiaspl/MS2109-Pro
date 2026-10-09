"""Check whether the active descriptor RAM byte is sampled at USB re-enumeration.

This uses a reversible one-byte XDATA edit and a USB device reset. It never
writes EEPROM. If the device does not return, the unchanged EEPROM is the
recovery image and a physical power cycle will reload it.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ms2109_hid import Device  # noqa: E402
from qualify_sharpness_ram import UVC  # noqa: E402

EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
DESCRIPTOR_BITMAP = 0xC07B


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_hid(timeout: float = 20.0) -> Device:
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            return Device()
        except Exception as exc:  # retry while macOS rebuilds the USB service
            error = exc
            time.sleep(0.25)
    raise RuntimeError(f"MS2109 HID did not return after reset: {error}")


def open_uvc(timeout: float = 20.0) -> UVC:
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            return UVC()
        except Exception as exc:
            error = exc
            time.sleep(0.25)
    raise RuntimeError(f"MS2109 EP0 did not return after reset: {error}")


def read_descriptor(uvc: UVC) -> tuple[dict, bytes]:
    record = uvc.descriptor(2, 1211)
    data = bytes.fromhex(record["data_hex"])
    if record["status"] != "ok" or len(data) != 1211:
        raise RuntimeError(f"Active descriptor request failed: {record}")
    return record, data


def main(output: Path) -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    result = {"scope": "RAM-only one-byte descriptor edit plus USB bus reset; EEPROM never written"}
    hid = Device()
    uvc = None
    original = None
    try:
        if hid.identify_eeprom() != 2048:
            raise RuntimeError("Expected the verified 2 KiB EEPROM")
        eeprom = hid.read("eeprom", 0, 2048)
        result["eeprom_sha256_before"] = sha(eeprom)
        if result["eeprom_sha256_before"] != EXPECTED_EEPROM:
            raise RuntimeError("Live EEPROM differs from the saved rollback image")
        if hid.read("ram", 0xC002, 2) != b"\xC0\x3A":
            raise RuntimeError("Active descriptor pointer is not C03A")
        original = hid.read("ram", DESCRIPTOR_BITMAP, 1)[0]
        if original != 0x0F:
            raise RuntimeError(f"Expected original PU bitmap 0x0F, got 0x{original:02X}")

        uvc = UVC()
        _, before = read_descriptor(uvc)
        result["ep0_bitmap_before"] = before[0x41]
        if before[0x41] != original:
            raise RuntimeError("RAM and EP0 bitmap differ before the reset probe")

        hid.exchange(0xB6, DESCRIPTOR_BITMAP, original | 0x10)
        if hid.read("ram", DESCRIPTOR_BITMAP, 1) != b"\x1F":
            raise RuntimeError("Could not set the volatile descriptor bit")
        result["bitmap_before_reset"] = hid.read("ram", DESCRIPTOR_BITMAP, 1)[0]
        hid.close()
        hid = None

        uvc.lib.libusb_reset_device.argtypes = [C.c_void_p]
        uvc.lib.libusb_reset_device.restype = C.c_int
        result["libusb_reset_device_result"] = uvc.lib.libusb_reset_device(uvc.handle)
        uvc.close()
        uvc = None
        if result["libusb_reset_device_result"] != 0:
            raise RuntimeError("USB reset failed; the volatile byte remains scheduled for restoration")

        hid = open_hid()
        if hid.identify_eeprom() != 2048:
            raise RuntimeError("Device returned with an unexpected EEPROM size")
        live_eeprom = hid.read("eeprom", 0, 2048)
        result["eeprom_sha256_after_reset"] = sha(live_eeprom)
        result["volatile_bitmap_after_reset"] = hid.read("ram", DESCRIPTOR_BITMAP, 1)[0]
        uvc = open_uvc()
        _, after = read_descriptor(uvc)
        result["ep0_bitmap_after_reset"] = after[0x41]
        result["ep0_reflected_pre_reset_ram_patch"] = after[0x41] == 0x1F
    finally:
        if uvc is not None:
            uvc.close()
        if hid is None:
            try:
                hid = open_hid(timeout=8.0)
            except Exception as exc:
                result["reconnect_error"] = repr(exc)
        if hid is not None:
            try:
                if original is not None:
                    current = hid.read("ram", DESCRIPTOR_BITMAP, 1)
                    if current != bytes((original,)):
                        hid.exchange(0xB6, DESCRIPTOR_BITMAP, original)
                    result["ram_restored"] = hid.read("ram", DESCRIPTOR_BITMAP, 1) == bytes((original,))
                first = hid.read("eeprom", 0, 2048)
                second = hid.read("eeprom", 0, 2048)
                result["eeprom_sha256_read1"] = sha(first)
                result["eeprom_sha256_read2"] = sha(second)
                result["eeprom_unchanged"] = (
                    first == second and sha(first) == EXPECTED_EEPROM
                )
            finally:
                hid.close()
    if result.get("ram_restored") and result.get("eeprom_unchanged"):
        if result.get("volatile_bitmap_after_reset") == original:
            result["status"] = "completed: USB reset reloaded the EEPROM image and cleared the volatile edit"
        else:
            result["status"] = "completed: RAM edit survived reset; post-reset EP0 result recorded"
    else:
        result["status"] = "failed: restoration or EEPROM verification"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"].startswith("failed"):
        raise RuntimeError(result["status"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
