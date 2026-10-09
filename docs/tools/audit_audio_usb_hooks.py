#!/usr/bin/env python3
"""Offline byte audit of MS2109 USB hooks; never opens or writes a device."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM_SHA = "b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8"
IMAGE_SHA = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
PROBE_SHA = "8fe6492a562e843fbaceeeb06c5d2ab45e4d754d4d620a585e1ba3d78fd0b7b8"


def audit():
    rom = (ROOT / "backups/ms2109-maskrom.bin").read_bytes()
    image = (ROOT / "artifacts/ms2109-calibrated-stereo-channel-order.bin").read_bytes()
    for name, data, expected in (("ROM", rom, ROM_SHA), ("image", image, IMAGE_SHA)):
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"{name} differs from the reviewed artifact")

    checks = []

    def check(name, address, expected, *, overlay=False):
        wanted = bytes.fromhex(expected)
        offset = address - 0xCC00 + 0x30 if overlay else address
        actual = (image if overlay else rom)[offset:offset + len(wanted)]
        if actual != wanted:
            raise ValueError(f"Unexpected bytes at {address:04x}: {actual.hex()}")
        checks.append({"name": name, "address": f"0x{address:04X}",
                       "space": "EEPROM overlay" if overlay else "saved ROM",
                       "bytes": actual.hex(), "matches": True})

    check("USB dispatch selects CC10 when CBD4 bit 1 is set; otherwise 2AD0",
          0x4788, "90cbd4 e0 30e105 12cc10 8003 122ad0 c213 22")
    check("Setup parser reads bmRequestType and bRequest from EP0 FIFO",
          0x58C8, "85ab0b 85ab0c 124b3e")
    check("Standard-request switch reads bRequest at IRAM 0C",
          0x2ADD, "e50c 120910")
    check("Switch table maps request 0B to 2B2B",
          0x2AFA, "2b2b0b 00002b30")
    check("SET_INTERFACE dispatch calls 67F1 then common completion at 2B8E",
          0x2B2B, "1267f1 805e")
    check("Interface 3 stores wValue low in IRAM 3A and marks status pending",
          0x6807, "bf0303 850e3a d216 22")
    check("Common completion consumes pending status and sets EP0 CSR bit 3",
          0x2B9D, "301606 d283 c216 800a")
    check("IRQ dispatch calls CC20 when CBD4 bit 2 is set",
          0x2CB3, "90cbd4 e0 30e203 12cc20")
    check("After CC20, IRAM 32 bit 2 gates the ROM EP2-ready write",
          0x2CD5, "e532 30e205 759302 d280")
    check("Endpoint 2 initialization", 0x61A1,
          "759302 e4 f5a2 75a301 758005 759070")
    check("Existing video callback occupying CC10", 0xCC10,
          "90de05 eb f0 a3 ea f0 a3 e9 f0 126345 22", overlay=True)
    check("Existing video command tail-jumps to CC10", 0xD118,
          "7bff 7acd 7952 02cc10", overlay=True)

    previous_probe = (ROOT / "artifacts/audio-stream-start-reset-attempt2-hook.bin").read_bytes()
    if hashlib.sha256(previous_probe).hexdigest() != PROBE_SHA:
        raise ValueError("Historical probe differs from the reviewed artifact")
    latch = bytes.fromhex("90de2c 7401 f0")
    if latch not in previous_probe:
        raise ValueError("Historical probe differs from the reviewed flag-writing implementation")
    return {
        "scope": "offline signatures only; no hardware access or new candidate installed",
        "rom_sha256": ROM_SHA, "image_sha256": IMAGE_SHA,
        "image_hook_flags": f"0x{image[4]:02X}",
        "usb_control_hook_enabled_in_image": bool(image[4] & 2),
        "checks": checks,
        "historical_probe_telemetry": {
            "hook_sha256": PROBE_SHA,
            "store_address": f"0x{0xD400 + previous_probe.index(latch):04X}",
            "bytes": latch.hex(),
            "meaning": "writes 1 to DE2C; occurrence flag, not an incrementing count",
            "proves": "reset sequence was reached at least once",
            "does_not_prove": ["exact event count", "timing before first audio packet"]
        },
        "conclusion": "USB request interception and pre-EP2-ready IRQ interception exist in this ROM; neither proves a sample-alignment fix."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(audit(), indent=2) + "\n"
    if args.output:
        with args.output.open("x") as output:
            output.write(result)
    print(result, end="")


if __name__ == "__main__":
    main()
