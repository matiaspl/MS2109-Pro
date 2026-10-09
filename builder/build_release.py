#!/usr/bin/env python3
"""Build the reproducible MS2109-Pro EEPROM image from the pinned base files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_builder import build, validate

EXPECTED_SHA256 = "0d8d3139b51edc4ff283dab33f00c2270f2134d95bce4bf7a351dcf38c14bb82"
BASE_EEPROM = ROOT / "firmware/base/original-eeprom.bin"
MASK_ROM = ROOT / "firmware/base/ms2109-maskrom.bin"


def build_release():
    original = BASE_EEPROM.read_bytes()
    rom = MASK_ROM.read_bytes()
    image, overlay, entry = build(
        original,
        rom=rom,
        uvc_control_profile=True,
        uvc_control_edid="rom",
        release_layout=True,
    )
    actual = hashlib.sha256(image).hexdigest()
    if actual != EXPECTED_SHA256:
        raise ValueError(f"Release image hash mismatch: {actual}")
    validate(image)
    return image, overlay, entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new firmware output path (must not exist)")
    args = parser.parse_args()
    output = args.output.resolve()
    manifest = output.with_suffix(".json")
    if output.exists() or manifest.exists():
        parser.error("output or its manifest already exists; choose a new path")
    image, overlay, entry = build_release()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    metadata = {
        "output_sha256": hashlib.sha256(image).hexdigest(),
        "base_eeprom_sha256": hashlib.sha256(BASE_EEPROM.read_bytes()).hexdigest(),
        "mask_rom_sha256": hashlib.sha256(MASK_ROM.read_bytes()).hexdigest(),
        "eeprom_bytes": len(image),
        "overlay_bytes": len(overlay),
        "entry_address": hex(entry),
        "build_source_commit": "85026a5",
        "uvc_controls": "stock descriptor and request handling",
        "video_name": "usb video",
        "audio_name": "usb video",
        "mjpeg_1080p_intervals_100ns": [333333, 333333, 400000, 500000, 1000000],
    }
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {output} ({len(image)} bytes, SHA-256 {metadata['output_sha256']})")


if __name__ == "__main__":
    main()
