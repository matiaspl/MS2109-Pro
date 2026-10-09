#!/usr/bin/env python3
"""Test a one-shot EP2 FIFO reset at audio SET_INTERFACE startup (RAM only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from audio_ram_probe import Probe
from qualify_stereo_audio import ROOT, REFERENCE as DEFAULT_REFERENCE, default_hdmi_output, read_device_state


def best_lag(analysis: dict) -> int:
    return max(analysis["lag_correlations"],
               key=lambda item: item["correlation_ch0_n_ch1_n_plus_lag"])["lag_samples"]


def capture_candidate(output: Path, seconds: int, probe: Probe, reference: Path) -> dict:
    capture_cmd = ["ffmpeg", "-n", "-hide_banner", "-f", "avfoundation",
                   "-i", ":usb video", "-t", str(seconds), "-vn",
                   "-c:a", "pcm_s16le", str(output)]
    capture = subprocess.Popen(capture_cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    playback = None
    capture_log = ""
    playback_log = ""
    telemetry = None
    try:
        time.sleep(0.4)
        playback = subprocess.Popen(["afplay", str(reference)],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True)
        _, capture_log = capture.communicate(timeout=seconds + 15)
        if capture.returncode != 0:
            raise RuntimeError(f"FFmpeg capture failed: {capture_log[-3000:]}")
    finally:
        if capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=5)
        if playback is not None:
            if playback.poll() is None:
                playback.terminate()
                playback.wait(timeout=5)
            if playback.stderr:
                playback_log = playback.stderr.read()
                playback.stderr.close()
        probe.write(0xde2b, b"\x00")
        telemetry = probe.d.read("ram", 0xde2a, 3)

    return {
        "capture_command": capture_cmd,
        "capture_returncode": capture.returncode,
        "capture_log_tail": capture_log[-3000:],
        "playback_log_tail": playback_log[-1000:],
        "stream_monitor_de2a_de2c": telemetry.hex(),
        "reset_trigger_count": telemetry[2],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", action="store_true",
                        help="required to install the temporary RAM hook")
    parser.add_argument("--seconds", type=int, default=8)
    parser.add_argument("--run-id", default="attempt2",
                        help="safe filename suffix; existing outputs are never overwritten")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE,
                        help="stereo WAV to play to HDMI during baseline and candidate captures")
    args = parser.parse_args()
    if not args.experiment:
        parser.error("RAM experiment; pass --experiment only with the known HDMI left/right fixture")
    if not 6 <= args.seconds <= 20:
        parser.error("--seconds must be between 6 and 20")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.run_id):
        parser.error("--run-id may contain only letters, digits, '_' and '-' (max 32 chars)")

    stem = f"audio-stream-start-reset-{args.run_id}"
    baseline = ROOT / f"artifacts/{stem}-baseline.wav"
    candidate = ROOT / f"artifacts/{stem}-candidate.wav"
    hook_path = ROOT / f"artifacts/{stem}-hook.bin"
    outputs = (baseline, baseline.with_suffix(".analysis.json"), baseline.with_suffix(".json"),
               candidate, candidate.with_suffix(".analysis.json"), candidate.with_suffix(".json"),
               hook_path)
    if any(path.exists() for path in outputs):
        parser.error("Refusing to overwrite existing sample-offset experiment outputs")
    reference = args.reference.resolve()
    if not reference.is_file():
        raise RuntimeError(f"Missing HDMI reference signal: {reference}")

    # The baseline helper fails closed unless HDMI TO USB is the default output
    # and the existing FE60/stereo routing is active.
    default_hdmi_output()
    baseline_command = ["python3", str(ROOT / "tools/qualify_stereo_audio.py"),
                        "--output", str(baseline), "--seconds", str(args.seconds),
                        "--reference", str(reference)]
    subprocess.run(baseline_command, check=True)
    baseline_metadata = json.loads(baseline.with_suffix(".json").read_text())
    baseline_analysis = json.loads(baseline.with_suffix(".analysis.json").read_text())
    if best_lag(baseline_analysis) != -1:
        raise RuntimeError("Baseline did not reproduce the known one-sample offset; candidate not installed")

    before = read_device_state()
    hook_code = Probe.build_code(stream_start_reset=True)
    hook_path.write_bytes(hook_code)
    probe = Probe(stream_start_reset=True)
    candidate_result = None
    monitor = None
    try:
        probe.write(0xde2b, b"\x01")  # arm transition detector
        candidate_result = capture_candidate(candidate, args.seconds, probe, reference)
        monitor = candidate_result["stream_monitor_de2a_de2c"]
    finally:
        probe.close()

    after = read_device_state()
    analyze_cmd = ["python3", str(ROOT / "tools/analyze_audio.py"), str(candidate),
                   "--output", str(candidate.with_suffix(".analysis.json"))]
    subprocess.run(analyze_cmd, check=True)
    candidate_analysis = json.loads(candidate.with_suffix(".analysis.json").read_text())
    left, right = candidate_analysis["channels"]
    channel_order_ok = (left["silent_window_fraction"] < 0.05
                        and 0.10 < right["silent_window_fraction"] < 0.50)
    telemetry = bytes.fromhex(monitor)
    trigger_count = telemetry[2]
    verified = (trigger_count == 1 and best_lag(candidate_analysis) == 0
                and channel_order_ok and candidate_analysis["rate"] == 48000
                and before == after)
    metadata = {
        "run_id": args.run_id,
        "scope": "temporary RAM hook only; no EEPROM writes",
        "hypothesis": "poll IRAM 0x3A on every common-hook call and flush endpoint 2 once when alt 1 is selected",
        "monitor_before_mailbox_idle_path": True,
        "hook_sha256": hashlib.sha256(hook_code).hexdigest(),
        "hook_bytes": len(hook_code),
        "reference_wav": str(reference.relative_to(ROOT)) if reference.is_relative_to(ROOT) else str(reference),
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "default_hdmi_output": default_hdmi_output(),
        "device_state_before": before,
        "device_state_after": after,
        "baseline": {
            "wav": str(baseline.relative_to(ROOT)),
            "sha256": baseline_metadata["capture_sha256"],
            "best_lag_samples": best_lag(baseline_analysis),
        },
        "candidate": {
            "wav": str(candidate.relative_to(ROOT)),
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "best_lag_samples": best_lag(candidate_analysis),
            "reset_trigger_count": trigger_count,
            "channel_order_ok": channel_order_ok,
        },
        "ram_hook_restored": True,
        "verified": verified,
    }
    candidate.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))
    if not verified:
        print("Candidate rejected: the reset did not prove a one-sample correction.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
