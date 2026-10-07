#!/usr/bin/env python3
"""Run a chart-gated, RAM-only FE84 7A→74 response and settling probe."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image

from ms2109_hid import Device

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EEPROM = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
WIDTH, HEIGHT, FPS = 1280, 720, 10


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_similarity(capture_path, source_path):
    captured = np.asarray(Image.open(capture_path).convert("L"), dtype=np.float32)
    source = np.asarray(Image.open(source_path).convert("L").resize(
        (WIDTH, HEIGHT), Image.Resampling.LANCZOS), dtype=np.float32)
    if captured.shape != (HEIGHT, WIDTH):
        raise RuntimeError(f"Unexpected preflight dimensions: {captured.shape}")
    return float(np.corrcoef(captured.ravel(), source.ravel())[0, 1])


def frame_difference(left_path, right_path):
    left = np.asarray(Image.open(left_path).convert("RGB"), dtype=np.int16)
    right = np.asarray(Image.open(right_path).convert("RGB"), dtype=np.int16)
    if left.shape != right.shape:
        raise RuntimeError("Repeated capture dimensions differ")
    delta = np.abs(left - right)
    changed = np.any(delta != 0, axis=2)
    return {"mean_abs_rgb_delta": round(float(delta.mean()), 6),
            "changed_pixels": int(changed.sum()),
            "changed_pixel_fraction": round(float(changed.mean()), 8),
            "max_abs_rgb_delta": int(delta.max())}


def flat_plane_check(movie_path, expected=None):
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(movie_path),
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                             capture_output=True, check=True, timeout=30)
    frame_bytes = WIDTH * HEIGHT * 3
    if not decoded.stdout or len(decoded.stdout) % frame_bytes:
        raise RuntimeError("Could not decode complete frames for flat-plane validation")
    frames = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(-1, HEIGHT, WIDTH, 3)
    regions = {
        # Large source fields: neutral gray footer, dark and white edge plateaus.
        "gray": (slice(712, 719), slice(20, 1260)),
        "black": (slice(180, 620), slice(80, 250)),
        "white": (slice(180, 620), slice(450, 580)),
    }
    result = {"frame_count": int(len(frames)), "regions": {}}
    for name, (ys, xs) in regions.items():
        plane = frames[:, ys, xs, :]
        color = plane[0, 0, 0].copy()
        changed = np.any(plane != color, axis=3)
        result["regions"][name] = {
            "size_px": [int(xs.stop - xs.start), int(ys.stop - ys.start)],
            "rgb": color.astype(int).tolist(),
            "nonmatching_pixel_samples": int(changed.sum()),
            "max_abs_rgb_delta": int(np.abs(plane.astype(np.int16) - color.astype(np.int16)).max()),
        }
    actual = {name: item["rgb"] for name, item in result["regions"].items()}
    if any(item["nonmatching_pixel_samples"] for item in result["regions"].values()):
        raise RuntimeError(f"Uniform test fields vary; refusing to score: {result}")
    if expected is not None and actual != expected:
        raise RuntimeError(f"Uniform test-field RGB changed from baseline: {actual} != {expected}")
    return result


def capture(label, directory, expected_planes=None):
    movie = directory / f"{label}.mkv"
    image = directory / f"{label}.png"
    log = directory / f"{label}.log"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
               "-f", "avfoundation", "-framerate", str(FPS), "-video_size",
               f"{WIDTH}x{HEIGHT}", "-pixel_format", "yuyv422", "-i", "usb video:none",
               "-t", "2", "-an", "-r", str(FPS), "-c:v", "ffv1", str(movie)]
    with log.open("wb") as stream:
        subprocess.run(command, stdout=stream, stderr=stream, check=True, timeout=20)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-sseof", "-0.2", "-i",
                    str(movie), "-frames:v", "1", "-update", "1", str(image)],
                   check=True, timeout=10)
    return {"movie": str(movie), "image": str(image),
            "image_sha256": digest(image.read_bytes()),
            "flat_plane_check": flat_plane_check(movie, expected_planes)}


def persist_capture(item, output):
    for key in ("movie", "image"):
        source = Path(item[key])
        destination = output / source.name
        shutil.copy2(source, destination)
        item[key] = str(destination.resolve())


def assert_chart_ready(ready_path, initial_state):
    current = json.loads(ready_path.read_text())
    required = (current.get("target_display_available") and
                current.get("display_profile_matches") and
                current.get("window_screen") == "HDMI TO USB" and
                current.get("chart_kind") == "full-frame-raster" and
                current.get("full_frame_image_size") == [1920, 1080] and
                current.get("display_generation") == initial_state.get("display_generation") and
                current.get("display_profile_generation") == initial_state.get("display_profile_generation"))
    if not required:
        raise RuntimeError(f"Chart display changed or is no longer ready: {current}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart-session", type=Path, required=True,
                        help="output directory from show_scaler_chart.py")
    parser.add_argument("--output", type=Path,
                        help="new evidence directory; refuses to overwrite")
    parser.add_argument("--source-image", type=Path,
                        default=ROOT / "artifacts/scaler-f9a0/test-chart-1920x1080.png")
    args = parser.parse_args()
    chart_session = args.chart_session.resolve()
    source_image = args.source_image.resolve()
    output = args.output.resolve() if args.output else ROOT / "artifacts/scaler-f9a0" / (
        "fe84-negative-" + time.strftime("%Y%m%d-%H%M%S")
    )
    if output.exists():
        parser.error(f"refusing to overwrite {output}")
    ready_path = chart_session / "display-ready.json"
    source_render = chart_session / "source-render.png"
    if not ready_path.is_file() or not source_render.is_file() or not source_image.is_file():
        parser.error("chart session must contain display-ready.json and source-render.png")

    state = json.loads(ready_path.read_text())
    if (not state.get("target_display_available") or
            not state.get("display_profile_matches") or
            state.get("window_screen") != "HDMI TO USB" or
            state.get("chart_kind") != "full-frame-raster" or
            state.get("full_frame_image_size") != [1920, 1080]):
        parser.error("chart session is not ready on the verified HDMI display")

    result = {"test": "FE84 7A→74 RAM-only response and settling test",
              "capture_mode": f"{WIDTH}x{HEIGHT} YUY2 at {FPS} fps",
              "chart_session": str(chart_session), "stages": []}
    device = Device()
    original = None
    write_attempted = False
    completed = False
    with tempfile.TemporaryDirectory(prefix="ms2109-fe84-negative-") as temporary:
        temp = Path(temporary)
        try:
            assert_chart_ready(ready_path, state)
            device.identify_eeprom()
            eeprom_before = device.read("eeprom", 0, device.eeprom_size)
            result["eeprom_before_sha256"] = digest(eeprom_before)
            if result["eeprom_before_sha256"] != EXPECTED_EEPROM:
                raise RuntimeError("EEPROM identity changed; refusing RAM write")
            original = device.read("ram", 0xFE84, 1)[0]
            result["registers_before"] = {f"{address:04X}": device.read("ram", address, 1)[0]
                for address in (0xFE80, 0xFE84, 0xFE85, 0xF9A0, 0xF92C, 0xFEBA)}
            expected = {0xFE80: 0x01, 0xFE84: 0x7A, 0xFE85: 0x00,
                        0xF9A0: 0x00, 0xF92C: 0x20, 0xFEBA: 0x00}
            if result["registers_before"] != {f"{a:04X}": v for a, v in expected.items()}:
                raise RuntimeError(f"Unexpected register baseline; refusing test: {result['registers_before']}")

            assert_chart_ready(ready_path, state)
            first = capture("baseline-a", temp)
            flat_reference = {name: plane["rgb"]
                              for name, plane in first["flat_plane_check"]["regions"].items()}
            assert_chart_ready(ready_path, state)
            first_similarity = source_similarity(first["image"], source_image)
            result["chart_similarity_baseline_a"] = round(first_similarity, 6)
            if first_similarity < 0.85:
                raise RuntimeError("Captured frame does not match the scaler chart; no RAM write made")
            second = capture("baseline-b", temp, flat_reference)
            assert_chart_ready(ready_path, state)
            second_similarity = source_similarity(second["image"], source_image)
            result["chart_similarity_baseline_b"] = round(second_similarity, 6)
            if second_similarity < 0.85:
                raise RuntimeError("Second frame does not match the scaler chart; no RAM write made")
            stability = frame_difference(first["image"], second["image"])
            result["baseline_repeat_difference"] = stability
            output.mkdir(parents=True, exist_ok=False)
            persist_capture(first, output)
            persist_capture(second, output)
            if (stability["changed_pixel_fraction"] > 0.002 or
                    stability["mean_abs_rgb_delta"] > 0.1):
                raise RuntimeError("Repeated chart baselines are not stable enough; refusing RAM write")
            result["stages"].append({"state": "FE84=7A", "capture": first,
                                     "repeat_capture": second})

            assert_chart_ready(ready_path, state)
            write_attempted = True
            device.exchange(0xB6, 0xFE84, 0x74)
            result["fe84_after_write"] = device.read("ram", 0xFE84, 1)[0]
            if result["fe84_after_write"] != 0x74:
                raise RuntimeError("FE84=74 readback failed")
            assert_chart_ready(ready_path, state)
            time.sleep(0.5)
            early = capture("candidate-early", temp, flat_reference)
            assert_chart_ready(ready_path, state)
            result["stages"].append({"state": "FE84=74, early", "capture": early,
                                     "fe84_after_capture": device.read("ram", 0xFE84, 1)[0]})
            time.sleep(3)
            late = capture("candidate-late", temp, flat_reference)
            assert_chart_ready(ready_path, state)
            result["stages"].append({"state": "FE84=74, settled", "capture": late,
                                     "fe84_after_capture": device.read("ram", 0xFE84, 1)[0]})
            persist_capture(early, output)
            persist_capture(late, output)
            completed = True
        except BaseException as exc:
            result["error"] = str(exc)
        finally:
            if write_attempted and original is not None:
                try:
                    device.exchange(0xB6, 0xFE84, original)
                    result["fe84_restored"] = device.read("ram", 0xFE84, 1)[0]
                    result["registers_after_restore"] = {
                        f"{address:04X}": device.read("ram", address, 1)[0]
                        for address in (0xFE80, 0xFE84, 0xFE85, 0xF9A0, 0xF92C, 0xFEBA)}
                    eeprom_after = device.read("eeprom", 0, device.eeprom_size)
                    result["eeprom_after_sha256"] = digest(eeprom_after)
                    result["eeprom_unchanged"] = eeprom_before == eeprom_after
                    if completed:
                        time.sleep(3)
                        restored = capture("restored", temp, flat_reference)
                        result["stages"].append({"state": "FE84 restored to 7A", "capture": restored})
                        persist_capture(restored, output)
                except BaseException as exc:
                    result["restore_error"] = str(exc)
            device.close()

    if output.exists():
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result.get("error"):
        raise RuntimeError(result["error"])
    if (not completed or result.get("restore_error") or result.get("fe84_restored") != 0x7A or
            not result.get("eeprom_unchanged")):
        raise RuntimeError("FE84 restore or EEPROM verification failed")


if __name__ == "__main__":
    main()
