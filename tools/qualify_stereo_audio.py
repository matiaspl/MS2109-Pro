#!/usr/bin/env python3
"""Capture the HDMI left/right audio fixture without changing device state."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from ms2109_hid import Device


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "artifacts" / "mac-hdmi-reference.wav"


def read_device_state():
    device = Device()
    try:
        return {
            "fe60": device.read("ram", 0xFE60, 1)[0],
            "audio_channels": device.read("ram", 0xC4C5, 1)[0],
            "audio_sample_rate_descriptor": device.read("ram", 0xC4C9, 3).hex(),
        }
    finally:
        device.close()


def default_hdmi_output():
    data = json.loads(subprocess.check_output(
        ["system_profiler", "SPAudioDataType", "-json"], text=True))
    outputs = [item for group in data["SPAudioDataType"]
               for item in group.get("_items", [])
               if item.get("coreaudio_default_audio_output_device") == "spaudio_yes"]
    if (len(outputs) != 1 or outputs[0].get("coreaudio_device_transport") != "coreaudio_device_type_hdmi"
            or outputs[0].get("_name") != "HDMI TO USB"):
        raise RuntimeError("Default audio output must be HDMI TO USB; no settings were changed")
    return outputs[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", default=8, type=int)
    parser.add_argument("--reference", type=Path, default=REFERENCE,
                        help="stereo WAV to play to the verified HDMI output")
    args = parser.parse_args()
    output = args.output.resolve()
    reference = args.reference.resolve()
    analysis_path = output.with_suffix(".analysis.json")
    metadata_path = output.with_suffix(".json")
    if not 6 <= args.seconds <= 20:
        parser.error("--seconds must be between 6 and 20")
    if any(path.exists() for path in (output, analysis_path, metadata_path)):
        parser.error("Refusing to overwrite existing qualification outputs")
    if not reference.is_file() or shutil.which("ffmpeg") is None or shutil.which("afplay") is None:
        raise RuntimeError("Reference WAV, ffmpeg, and afplay are required")

    audio_output = default_hdmi_output()
    before = read_device_state()
    if before["fe60"] != 0x01 or before["audio_channels"] != 2 or before["audio_sample_rate_descriptor"] != "80bb00":
        raise RuntimeError(f"Live stereo/FE60 state does not match expected 01/2/48000 Hz: {before}")

    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_command = ["ffmpeg", "-n", "-hide_banner", "-f", "avfoundation", "-i", ":usb video",
                      "-t", str(args.seconds), "-vn", "-c:a", "pcm_s16le", str(output)]
    capture = subprocess.Popen(ffmpeg_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    playback = None
    try:
        time.sleep(0.4)
        playback = subprocess.Popen(["afplay", str(reference)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        _, capture_log = capture.communicate(timeout=args.seconds + 15)
        if capture.returncode != 0:
            raise RuntimeError(f"FFmpeg audio capture failed ({capture.returncode}): {capture_log[-4000:]}")
    finally:
        if capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=5)
        if playback is not None and playback.poll() is None:
            playback.terminate()
            playback.wait(timeout=5)
        if playback is not None and playback.stderr:
            playback.stderr.close()

    subprocess.run(["python3", str(ROOT / "tools" / "analyze_audio.py"), str(output),
                    "--output", str(analysis_path)], check=True)
    after = read_device_state()
    analysis = json.loads(analysis_path.read_text())
    left, right = analysis["channels"]
    left_continuous = left["peak"] > 100 and left["silent_window_fraction"] < 0.05
    right_gapped = right["peak"] > 100 and 0.10 < right["silent_window_fraction"] < 0.50
    if after != before:
        raise RuntimeError(f"Read-only device state changed during capture: before={before}, after={after}")
    if analysis["rate"] != 48000 or not left_continuous or not right_gapped:
        raise RuntimeError("Fresh fixture did not verify continuous left and gapped right channels")

    metadata = {
        "reference_wav": str(reference.relative_to(ROOT)) if reference.is_relative_to(ROOT) else str(reference),
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "capture_wav": str(output),
        "capture_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "capture_backend": "AVFoundation CoreAudio input :usb video",
        "system_profiler_default_output": audio_output,
        "device_state_before": before,
        "device_state_after": after,
        "register_policy": "read-only; no FE60, EEPROM, or picture-control writes",
        "analysis": str(analysis_path),
        "verified": {"48_khz": analysis["rate"] == 48000,
                     "channel_0_continuous_left": left_continuous,
                     "channel_1_gapped_right": right_gapped,
                     "device_state_unchanged": after == before},
        "known_sample_offset": analysis["lag_correlations"],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
