#!/usr/bin/env python3
"""Read-only cold-boot verification of MS2109 video/audio USB name strings."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ms2109_hid import Device
from probe_uac_descriptor_patch_ram import EP0, read_eeprom_twice

DEFAULT_IMAGE = ROOT / "artifacts/ms2109-repair/20261008/named-eeprom-installed-readback.bin"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_name_record(record: bytes) -> str:
    if len(record) != 16 or not 2 <= record[0] <= 16:
        raise ValueError(f"Malformed EEPROM name record: {record.hex()}")
    return record[1:record[0]].decode("ascii")


def decode_string_descriptor(raw: bytes) -> str:
    if len(raw) < 2 or raw[0] != len(raw) or raw[1] != 3 or len(raw) % 2:
        raise ValueError(f"Malformed USB string descriptor: {raw.hex()}")
    return raw[2:].decode("utf-16le")


def run(output: Path, image_path: Path, expected_name: str) -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    expected = image_path.read_bytes()
    expected_sha = sha(expected)
    device = Device()
    ep0 = None
    result = {
        "scope": "read-only USB name verification after physical power-cycle",
        "expected_name": expected_name,
        "expected_eeprom_sha256": expected_sha,
        "strings": {},
    }
    try:
        if device.identify_eeprom() != len(expected):
            raise RuntimeError("Attached EEPROM has an unexpected size")
        eeprom_first = device.read("eeprom", 0, len(expected))
        eeprom_second = device.read("eeprom", 0, len(expected))
        result["eeprom_readbacks_match"] = eeprom_first == eeprom_second
        result["live_eeprom_sha256"] = sha(eeprom_first)
        if eeprom_first != expected or eeprom_second != expected:
            raise RuntimeError("Live EEPROM differs from the saved installed readback")
        result["header_names"] = {
            "video": decode_name_record(eeprom_first[0x10:0x20]),
            "audio": decode_name_record(eeprom_first[0x20:0x30]),
        }

        ep0 = EP0()
        for index in (2, 4):
            raw = ep0.get_string(index)
            decoded = decode_string_descriptor(raw)
            result["strings"][str(index)] = {
                "raw_hex": raw.hex(),
                "decoded": decoded,
                "matches_expected": decoded == expected_name,
            }
        result["status"] = (
            "passed" if all(item["matches_expected"] for item in result["strings"].values())
            else "failed: one or more USB strings differ from the expected name"
        )
    except BaseException as error:
        result["status"] = "failed"
        result["error"] = repr(error)
    finally:
        if ep0 is not None:
            ep0.close()
        device.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    if result["status"] != "passed":
        raise RuntimeError(result["status"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE,
                        help="saved full EEPROM readback to require")
    parser.add_argument("--name", default="MS2109-Pro")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.image, args.name), indent=2))


if __name__ == "__main__":
    main()
