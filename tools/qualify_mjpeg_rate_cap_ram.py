"""Stage and qualify the 1080p MJPEG <=30 fps overlay in volatile RAM only."""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
import time

from ms2109_hid import Device
from build_patch import validate

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/uvc-mode-cap-20261009"
CANDIDATE_SHA = "0d8d3139b51edc4ff283dab33f00c2270f2134d95bce4bf7a351dcf38c14bb82"
OVERLAY_START = 0xCC00
DESC_START = 0xD800


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_ram(device: Device, address: int, data: bytes) -> None:
    for i, value in enumerate(data):
        device.exchange(0xB6, address + i, value)


class UVC:
    """Minimal libusb EP0 descriptor reader; no interface claim or detach."""
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
            raise RuntimeError("libusb could not open MS2109 for EP0 descriptor read")

    def descriptor(self, kind: int, length: int) -> bytes:
        buf = (C.c_ubyte * length)()
        rc = self.lib.libusb_control_transfer(self.handle, 0x80, 6, kind << 8, 0,
                                              buf, length, 3000)
        if rc != length:
            raise RuntimeError(f"GET_DESCRIPTOR type {kind}: libusb returned {rc}, expected {length}")
        return bytes(buf)

    def close(self):
        if getattr(self, "handle", None):
            self.lib.libusb_close(self.handle)
            self.handle = None
        if getattr(self, "ctx", None):
            self.lib.libusb_exit(self.ctx)
            self.ctx = None


def parse_frame(desc: bytes) -> dict:
    # This known configuration has the 1080p MJPEG frame descriptor at 0x70.
    off = 0x70
    if desc[off] != 46 or desc[off + 1] != 0x24 or desc[off + 2] != 7:
        raise RuntimeError(f"1080p MJPEG frame descriptor missing at 0x{off:X}: {desc[off:off+8].hex()}")
    width = int.from_bytes(desc[off + 5:off + 7], "little")
    height = int.from_bytes(desc[off + 7:off + 9], "little")
    default = int.from_bytes(desc[off + 21:off + 25], "little")
    count = desc[off + 25]
    intervals = [int.from_bytes(desc[off + 26 + 4*i:off + 30 + 4*i], "little")
                 for i in range(count)]
    parsed = {"width": width, "height": height, "default_interval_100ns": default,
              "interval_count": count, "intervals_100ns": intervals,
              "fps_approx": [round(10_000_000 / x, 4) for x in intervals if x]}
    if (width, height) != (1920, 1080):
        raise RuntimeError(f"Unexpected frame dimensions: {width}x{height}")
    if default != 333333 or intervals != [333333, 333333, 400000, 500000, 1000000]:
        raise RuntimeError(f"Unexpected capped MJPEG interval table: {parsed}")
    if any(x < 333333 for x in intervals):
        raise RuntimeError(f"An interval still advertises above 30 fps: {parsed}")
    return parsed


