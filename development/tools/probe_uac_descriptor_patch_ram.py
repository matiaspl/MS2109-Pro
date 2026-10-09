#!/usr/bin/env python3
"""RAM-only live qualification for the UAC interface-name descriptor patch.

The tool snapshots every XDATA range it may touch, verifies the EEPROM twice,
stages a small callback patch, reads raw EP0 configuration descriptors, then
restores and verifies the original RAM and EEPROM. It never writes EEPROM.
"""
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
from patch_uac_interface_name import (
    BASELINE_SHA256, CALL_SITE, CALL_STUB, EXPECTED_CALL_SITE, HELPER,
    HELPER_ADDRESS, build,
)

DEFAULT_EEPROM = ROOT / "artifacts/ms2109-repair/20261007/current-eeprom-readback.bin"
RANGES = ((CALL_SITE, 3), (HELPER_ADDRESS, len(HELPER)),
          (0xD800, 1211), (0xC000, 4))
INTERFACE_OFFSETS = {2: (0x447, 0x476, 0x47F), 7: (0x0EF, 0x11E, 0x127)}
CONFIG_LENGTHS = {2: 1211, 7: 355}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EP0:
    def __init__(self):
        self.lib = C.CDLL("/opt/homebrew/lib/libusb-1.0.dylib")
        self.lib.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
        self.lib.libusb_init.restype = C.c_int
        self.lib.libusb_open_device_with_vid_pid.argtypes = [
            C.c_void_p, C.c_uint16, C.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = C.c_void_p
        self.lib.libusb_control_transfer.argtypes = [
            C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16,
            C.POINTER(C.c_ubyte), C.c_uint16, C.c_uint]
        self.lib.libusb_control_transfer.restype = C.c_int
        self.lib.libusb_close.argtypes = [C.c_void_p]
        self.lib.libusb_exit.argtypes = [C.c_void_p]
        self.ctx = C.c_void_p()
        rc = self.lib.libusb_init(C.byref(self.ctx))
        if rc:
            raise RuntimeError(f"libusb_init failed: {rc}")
        self.handle = self.lib.libusb_open_device_with_vid_pid(
            self.ctx, 0x534D, 0x2109)
        if not self.handle:
            self.close()
            raise RuntimeError("Could not open attached MS2109 for raw EP0 reads")

    def get_descriptor(self, kind: int, length: int) -> bytes:
        buf = (C.c_ubyte * length)()
        count = self.lib.libusb_control_transfer(
            self.handle, 0x80, 6, kind << 8, 0, buf, length, 3000)
        if count < 0:
            raise RuntimeError(f"GET_DESCRIPTOR type {kind} failed: {count}")
        return bytes(buf[:count])

    def get_string(self, index: int) -> bytes:
        buf = (C.c_ubyte * 64)()
        count = self.lib.libusb_control_transfer(
            self.handle, 0x80, 6, 0x0300 | index, 0x0409, buf, 64, 3000)
        if count < 0:
            raise RuntimeError(f"GET_DESCRIPTOR string {index} failed: {count}")
        return bytes(buf[:count])

    def close(self):
        if getattr(self, "handle", None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self, "ctx", None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def write_ram(device: Device, address: int, data: bytes) -> None:
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)
    actual = device.read("ram", address, len(data))
    if actual != data:
        raise RuntimeError(f"XDATA readback failed at {address:04X}")


def read_eeprom_twice(device: Device) -> bytes:
    size = device.identify_eeprom()
    first = device.read("eeprom", 0, size)
    second = device.read("eeprom", 0, size)
    if first != second:
        raise RuntimeError("Two EEPROM readbacks disagree")
    return first


def descriptor_summary(raw: bytes, kind: int) -> dict:
    if len(raw) != CONFIG_LENGTHS[kind]:
        return {"byte_count": len(raw), "complete": False}
    offsets = INTERFACE_OFFSETS[kind]
    indexes = [raw[offset] for offset in offsets]
    return {
        "byte_count": len(raw),
        "complete": True,
        "audio_interface_string_indexes": indexes,
        "processing_unit_controls": raw[0x41:0x43].hex(),
        "sharpness_advertised": bool(raw[0x41] & 0x10),
    }


def restore(device: Device, snapshot: dict) -> dict:
    results = {}
    for address, data in snapshot:
        write_ram(device, address, data)
        results[f"{address:04X}"] = device.read("ram", address, len(data)) == data
    return results


def run(output: Path, *, baseline: Path = DEFAULT_EEPROM) -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    recovery_path = output.with_suffix(".recovery.json")
    if recovery_path.exists():
        raise RuntimeError(f"Refusing to overwrite {recovery_path}")
    image = baseline.read_bytes()
    if sha(image) != BASELINE_SHA256:
        raise RuntimeError("Saved baseline does not match the attached MS2109 profile")
    candidate, candidate_report = build(image)
    code_length = int.from_bytes(candidate[2:4], "big")
    code = candidate[48:48 + code_length]
    helper_offset = HELPER_ADDRESS - 0xCC00
    code_site_offset = CALL_SITE - 0xCC00
    if code[helper_offset:helper_offset + len(HELPER)] != HELPER:
        raise AssertionError("Candidate helper bytes do not match the live probe")
    if code[code_site_offset:code_site_offset + 3] != CALL_STUB:
        raise AssertionError("Candidate call site does not match the live probe")

    device = Device()
    ep0 = None
    snapshot = []
    recovery = {
        "format": 1,
        "device": "MS2109",
        "region": "XDATA RAM only",
        "eeprom_sha256": BASELINE_SHA256,
        "state": "preparing",
        "ranges": [],
    }
    result = {
        "scope": "volatile descriptor callback probe; no EEPROM writes",
        "candidate_sha256": candidate_report["candidate_sha256"],
        "eeprom_sha256_expected": BASELINE_SHA256,
        "configuration_types": {},
        "restoration": {"attempted": False},
    }
    changed = False
    try:
        eeprom_before = read_eeprom_twice(device)
        result["eeprom_sha256_before"] = sha(eeprom_before)
        if result["eeprom_sha256_before"] != BASELINE_SHA256:
            raise RuntimeError("Attached EEPROM differs from the exact two-read baseline")
        for address, length in RANGES:
            snapshot.append((address, device.read("ram", address, length)))
        site_before = next(data for address, data in snapshot if address == CALL_SITE)
        if site_before != EXPECTED_CALL_SITE:
            raise RuntimeError(
                f"Live callback bytes at {CALL_SITE:04X} differ: {site_before.hex()}")
        recovery["ranges"] = [
            {"address": f"0x{address:04X}", "data_hex": data.hex()}
            for address, data in snapshot]
        recovery["state"] = "active"
        recovery_path.parent.mkdir(parents=True, exist_ok=True)
        recovery_path.write_text(json.dumps(recovery, indent=2) + "\n")

        ep0 = EP0()
        result["baseline_configurations"] = {}
        for kind, length in CONFIG_LENGTHS.items():
            raw = ep0.get_descriptor(kind, length)
            result["baseline_configurations"][str(kind)] = descriptor_summary(raw, kind)

        # Stage helper first, then the two target bytes, and activate with the
        # LCALL opcode last so an interrupted write cannot jump into half-code.
        write_ram(device, HELPER_ADDRESS, HELPER)
        write_ram(device, CALL_SITE + 1, CALL_STUB[1:])
        write_ram(device, CALL_SITE, CALL_STUB[:1])
        changed = True

        for kind, length in CONFIG_LENGTHS.items():
            raw = ep0.get_descriptor(kind, length)
            observed = descriptor_summary(raw, kind)
            observed["raw_sha256"] = sha(raw)
            result["configuration_types"][str(kind)] = observed

        result["candidate_live_checks"] = {
            "type_2_audio_names_reuse_product_string": (
                result["configuration_types"].get("2", {}).get(
                    "audio_interface_string_indexes") == [2, 2, 2]),
            "type_7_audio_names_reuse_product_string": (
                result["configuration_types"].get("7", {}).get(
                    "audio_interface_string_indexes") == [2, 2, 2]),
            "sharpness_not_advertised_in_type_2": (
                result["configuration_types"].get("2", {}).get(
                    "sharpness_advertised") is False),
            "sharpness_not_advertised_in_type_7": (
                result["configuration_types"].get("7", {}).get(
                    "sharpness_advertised") is False),
        }
        result["status"] = ("passed" if all(result["candidate_live_checks"].values())
                            else "partial: at least one raw EP0 descriptor did not use the patch")
    finally:
        result["restoration"]["attempted"] = bool(snapshot)
        if ep0 is not None:
            ep0.close()
        if snapshot:
            # Disable the patched call site first; then restore every snapshotted
            # range in reverse order so the original scratch/source state returns.
            original_site = next(data for address, data in snapshot if address == CALL_SITE)
            try:
                write_ram(device, CALL_SITE, original_site[:1])
                for address, data in reversed(snapshot):
                    if address == CALL_SITE:
                        write_ram(device, address + 1, data[1:])
                        continue
                    write_ram(device, address, data)
                result["restoration"]["ranges_readback_match"] = True
                recovery["state"] = "restored"
            except Exception as error:
                result["restoration"]["error"] = str(error)
                recovery["state"] = "restore_failed"
            recovery_path.write_text(json.dumps(recovery, indent=2) + "\n")
        try:
            after = read_eeprom_twice(device)
            result["eeprom_sha256_after"] = sha(after)
            result["eeprom_unchanged"] = after == eeprom_before
        except Exception as error:
            result["eeprom_check_error"] = str(error)
        device.close()
        result["recovery_file"] = str(recovery_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def recover(path: Path) -> dict:
    record = json.loads(path.read_text())
    if record.get("format") != 1 or record.get("region") != "XDATA RAM only":
        raise ValueError("Unsupported RAM recovery journal")
    device = Device()
    try:
        if sha(read_eeprom_twice(device)) != record["eeprom_sha256"]:
            raise RuntimeError("EEPROM identity changed; refusing recovery write")
        ranges = [(int(item["address"], 16), bytes.fromhex(item["data_hex"]))
                  for item in record["ranges"]]
        results = restore(device, list(reversed(ranges)))
        record["state"] = "restored" if all(results.values()) else "restore_failed"
        record["recovery_readback"] = results
        record["eeprom_sha256_after"] = sha(read_eeprom_twice(device))
        path.write_text(json.dumps(record, indent=2) + "\n")
        return record
    finally:
        device.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new JSON evidence path")
    mode.add_argument("--recover", type=Path, help="restore an interrupted probe journal")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_EEPROM)
    args = parser.parse_args()
    result = recover(args.recover) if args.recover else run(args.output, baseline=args.baseline)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
