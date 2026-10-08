#!/usr/bin/env python3
"""Build an offline UAC interface-name firmware candidate.

The candidate rewrites the audio interface descriptors' string indexes in the
firmware's guarded configuration-copy path. It reuses USB string 2, whose
descriptor is already MS2109-Pro. Live RAM qualification changed type 7, but
the active type-2 response remained on the ROM path; the candidate is not a
complete UAC rename. It does not install or communicate with the device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_patch import validate

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "artifacts/ms2109-repair/20261007/current-eeprom-readback.bin"
BASELINE_SHA256 = "b1f78dd4ac512fa195261b7619fc8cd50498adaf48e199a0eb607dd0641e1ce8"
EEPROM_BYTES = 2048
OLD_CODE_LENGTH = 1904
MAX_CODE_LENGTH = EEPROM_BYTES - 52
CODE_BASE = 0xCC00
CALL_SITE = 0xCDAB
HELPER_ADDRESS = 0xD370
EXPECTED_CALL_SITE = bytes.fromhex("44 10 F0")

# After the existing copy routine fills D800, the descriptor type is still in
# IRAM 0D. Rewrite all three audio iInterface fields in either known layout.
# A type other than 2 or 7 returns without changing the copy. The former
# Sharpness bit OR at CDAB is removed; no visual sharpness mapping is claimed.
def _store(address: int) -> bytes:
    return bytes((0x90, address >> 8, address & 0xFF, 0x74, 2, 0xF0))


HELPER = (
    bytes.fromhex("E5 0D B4 02 13")
    + _store(0xDC47) + _store(0xDC76) + _store(0xDC7F)
    + bytes.fromhex("22 B4 07 12")
    + _store(0xD8EF) + _store(0xD91E) + _store(0xD927)
    + bytes.fromhex("22")
)
CALL_STUB = bytes((0x12, HELPER_ADDRESS >> 8, HELPER_ADDRESS & 0xFF))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(image: bytes) -> tuple[bytes, dict]:
    if len(image) != EEPROM_BYTES or sha(image) != BASELINE_SHA256:
        raise ValueError("Input does not match the exact two-read MS2109 EEPROM baseline")
    code_length = validate(image)
    if code_length != OLD_CODE_LENGTH or image[4] != 0x07:
        raise ValueError("Unexpected loaded-code length or hook flags")
    if CALL_SITE - CODE_BASE != 0x01AB:
        raise ValueError("Reviewed descriptor hook location changed")
    if len(HELPER) != 46 or HELPER_ADDRESS != CODE_BASE + code_length:
        raise ValueError("Reviewed helper placement changed")
    if code_length + len(HELPER) > MAX_CODE_LENGTH:
        raise ValueError("UAC interface-name helper exceeds the 2 KiB EEPROM budget")
    if image[48 + CALL_SITE - CODE_BASE:48 + CALL_SITE - CODE_BASE + 3] != EXPECTED_CALL_SITE:
        raise ValueError("Expected Sharpness-advertisement instruction is not present")
    if any(value != 0xFF for value in image[48 + code_length + 4:]):
        raise ValueError("Expected erased EEPROM space after the current checksums")

    code = bytearray(image[48:48 + code_length])
    offset = CALL_SITE - CODE_BASE
    code[offset:offset + 3] = CALL_STUB
    code.extend(HELPER)
    new_length = len(code)

    candidate = bytearray(image)
    candidate[48:48 + new_length] = code
    candidate[2:4] = new_length.to_bytes(2, "big")
    candidate[48 + new_length:50 + new_length] = (
        sum(candidate[2:48]) & 0xFFFF).to_bytes(2, "big")
    candidate[50 + new_length:52 + new_length] = (
        sum(candidate[48:48 + new_length]) & 0xFFFF).to_bytes(2, "big")
    output = bytes(candidate)
    if validate(output) != new_length:
        raise AssertionError("Generated candidate failed checksum validation")
    return output, {
        "status": "partial offline candidate; active type-2 ROM path remains unmodified",
        "baseline_sha256": sha(image),
        "candidate_sha256": sha(output),
        "old_code_bytes": code_length,
        "new_code_bytes": new_length,
        "helper_address": f"0x{HELPER_ADDRESS:04X}",
        "call_site": f"0x{CALL_SITE:04X}",
        "uac_interface_string_index": 2,
        "uac_interface_string": "MS2109-Pro",
        "configuration_types_supported_by_helper": [2, 7],
        "live_probe": {
            "type_2": "ROM path remained unchanged: interface string indexes 4, processing bitmap 1F00",
            "type_7": "overlay path changed interface string indexes to 2 and bitmap to 0F00",
        },
        "audio_interface_index_fields": {
            "2": ["0x0447", "0x0476", "0x047F"],
            "7": ["0x00EF", "0x011E", "0x0127"]
        },
        "sharpness_advertisement": (
            "overlay helper does not add Sharpness; type-7 response is 0F00, "
            "but the active type-2 ROM response still advertises Processing Unit bitmap 1F00"
        ),
        "eeprom_writes": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        parser.error("Refusing to overwrite candidate or metadata")
    candidate, report = build(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    report["candidate_file"] = str(args.output)
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
