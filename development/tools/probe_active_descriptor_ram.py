"""Reversibly identify the live active-configuration descriptor backing RAM."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ms2109_hid import Device  # noqa: E402
from qualify_sharpness_ram import UVC  # noqa: E402

EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
PU_BITMAP_OFFSET = 0x41


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(output: Path) -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    device = Device()
    uvc = None
    result = {"scope": "single-byte volatile RAM probe; EEPROM never written"}
    address = None
    original = None
    changed = False
    try:
        if device.identify_eeprom() != 2048:
            raise RuntimeError("Expected the verified 2 KiB EEPROM")
        eeprom_before = device.read("eeprom", 0, 2048)
        result["eeprom_sha256_before"] = sha(eeprom_before)
        if result["eeprom_sha256_before"] != EXPECTED_EEPROM:
            raise RuntimeError("Live EEPROM differs from the saved rollback image")

        pointer = device.read("ram", 0xC002, 2)
        descriptor_base = int.from_bytes(pointer, "big")
        if descriptor_base != 0xC03A:
            raise RuntimeError(f"Unexpected active descriptor pointer: {pointer.hex()}")
        header = device.read("ram", descriptor_base, 4)
        if header[:2] != b"\x09\x02" or int.from_bytes(header[2:4], "little") != 1211:
            raise RuntimeError(f"Unexpected active configuration header: {header.hex()}")

        address = descriptor_base + PU_BITMAP_OFFSET
        original = device.read("ram", address, 1)[0]
        if original != 0x0F:
            raise RuntimeError(f"Expected stock PU bitmap 0x0F, got 0x{original:02X}")

        uvc = UVC()
        before = uvc.descriptor(2, 1211)
        before_raw = bytes.fromhex(before["data_hex"])
        if before["status"] != "ok" or len(before_raw) != 1211:
            raise RuntimeError(f"Raw active descriptor read failed: {before}")
        result["pointer"] = pointer.hex()
        result["descriptor_header"] = header.hex()
        result["bitmap_address"] = f"0x{address:04X}"
        result["ram_bitmap_before"] = original
        result["ep0_bitmap_before"] = before_raw[PU_BITMAP_OFFSET]
        if before_raw[PU_BITMAP_OFFSET] != original:
            raise RuntimeError("RAM byte and raw EP0 descriptor disagree before mutation")

        device.exchange(0xB6, address, original | 0x10)
        changed = True
        if device.read("ram", address, 1) != bytes((original | 0x10,)):
            raise RuntimeError("RAM bitmap write did not read back")
        after = uvc.descriptor(2, 1211)
        after_raw = bytes.fromhex(after["data_hex"])
        if after["status"] != "ok" or len(after_raw) != 1211:
            raise RuntimeError(f"Raw active descriptor reread failed: {after}")
        result["ram_bitmap_during_probe"] = device.read("ram", address, 1)[0]
        result["ep0_bitmap_after"] = after_raw[PU_BITMAP_OFFSET]
        result["ep0_reflected_ram_patch"] = after_raw[PU_BITMAP_OFFSET] == (original | 0x10)
    finally:
        if uvc is not None:
            uvc.close()
        if changed and address is not None and original is not None:
            device.exchange(0xB6, address, original)
        if address is not None and original is not None:
            result["ram_restored"] = device.read("ram", address, 1) == bytes((original,))
        eeprom_first = device.read("eeprom", 0, 2048)
        eeprom_second = device.read("eeprom", 0, 2048)
        result["eeprom_sha256_read1"] = sha(eeprom_first)
        result["eeprom_sha256_read2"] = sha(eeprom_second)
        result["eeprom_unchanged"] = (
            eeprom_first == eeprom_second and sha(eeprom_first) == EXPECTED_EEPROM
        )
        device.close()

    if result.get("ram_restored") and result.get("eeprom_unchanged"):
        result["status"] = (
            "completed: response reflected the RAM patch"
            if result.get("ep0_reflected_ram_patch")
            else "completed: EP0 response did not reflect the XDATA patch; RAM and EEPROM restored"
        )
    else:
        result["status"] = "failed: restoration verification"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        raise RuntimeError(result["status"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.output)
