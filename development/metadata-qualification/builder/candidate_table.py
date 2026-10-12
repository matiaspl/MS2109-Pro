#!/usr/bin/env python3
"""EDID delta encoding used by the fixed release builder."""
from __future__ import annotations

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


