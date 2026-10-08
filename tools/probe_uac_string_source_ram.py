#!/usr/bin/env python3
"""Reversibly test whether the live ROM reads UAC string 4 from XDATA CBF0.

The tool journals CBF0 and C656 before writing, checks raw EP0, restores both
XDATA ranges, and verifies that EEPROM is unchanged. A live source edit may not
change strings that the ROM initialized only during boot.
"""
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

DEFAULT_EEPROM = ROOT / "artifacts/ms2109-repair/20261008/installed-readback.bin"
SOURCE_ADDRESS = 0xCBF0
SOURCE_SIZE = 16
RESPONSE_ADDRESS = 0xC656
RESPONSE_SIZE = 22


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_string(raw: bytes) -> str:
    if len(raw) < 2 or raw[0] != len(raw) or raw[1] != 3 or len(raw) % 2:
        raise ValueError(f"Malformed USB string descriptor: {raw.hex()}")
    return raw[2:].decode("utf-16le")


def source_record(name: str) -> bytes:
    try:
        encoded = name.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("Name must use ASCII characters") from error
    if not encoded or len(encoded) > 15:
        raise ValueError("Name must contain 1 to 15 ASCII bytes")
    return bytes((len(encoded) + 1,)) + encoded + bytes((0xFF,)) * (15-len(encoded))


def descriptor_from_source(source: bytes) -> bytes:
    if len(source) != SOURCE_SIZE or not 2 <= source[0] <= 16:
        raise ValueError(f"Malformed EEPROM name record: {source.hex()}")
    name = source[1:source[0]].decode("ascii")
    payload = name.encode("utf-16le")
    return bytes((len(payload)+2, 3)) + payload


def write_ram(device: Device, address: int, data: bytes) -> None:
    for offset, value in enumerate(data):
        device.exchange(0xB6, address + offset, value)
    if device.read("ram", address, len(data)) != data:
        raise RuntimeError(f"XDATA readback failed at {address:04X}")


