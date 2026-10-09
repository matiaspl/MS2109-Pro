#!/usr/bin/env python3
"""Audit an injected JPEG ICC APP2 segment and compare common file decoders."""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np


def scan(payload: bytes):
    if payload[:2] != b"\xff\xd8":
        raise ValueError("JPEG SOI missing")
    i = 2
    segments = []
    while i < len(payload):
        if payload[i] != 255:
            raise ValueError(f"invalid marker boundary at {i}")
        while payload[i] == 255:
            i += 1
        marker = payload[i]
        i += 1
        if marker in (0xDA, 0xD9):
            return segments, i - 2
        length = int.from_bytes(payload[i:i+2], "big")
        if length < 2 or i + length > len(payload):
            raise ValueError("invalid JPEG segment length")
        segments.append((marker, payload[i+2:i+length]))
        i += length
    raise ValueError("JPEG SOS missing")


def icc_tags(profile: bytes):
    if len(profile) < 132:
        raise ValueError("ICC profile too short")
    count = int.from_bytes(profile[128:132], "big")
    tags = {}
    for j in range(count):
        pos = 132 + j * 12
        signature = profile[pos:pos+4].decode("ascii")
        offset, size = struct.unpack(">II", profile[pos+4:pos+12])
        if offset + size > len(profile):
            raise ValueError(f"ICC tag {signature} points outside the profile")
        tags[signature] = profile[offset:offset+size]
    return tags


def rgb(path: Path):
    a = np.fromfile(path, dtype=np.uint8)
    if a.size != 1920 * 1080 * 4:
        raise ValueError(f"unexpected decoded frame length in {path}")
    return a.reshape(1080, 1920, 4)[:, :, :3].astype(np.int16)


def compare_decoders(root: Path):
    results = {}
    for decoder, prefix in (("Apple ImageIO", "calibrated"), ("FFmpeg", "calibrated-ffmpeg")):
        before = rgb(root / f"{prefix}-original.rgba")
        after = rgb(root / f"{prefix}-tagged.rgba")
        delta = after - before
        results[decoder] = {
            "rgb_rms_change": float(np.sqrt(np.mean(delta.astype(np.float64) ** 2))),
            "maximum_absolute_change": int(np.abs(delta).max()),
            "changed_components": int(np.count_nonzero(delta)),
        }
    before = np.fromfile(root / "calibrated-original.ycbcr", np.uint8)
    after = np.fromfile(root / "calibrated-tagged.ycbcr", np.uint8)
    if before.shape != after.shape:
        raise ValueError("libjpeg output dimensions differ")
    results["libjpeg-turbo raw YCbCr"] = {
        "identical_sample_bytes": bool(np.array_equal(before, after)),
        "maximum_absolute_change": int(np.abs(before.astype(np.int16) - after.astype(np.int16)).max()),
    }
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("tagged", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--analysis-dir", type=Path, required=True)
    a = p.parse_args()
    original, tagged = a.source.read_bytes(), a.tagged.read_bytes()
    source_segments, source_scan = scan(original)
    tagged_segments, tagged_scan = scan(tagged)
    app2 = [data for marker, data in tagged_segments if marker == 0xE2 and data.startswith(b"ICC_PROFILE\0")]
    if len(app2) != 1 or app2[0][12:14] != b"\x01\x01":
        raise ValueError("expected exactly one sequence-1 ICC APP2 segment")
    profile = app2[0][14:]
    if tagged[:tagged_scan] == original[:source_scan]:
        raise ValueError("no inserted marker found before SOS")
    # Strip the added marker, then require exact original marker and entropy data.
    marker_start = tagged.find(b"\xff\xe2" + (len(app2[0]) + 2).to_bytes(2, "big"), 2, tagged_scan)
    if marker_start < 0:
        raise ValueError("APP2 marker not located in original header region")
    marker_end = marker_start + 4 + len(app2[0])
    reconstructed = tagged[:marker_start] + tagged[marker_end:]
    if reconstructed != original:
        raise ValueError("source JPEG data changed beyond the inserted APP2 marker")
    tags = icc_tags(profile)
    cicp = tags.get("cicp")
    if cicp != b"cicp\0\0\0\0\x01\x01\x01\x01":
        raise ValueError("CICP tag is not BT.709 full-range")
    decoders = compare_decoders(a.analysis_dir)
    report = {
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "tagged_sha256": hashlib.sha256(tagged).hexdigest(),
        "profile_sha256": hashlib.sha256(profile).hexdigest(),
        "source_scan_offset": source_scan,
        "tagged_scan_offset": tagged_scan,
        "jpeg_bytes_preserved_after_removing_app2": True,
        "icc_profile_bytes": len(profile),
        "icc_tag_signatures": sorted(tags),
        "cicp": {"primaries": 1, "transfer": 1, "matrix": 1, "full_range": True},
        "decoder_results": decoders,
        "qualification": "file-decoder experiment only; no live AVFoundation qualification",
    }
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
