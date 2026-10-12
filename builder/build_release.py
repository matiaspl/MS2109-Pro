#!/usr/bin/env python3
"""Build the reproducible MS2109-Pro EEPROM image from the pinned base files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_builder import validate
from qualified_release import build_qualified_release, PROCAM, BASE_SHA256

EXPECTED_SHA256 = "64d761a92fdfc140222a6d24e316eb212ce17fa1ec43c33517011b2d7527a769"
BASE_EEPROM = ROOT / "firmware/base/qualified-eeprom.bin"
MASK_ROM = ROOT / "firmware/base/ms2109-maskrom.bin"

def build_release():
    image, overlay, entry = build_qualified_release(BASE_EEPROM.read_bytes())
    if hashlib.sha256(image).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Release image hash mismatch")
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
        "qualified_baseline_sha256": BASE_SHA256,
        "startup_procamp": PROCAM,
        "source_renderer": "direct display-native RGB patches",
        "qualification": "runtime controls and baseline live-qualified; rebuilt startup image not cold-boot tested",
        "edid": "baseline ROM-derived EDID with verified 8-bit capability patch; no sRGB edit",
        "uvc_controls": "stock mask-ROM descriptor and request handling",
        "usb_header_names": {"video":"MS2109-Pro","audio":"MS2109-Pro"},
        "cold_restart_descriptor": {"fps_approx":[30,30,25,20,10],"default_interval_100ns":333333,"qualification":"inherited baseline descriptor repair; new startup image has not been cold-boot tested"},
        "video_name": "MS2109-Pro",
        "audio_name": "MS2109-Pro",
        "mjpeg_1080p_intervals_100ns": [333333, 333333, 400000, 500000, 1000000],
    }
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {output} ({len(image)} bytes, SHA-256 {metadata['output_sha256']})")


if __name__ == "__main__":
    main()