def write_journal(path: Path, state: str, eeprom_sha: str,
                  ranges: list[tuple[int, bytes]]) -> None:
    record = {
        "format": 1,
        "device": "MS2109",
        "region": "XDATA RAM only",
        "eeprom_sha256": eeprom_sha,
        "state": state,
        "ranges": [{"address": f"0x{address:04X}", "data_hex": data.hex()}
                   for address, data in ranges],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")


def restore(device: Device, ranges: list[tuple[int, bytes]]) -> dict:
    checks = {}
    for address, data in ranges:
        write_ram(device, address, data)
        checks[f"{address:04X}"] = device.read("ram", address, len(data)) == data
    return checks


def recover(path: Path) -> dict:
    record = json.loads(path.read_text())
    if record.get("format") != 1 or record.get("region") != "XDATA RAM only":
        raise ValueError("Unsupported string-source recovery journal")
    device = Device()
    try:
        if sha(read_eeprom_twice(device)) != record["eeprom_sha256"]:
            raise RuntimeError("EEPROM identity changed; refusing RAM recovery")
        ranges = [(int(item["address"], 16), bytes.fromhex(item["data_hex"]))
                  for item in record["ranges"]]
        checks = restore(device, ranges)
        record["recovery_readback"] = checks
        record["state"] = "restored" if all(checks.values()) else "restore_failed"
        record["eeprom_sha256_after"] = sha(read_eeprom_twice(device))
        path.write_text(json.dumps(record, indent=2) + "\n")
        return record
    finally:
        device.close()


def run(output: Path, expected_eeprom_path: Path = DEFAULT_EEPROM,
        new_name: str = "MS2109-Pro") -> dict:
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    recovery_path = output.with_suffix(".recovery.json")
    if recovery_path.exists():
        raise RuntimeError(f"Refusing to overwrite {recovery_path}")
    expected_eeprom = expected_eeprom_path.read_bytes()
    expected_eeprom_sha256 = sha(expected_eeprom)
    old_source = expected_eeprom[0x20:0x30]
    old_descriptor = descriptor_from_source(old_source)
    new_source = source_record(new_name)
    new_descriptor = descriptor_from_source(new_source)
    device = Device()
    ep0 = None
    original = []
    eeprom_before = None
    result = {
        "scope": "volatile UAC string-source probe; no EEPROM writes",
        "source_address": f"0x{SOURCE_ADDRESS:04X}",
        "response_buffer": f"0x{RESPONSE_ADDRESS:04X}",
        "restoration": {"attempted": False},
    }
    recovery_saved = False
    try:
        eeprom_before = read_eeprom_twice(device)
        result["eeprom_sha256_before"] = sha(eeprom_before)
        if eeprom_before != expected_eeprom or result["eeprom_sha256_before"] != expected_eeprom_sha256:
            raise RuntimeError("Attached EEPROM differs from the exact two-read backup")
        source = device.read("ram", SOURCE_ADDRESS, SOURCE_SIZE)
        response = device.read("ram", RESPONSE_ADDRESS, RESPONSE_SIZE)
        original = [(SOURCE_ADDRESS, source), (RESPONSE_ADDRESS, response)]
        result["source_before_hex"] = source.hex()
        result["response_before_hex"] = response.hex()
        if source != old_source:
            raise RuntimeError(f"Unexpected live CBF0 source: {source.hex()}")

        ep0 = EP0()
        before = ep0.get_string(4)
        result["ep0_before_hex"] = before.hex()
        result["ep0_before_decoded"] = parse_string(before)
        if before != old_descriptor:
            raise RuntimeError("Raw EP0 string 4 differs from the backed-up audio-name record")

        write_journal(recovery_path, "active", expected_eeprom_sha256, original)
        recovery_saved = True
        write_ram(device, SOURCE_ADDRESS, new_source)
        result["source_during_hex"] = device.read("ram", SOURCE_ADDRESS, SOURCE_SIZE).hex()
        during = ep0.get_string(4)
        result["ep0_during_hex"] = during.hex()
        result["ep0_during_decoded"] = parse_string(during)
        result["source_edit_reached_ep0"] = during == new_descriptor
        result["status"] = (f"passed: ROM rebuilt string 4 as {new_name} from CBF0"
                            if during == new_descriptor else
                            "failed: CBF0 edit did not produce the expected raw EP0 string")
    finally:
        result["restoration"]["attempted"] = bool(original)
        if ep0 is not None:
            ep0.close()
        if original:
            try:
                # Restore the authoritative source first, then regenerate the
                # original EP0 response before restoring its exact saved buffer.
                write_ram(device, SOURCE_ADDRESS, original[0][1])
                ep0_restore = EP0()
                try:
                    restored_string = ep0_restore.get_string(4)
                    result["restoration"]["ep0_string4_restored"] = restored_string == old_descriptor
                finally:
                    ep0_restore.close()
                write_ram(device, RESPONSE_ADDRESS, original[1][1])
                result["restoration"]["ranges_readback_match"] = all(
                    device.read("ram", address, len(data)) == data
                    for address, data in original)
                if recovery_saved:
                    write_journal(recovery_path, "restored", expected_eeprom_sha256, original)
            except Exception as error:
                result["restoration"]["error"] = str(error)
                if recovery_saved:
                    write_journal(recovery_path, "restore_failed", expected_eeprom_sha256, original)
        try:
            after = read_eeprom_twice(device)
            result["eeprom_sha256_after"] = sha(after)
            result["eeprom_unchanged"] = after == eeprom_before
        except Exception as error:
            result["eeprom_check_error"] = str(error)
        result["recovery_file"] = str(recovery_path) if recovery_saved else None
        device.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new JSON evidence path")
    mode.add_argument("--recover", type=Path, help="restore an interrupted RAM probe")
    parser.add_argument("--expected-eeprom", type=Path, default=DEFAULT_EEPROM,
                        help="two-read EEPROM backup to require before RAM writes")
    parser.add_argument("--name", default="MS2109-Pro", help="ASCII name to probe")
    args = parser.parse_args()
    result = recover(args.recover) if args.recover else run(
        args.output, args.expected_eeprom, args.name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
