#!/usr/bin/env python3
"""Create a deterministic wideband stereo alignment fixture for the MS2109."""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/audio-prbs-reference-20261006.wav"
SAMPLE_RATE = 48000
SEED = 0x21090001


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seconds", type=int, default=24)
    parser.add_argument("--amplitude", type=int, default=3200,
                        help="peak PCM amplitude; default is about -20 dBFS")
    args = parser.parse_args()
    output = args.output.resolve()
    metadata_path = output.with_suffix(".json")
    if not 8 <= args.seconds <= 60 or not 100 <= args.amplitude <= 32767:
        parser.error("seconds must be 8..60 and amplitude must be 100..32767")
    if output.exists() or metadata_path.exists():
        parser.error("Refusing to overwrite an existing reference artifact")

    state = SEED
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for start in range(0, SAMPLE_RATE * args.seconds, 4096):
            count = min(4096, SAMPLE_RATE * args.seconds - start)
            interleaved = array("h")
            for frame in range(start, start + count):
                state ^= (state << 13) & 0xFFFFFFFF
                state ^= state >> 17
                state ^= (state << 5) & 0xFFFFFFFF
                state &= 0xFFFFFFFF
                sample = round((((state & 0xFFFF) - 32768) / 32768) * args.amplitude)
                interleaved.append(sample)
                right_active = frame % (2 * SAMPLE_RATE) >= SAMPLE_RATE // 2
                interleaved.append(sample if right_active else 0)
            if interleaved.itemsize != 2:
                raise RuntimeError("Host array type is not 16-bit")
            if __import__("sys").byteorder != "little":
                interleaved.byteswap()
            wav.writeframes(interleaved.tobytes())

    metadata = {
        "wav": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "sample_format": "signed 16-bit little-endian PCM",
        "duration_seconds": args.seconds,
        "generator": "xorshift32, seed 0x21090001; left is continuous wideband code",
        "channel_relation": "right duplicates the same sample code except during its silence gate",
        "right_silence_gate": "first 0.5 seconds of every 2-second period",
        "peak_amplitude": args.amplitude,
        "writes": "reference file only; no device access",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
