#!/usr/bin/env python3
"""Reversible F9A0 bit-0 video probe; raw frames stay in temporary storage."""
import hashlib
import argparse
import json
import signal
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from ms2109_hid import Device

OUT = Path("artifacts/scaler-f9a0/live-02")
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
WIDTH, HEIGHT, FPS = 1280, 720, 10


def save(result):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def capture_metrics(label):
    """Capture a short YUY2 stream, measure one RGB frame, then delete pixels."""
    with tempfile.TemporaryDirectory(prefix="ms2109-f9a0-") as tmp:
        movie = Path(tmp) / "capture.mkv"
        log = Path(tmp) / "capture.log"
        with log.open("wb") as stream_log:
            p = subprocess.Popen([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
                "-f", "avfoundation", "-framerate", str(FPS), "-video_size",
                f"{WIDTH}x{HEIGHT}", "-pixel_format", "yuyv422", "-i",
                "usb video:none", "-t", "2.5", "-an", "-r", str(FPS),
                "-c:v", "ffv1", str(movie),
            ], stdout=stream_log, stderr=stream_log)
            try:
                rc = p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                raise RuntimeError(f"{label}: capture timed out")
        if rc:
            raise RuntimeError(f"{label}: capture failed: {log.read_text(errors='replace')[-1200:]}")
        decoded = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(movie),
            "-vf", r"select=eq(n\,10)", "-frames:v", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "pipe:1",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
        pixels = np.frombuffer(decoded.stdout, dtype=np.uint8)
        if pixels.size != WIDTH * HEIGHT * 3:
            raise RuntimeError(f"{label}: expected one RGB frame, got {pixels.size} bytes")
        # int32 avoids overflow in the weighted luma sum (255 * 150 > int16 max).
        rgb = pixels.reshape((HEIGHT, WIDTH, 3)).astype(np.int32)
        y = (77 * rgb[:, :, 0] + 150 * rgb[:, :, 1] + 29 * rgb[:, :, 2]) >> 8
        # A compact sharpness proxy: average first-difference magnitude.
        gx = np.abs(np.diff(y, axis=1))
        gy = np.abs(np.diff(y, axis=0))
        return {
            "capture_size": [WIDTH, HEIGHT],
            "sampled_luma_mean": round(float(y.mean()), 3),
            "sampled_luma_stddev": round(float(y.std()), 3),
            "mean_abs_horizontal_luma_step": round(float(gx.mean()), 3),
            "mean_abs_vertical_luma_step": round(float(gy.mean()), 3),
            "sampled_unique_rgb_count": int(np.unique(rgb[::8, ::8].reshape(-1, 3), axis=0).shape[0]),
            "raw_frame_sha256": hashlib.sha256(decoded.stdout).hexdigest(),
        }


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT, help="new evidence directory (must not exist)")
    OUT = parser.parse_args().out
    if OUT.exists():
        raise RuntimeError(f"Refusing to overwrite {OUT}")
    d = Device()
    original = None
    wrote = False
    result = {
        "scope": "F9A0 bit 0 temporary RAM-only test; 1280x720 YUY2 capture",
        "input_state": "active HDMI baseline confirmed nonuniform before test",
        "stages": [],
    }

    def on_signal(signum, frame):
        raise RuntimeError(f"interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        d.identify_eeprom()
        before = d.read("eeprom", 0, d.eeprom_size)
        result["eeprom_before_sha256"] = hashlib.sha256(before).hexdigest()
        if result["eeprom_before_sha256"] != EXPECTED_EEPROM:
            raise RuntimeError("EEPROM identity changed; refusing RAM write")
        original = d.read("ram", 0xF9A0, 1)[0]
        result["f9a0_original"] = original
        result["f92c_before"] = d.read("ram", 0xF92C, 1)[0]
        result["feba_before"] = d.read("ram", 0xFEBA, 1)[0]
        if original & 0xFE:
            raise RuntimeError(f"Unexpected F9A0 other bits {original:02x}; refusing test")
        target = (original & 0xFE) | (original ^ 0x01)
        result["f9a0_test_value"] = target
        baseline = capture_metrics("baseline")
        if baseline["sampled_luma_stddev"] < 5 or baseline["sampled_unique_rgb_count"] < 20:
            raise RuntimeError("Baseline is not a valid nonuniform picture; refusing RAM write")
        result["stages"].append({"name": "baseline", **baseline})
        save(result)

        wrote = True
        d.exchange(0xB6, 0xF9A0, target)
        result["f9a0_after_write"] = d.read("ram", 0xF9A0, 1)[0]
        save(result)
        if result["f9a0_after_write"] != target:
            raise RuntimeError("F9A0 test value did not read back")
        result["stages"].append({"name": "bit0-toggled", **capture_metrics("bit0-toggled")})
        result["f9a0_after_test_capture"] = d.read("ram", 0xF9A0, 1)[0]
        if result["f9a0_after_test_capture"] != target:
            raise RuntimeError("Capture path changed F9A0 during the test")
        save(result)
    except BaseException as error:
        result["error"] = str(error)
        save(result)
        raise
    finally:
        if wrote and original is not None:
            try:
                d.exchange(0xB6, 0xF9A0, original)
                result["f9a0_restored"] = d.read("ram", 0xF9A0, 1)[0]
                result["f92c_after"] = d.read("ram", 0xF92C, 1)[0]
                result["feba_after"] = d.read("ram", 0xFEBA, 1)[0]
                after = d.read("eeprom", 0, d.eeprom_size)
                result["eeprom_after_sha256"] = hashlib.sha256(after).hexdigest()
                result["eeprom_unchanged"] = before == after
                save(result)
            except Exception as error:
                result["restore_error"] = str(error)
                save(result)
        d.close()
    if result.get("f9a0_restored") != original or not result.get("eeprom_unchanged"):
        raise RuntimeError("F9A0 restore or EEPROM verification failed")
    result["stages"].append({"name": "restored", **capture_metrics("restored")})
    save(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