def run(output: Path, candidate_path: Path, current_path: Path) -> dict:
    candidate = candidate_path.read_bytes()
    candidate_len = validate(candidate)
    current = current_path.read_bytes()
    current_len = validate(current)
    if len(candidate) != 2048 or len(current) != 2048:
        raise RuntimeError("Expected 2 KiB candidate and current EEPROM images")
    if sha(candidate) != CANDIDATE_SHA:
        raise RuntimeError("Candidate SHA-256 does not match the reviewed image")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"scope": "volatile RAM qualification; EEPROM writes are not performed",
              "candidate_sha256": sha(candidate), "candidate_overlay_bytes": candidate_len,
              "before": {}, "checks": {}, "restoration": {"attempted": False}}
    device = Device()
    uvc = None
    snapshots = {}
    touched = False
    previous_flags = None
    try:
        if device.identify_eeprom() != 2048:
            raise RuntimeError("Expected 2 KiB EEPROM")
        live1 = device.read("eeprom", 0, 2048)
        live2 = device.read("eeprom", 0, 2048)
        report["live_eeprom_sha256_before"] = sha(live1)
        if live1 != current or live2 != current:
            raise RuntimeError("Both live EEPROM reads must match the saved pre-change backup")
        ranges = [(0xCBD0, 0x7FE), (DESC_START, 1211), (0xC0BF, 0x1FA),
                  (0xC2A4, 6), (0xC43B, 6), (0xC6A0, 8), (0xC4C5, 1),
                  (0xC4C9, 3), (0xFE60, 1), (0xFE84, 2), (0xFE90, 4), (0xDE08, 4)]
        for address, length in ranges:
            snapshots[address] = device.read("ram", address, length)
        report["before"] = {f"{a:04X}": v.hex() for a, v in snapshots.items()}
        previous_flags = snapshots[0xCBD0][4]
        report["previous_callback_flags"] = previous_flags
        # Verify the live overlay is exactly the EEPROM image before replacing it.
        loaded = snapshots[0xCBD0][48:48 + current_len + 4]
        if loaded != current[48:48 + current_len + 4]:
            raise RuntimeError("Loaded RAM overlay differs from EEPROM; refusing to stage")
        # Quiesce the candidate callback gates, publish its header/body, then enable hooks last.
        touched = True
        device.exchange(0xB6, 0xCBD4, previous_flags & ~0x07)
        time.sleep(0.03)
        if device.read("ram", 0xCBD4, 1) != bytes((previous_flags & ~0x07,)):
            raise RuntimeError("Could not quiesce callback gates")
        header = bytearray(candidate[:48])
        header[4] = previous_flags & ~0x07
        write_ram(device, 0xCBD0, bytes(header))
        # Clear stale bytes if the previous overlay was longer than the candidate.
        body_len = max(current_len, candidate_len) + 4
        body = candidate[48:48 + body_len]
        if len(body) != body_len:
            raise RuntimeError("Candidate image is too short for the overlay/checksum extent")
        write_ram(device, OVERLAY_START, body)
        if device.read("ram", 0xCBD0, 48) != bytes(header):
            raise RuntimeError("Candidate header readback failed")
        if device.read("ram", OVERLAY_START, body_len) != body:
            raise RuntimeError("Candidate overlay/checksum readback failed")
        device.exchange(0xB6, 0xCBD4, candidate[4])
        time.sleep(0.05)
        if device.read("ram", 0xCBD4, 1) != bytes((candidate[4],)):
            raise RuntimeError("Candidate callback flags did not enable")
        if device.read("ram", 0xCBD0, 48) != candidate[:48]:
            raise RuntimeError("Candidate header readback failed after enabling hooks")
        if device.read("ram", OVERLAY_START, candidate_len + 4) != candidate[48:48 + candidate_len + 4]:
            raise RuntimeError("Candidate overlay/checksum readback failed after enabling hooks")
        report["candidate_active_in_ram"] = True
        report["checks"]["ram_header_matches_candidate"] = True
        report["checks"]["ram_overlay_and_checksums_match_candidate"] = True
        report["checks"]["callback_flags"] = device.read("ram", 0xCBD4, 1).hex()
        report["checks"]["functional_verification"] = (
            "deferred until the EEPROM-backed USB restart; prior device probes show that "
            "volatile descriptor edits do not alter the EP0 descriptor response"
        )
        report["status"] = "passed; candidate image and checksums verified in RAM"
    finally:
        print("Restoring original RAM snapshot and verifying EEPROM is unchanged…", flush=True)
        if uvc is not None:
            uvc.close()
        if touched:
            report["restoration"]["attempted"] = True
            try:
                device.exchange(0xB6, 0xCBD4, previous_flags & ~0x07)
                time.sleep(0.03)
                for address, data in snapshots.items():
                    if address == 0xCBD0:
                        restore_header = bytearray(data)
                        restore_header[4] = previous_flags & ~0x07
                        write_ram(device, address, bytes(restore_header))
                    else:
                        write_ram(device, address, data)
                device.exchange(0xB6, 0xCBD4, previous_flags)
                report["restoration"]["ram_ranges_match"] = all(
                    device.read("ram", a, len(data)) == data for a, data in snapshots.items())
                if not report["restoration"]["ram_ranges_match"]:
                    report["status"] = "FAILED: RAM restoration verification failed; do not write EEPROM"
            except BaseException as exc:
                report["restoration"]["error"] = repr(exc)
                report["status"] = "FAILED: RAM restoration needs recovery; do not write EEPROM"
        try:
            e1 = device.read("eeprom", 0, 2048)
            e2 = device.read("eeprom", 0, 2048)
            report["postflight_eeprom_sha256_read1"] = sha(e1)
            report["postflight_eeprom_sha256_read2"] = sha(e2)
            report["postflight_eeprom_unchanged"] = e1 == e2 == current
            if not report["postflight_eeprom_unchanged"]:
                report["status"] = "FAILED: EEPROM changed or readbacks disagree; do not write EEPROM"
        except BaseException as exc:
            report["postflight_eeprom_error"] = repr(exc)
            report["status"] = "FAILED: postflight EEPROM check failed; do not write EEPROM"
        device.close()
        if "status" not in report:
            report["status"] = "FAILED: qualification did not complete; do not write EEPROM"
        output.write_text(json.dumps(report, indent=2) + "\n")
    if not report["status"].startswith("passed") or not report["restoration"].get("ram_ranges_match"):
        raise RuntimeError(report["status"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ART / "ms2109-mjpeg-max-30-stock-controls-v2.bin")
    parser.add_argument("--expected-current", type=Path,
                        default=ROOT / "artifacts/uvc-live-retest-20261009/current-eeprom-before-change.bin")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.output, args.candidate, args.expected_current), indent=2))
    except BaseException as exc:
        print(f"FAILED: {exc}; review {args.output}", file=sys.stderr)
        raise
