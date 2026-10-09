#!/usr/bin/env python3
"""Measure the 2 KiB MS2109 Sharpness-profile space and EDID encoding.

This is an offline accounting tool. It does not build or install firmware.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_patch import ORIGINAL_SHA, ROM_SHA, build, validate

ROOT = Path(__file__).resolve().parents[1]
EEPROM_LIMIT = 2048
CODE_LIMIT = EEPROM_LIMIT - 52
EDID_LENGTH = 256
CUSTOM_EDID_CODE = 0xCD52
ROM_DEFAULT_EDID_CODE = 0x7738


def encode_delta(base: bytes, target: bytes) -> bytes:
    """Encode changed runs as count, then (offset, length, bytes) records."""
    if len(base) != EDID_LENGTH or len(target) != EDID_LENGTH:
        raise ValueError("EDID delta inputs must each be 256 bytes")
    runs: list[tuple[int, bytes]] = []
    i = 0
    while i < EDID_LENGTH:
        if base[i] == target[i]:
            i += 1
            continue
        start = i
        while i < EDID_LENGTH and base[i] != target[i]:
            i += 1
        runs.append((start, target[start:i]))
    if len(runs) > 255:
        raise ValueError("Too many runs for the compact format")
    out = bytearray((len(runs),))
    for start, changed in runs:
        if not 1 <= len(changed) <= 255:
            raise ValueError("Run length does not fit in one byte")
        out.extend((start, len(changed)))
        out.extend(changed)
    return bytes(out)


def decode_delta(base: bytes, encoded: bytes) -> bytes:
    """Reconstruct a 256-byte EDID from an encoded changed-run stream."""
    if len(base) != EDID_LENGTH or not encoded:
        raise ValueError("Invalid EDID delta input")
    output = bytearray(base)
    run_count = encoded[0]
    cursor = 1
    for _ in range(run_count):
        if cursor + 2 > len(encoded):
            raise ValueError("Truncated EDID run header")
        start, count = encoded[cursor:cursor + 2]
        cursor += 2
        if count == 0 or cursor + count > len(encoded) or start + count > EDID_LENGTH:
            raise ValueError("Invalid EDID run extent")
        output[start:start + count] = encoded[cursor:cursor + count]
        cursor += count
    if cursor != len(encoded):
        raise ValueError("Trailing bytes after EDID delta")
    return bytes(output)


def audit() -> dict:
    original = (ROOT / "backups/ms2109-original.bin").read_bytes()
    rom = (ROOT / "backups/ms2109-maskrom.bin").read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise ValueError("Unexpected EEPROM base image")
    if hashlib.sha256(rom).hexdigest() != ROM_SHA:
        raise ValueError("Unexpected mask-ROM image")

    current, _, _ = build(original, channel_order=True,
                          calibrated_color=True, rom=rom)
    current_code_length = validate(current)
    custom_edid = original[CUSTOM_EDID_CODE - 0xCC00 + 0x30:
                           CUSTOM_EDID_CODE - 0xCC00 + 0x30 + EDID_LENGTH]
    default_edid = rom[ROM_DEFAULT_EDID_CODE:ROM_DEFAULT_EDID_CODE + EDID_LENGTH]
    delta = encode_delta(default_edid, custom_edid)
    reconstructed = decode_delta(default_edid, delta)
    if reconstructed != custom_edid:
        raise AssertionError("Lossless EDID reconstruction failed")

    # The hypothetical post-compression headroom excludes the decoder, the
    # Sharpness request code and all descriptor-response code.
    compressed_code_length = current_code_length - EDID_LENGTH + len(delta)
    return {
        "scope": "offline storage audit only; no firmware candidate or device write",
        "eeprom_bytes": EEPROM_LIMIT,
        "maximum_code_bytes": CODE_LIMIT,
        "qualified_calibrated_stereo_code_bytes": current_code_length,
        "qualified_calibrated_stereo_free_bytes": CODE_LIMIT - current_code_length,
        "custom_edid": {
            "code_address": hex(CUSTOM_EDID_CODE),
            "length": EDID_LENGTH,
            "rom_default_code_address": hex(ROM_DEFAULT_EDID_CODE),
            "changed_bytes": sum(a != b for a, b in zip(default_edid, custom_edid)),
            "changed_runs": delta[0],
            "encoded_length": len(delta),
            "encoded_sha256": hashlib.sha256(delta).hexdigest(),
            "reconstruction_exact": reconstructed == custom_edid,
            "custom_sha256": hashlib.sha256(custom_edid).hexdigest(),
        },
        "hypothetical_after_table_replacement": {
            "code_bytes_before_decoder_and_features": compressed_code_length,
            "remaining_bytes_before_decoder_and_features": CODE_LIMIT - compressed_code_length,
        },
        "unmeasured_components": [
            "EDID delta decoder and ROM-compatible EDID upload path",
            "CC10 return-address multiplexing and preservation of factory EDID callback",
            "validated UVC Sharpness SET_CUR data-stage/completion path",
            "GET_CUR/MIN/MAX/RES/DEF/INFO/LEN replies and strict request validation",
            "FE84/FE85 repair after startup and each delegated video configuration",
            "active and other-speed descriptor response patching",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
