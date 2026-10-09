"""Inspect saved MS2109 ROM color metadata without opening a USB device."""

import argparse
import hashlib
import json
from pathlib import Path


ROM_SHA256 = "b383ef31fca43ebc58a22be8e342d9a1e33ec1cc15afce02921910b0ca358bc8"


def decode_configuration(rom, start):
    if rom[start:start + 2] not in (b"\x09\x02", b"\x09\x07"):
        raise ValueError(f"Missing configuration header at {start:04x}")
    end = start + int.from_bytes(rom[start + 2:start + 4], "little")
    if end > len(rom):
        raise ValueError("Configuration extends beyond the saved ROM")
    result = {"offset": hex(start), "end": hex(end), "formats": [], "processing_units": []}
    pos = start
    video_streaming = False
    video_control = False
    current_format = None
    while pos < end:
        length = rom[pos]
        if length < 2 or pos + length > end:
            raise ValueError(f"Invalid descriptor at {pos:04x}")
        data = rom[pos:pos + length]
        if data[1] == 4 and length == 9:
            video_streaming = data[5:7] == b"\x0e\x02"
            video_control = data[5:7] == b"\x0e\x01"
            current_format = None
        elif data[1] == 0x24 and length >= 3:
            subtype = data[2]
            if video_control and subtype == 5 and length >= 10:
                size = data[7]
                controls = data[8:8 + size]
                result["processing_units"].append({
                    "offset": hex(pos), "bytes": data.hex(" "),
                    "controls_bitmap": hex(int.from_bytes(controls, "little")),
                })
            if video_streaming and ((subtype == 6 and length == 11) or
                                    (subtype == 4 and length == 27)):
                current_format = {
                    "offset": hex(pos), "index": data[3], "frame_count": data[4],
                    "format": "MJPEG" if subtype == 6 else data[5:9].decode("ascii"),
                }
                if subtype == 4:
                    current_format["bits_per_pixel"] = data[21]
                result["formats"].append(current_format)
            if video_streaming and subtype == 0x0d and length == 6:
                if current_format is None:
                    raise ValueError("Color descriptor has no preceding video format")
                current_format["color_matching"] = {
                    "offset": hex(pos), "bytes": data.hex(" "),
                    "primaries": data[3], "transfer": data[4], "matrix": data[5],
                    "quantization_range": "not encoded in this descriptor",
                }
        pos += length
    return result


def decode_edid(rom, start):
    if rom[start:start + 8] != bytes.fromhex("00 ff ff ff ff ff ff 00"):
        raise ValueError("Missing EDID header")
    size = 128 * (1 + rom[start + 126])
    data = rom[start:start + size]
    if len(data) != size or any(sum(data[i:i + 128]) & 255 for i in range(0, size, 128)):
        raise ValueError("Invalid EDID length or block checksum")
    result = {
        "offset": hex(start), "length": size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "version": f"{data[18]}.{data[19]}",
        "gamma": None if data[23] == 255 else 1 + data[23] / 100,
        "base_features": hex(data[24]),
        "chromaticities": {}, "cta_data_blocks": [],
        "block_checksum_remainders": [sum(data[i:i + 128]) & 255 for i in range(0, size, 128)],
    }
    for name, high, low, shift in (
        ("red_x", 27, 25, 6), ("red_y", 28, 25, 4),
        ("green_x", 29, 25, 2), ("green_y", 30, 25, 0),
        ("blue_x", 31, 26, 6), ("blue_y", 32, 26, 4),
        ("white_x", 33, 26, 2), ("white_y", 34, 26, 0),
    ):
        result["chromaticities"][name] = ((data[high] << 2) | ((data[low] >> shift) & 3)) / 1024
    if size >= 256 and data[128] == 2:
        result["cta_flags"] = hex(data[131])
        result["cta_ycbcr_444"] = bool(data[131] & 0x20)
        result["cta_ycbcr_422"] = bool(data[131] & 0x10)
        pos = 132
        end = 128 + data[130]
        if not 132 <= end <= 255:
            raise ValueError("Invalid CTA data-block boundary")
        while pos < end:
            length = data[pos] & 31
            if pos + 1 + length > end:
                raise ValueError("Invalid CTA data block")
            result["cta_data_blocks"].append({
                "offset": hex(start + pos), "tag": data[pos] >> 5,
                "payload": data[pos + 1:pos + 1 + length].hex(" "),
            })
            pos += 1 + length
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    digest = hashlib.sha256(rom).hexdigest()
    if digest != ROM_SHA256:
        raise SystemExit("Offsets are qualified only for the saved MS2109 ROM SHA256")
    result = {
        "rom": str(args.rom), "rom_size": len(rom), "rom_sha256": digest,
        "scope": "Offline templates; no current USB descriptors or pixels measured",
        "configurations": [decode_configuration(rom, start) for start in (0x7111, 0x75cc, 0xc03a)],
        "edid": decode_edid(rom, 0x7738),
    }
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
