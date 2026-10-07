#!/usr/bin/env python3
"""Capture first delivered YUY2/MJPEG frames across three manual USB reconnects."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile

from probe_colors import write_json

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
              "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_format(directory: Path) -> bool:
    metadata_path = directory / "usb-capture.json"
    requests_path = directory / "control-requests.jsonl"
    if not metadata_path.is_file() or not requests_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text())
    requests = requests_path.read_text()
    display_path = directory.parent / f"{directory.name}-display-ready.json"
    if not display_path.is_file():
        return False
    display = json.loads(display_path.read_text())
    return (metadata.get("exit_code") == 0
            and metadata.get("frames_captured") == 8
            and metadata.get("frames_skipped_for_settling") == 0
            and metadata.get("getter_profile") == "GET_CUR only"
            and metadata.get("control_profile") == "untouched"
            and metadata.get("controls_restoration_ok") is True
            and display.get("target_display_available") is True
            and display.get("display_profile_matches") is True
            and display.get("window_screen") == "HDMI TO USB"
            and isinstance(display.get("display_generation"), int)
            and '"direction":"OUT"' not in requests)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be between 60 and 1800")
    root = args.capture_root.resolve()
    inputs_path = root / "qualification-inputs.json"
    raw = root / "raw"
    if not inputs_path.is_file() or not raw.is_dir():
        parser.error("capture_root must be an existing qualification bundle")
    attempt = 1
    while True:
        run_tag = f"reconnect-attempt-{attempt}"
        chart = root / f"reconnect-chart-{run_tag}"
        output_marker = raw / run_tag
        log_path = root / f"reconnect-cycles-{run_tag}-runner.log"
        trial_paths = [raw / f"{run_tag}-cycle-{cycle}" for cycle in range(1, 4)]
        if (not chart.exists() and not output_marker.exists() and not log_path.exists()
                and all(not path.exists() and not path.with_name(path.name + "-incomplete").exists()
                        for path in trial_paths)):
            break
        attempt += 1

    compiled: dict[str, str] = {}
    run_returncode = None
    run_output = ""
    with tempfile.TemporaryDirectory(prefix="ms2109-reconnect-qualification-") as temporary:
        temp = Path(temporary)
        capture, admin, display = (temp / name for name in ("capture", "admin", "display"))
        commands = {
            "capture": ["clang", "-Wall", "-Wextra", "-O2", "-I/opt/homebrew/include",
                        "-L/opt/homebrew/lib", str(ROOT / "tools/capture_video_uvc.c"),
                        "-luvc", "-o", str(capture)],
            "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit",
                      "-framework", "Security", str(ROOT / "tools/run_capture_video_uvc_admin.m"),
                      "-o", str(admin)],
            "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                        *[item for framework in FRAMEWORKS for item in ("-framework", framework)],
                        str(ROOT / "tools/color_probe_macos.m"), "-o", str(display)],
        }
        for name, command in commands.items():
            subprocess.run(command, check=True)
            compiled[name] = sha256({"capture": capture, "admin": admin, "display": display}[name])
        run_command = [str(admin), str(capture), str(display), str(root / "chart.json"),
                       str(output_marker), "reconnect-cycles"]
        try:
            result = subprocess.run(run_command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=args.timeout_seconds)
            run_returncode, run_output = result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            run_returncode, run_output = 124, partial + "\nReconnect capture timed out.\n"
        log_path.write_text(run_output)

    completed_cycles = []
    incomplete_cycles = []
    trial_directories = {str(cycle): f"{run_tag}-cycle-{cycle}" for cycle in range(1, 4)}
    for cycle in range(1, 4):
        trial = raw / trial_directories[str(cycle)]
        if not trial.exists():
            continue
        if all(valid_format(trial / mode) for mode in ("yuy2", "mjpeg")):
            completed_cycles.append(cycle)
        else:
            incomplete = trial.with_name(trial.name + "-incomplete")
            trial.rename(incomplete)
            incomplete_cycles.append(cycle)

    inputs = json.loads(inputs_path.read_text())
    inputs["reconnect_first_frames"] = {
        "requested_cycles": 3,
        "completed_cycles": completed_cycles,
        "incomplete_cycles": incomplete_cycles,
        "trial_directories": trial_directories,
        "capture_order": ["yuy2", "mjpeg"],
        "frame_policy": "first eight frames delivered after stream start; no settle delay",
        "control_policy": "GET_CUR only; verifies no OUT requests and unchanged/restored readbacks",
        "chart_source": chart.name,
        "utc_completed": datetime.now(timezone.utc).isoformat(),
        "admin_runner_returncode": run_returncode,
        "source_sha256": {
            name: sha256(ROOT / "tools" / name) for name in (
                "capture_video_uvc.c", "run_capture_video_uvc_admin.m",
                "color_probe_macos.m", "analyze_color_capture.py",
                "qualify_reconnect_cycles.py")
        },
        "compiled_tools_sha256": compiled,
        "runner_log": log_path.name,
    }
    write_json(inputs_path, inputs)

    replay = subprocess.run(["python3", str(ROOT / "tools/reanalyze_color_capture.py"), str(root)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if replay.returncode:
        raise RuntimeError(f"Reconnect captures recorded, but offline reanalysis failed:\n{replay.stdout}")
    print(run_output, end="")
    print(replay.stdout, end="")
    if run_returncode != 0 or completed_cycles != [1, 2, 3]:
        raise RuntimeError(f"Reconnect qualification incomplete; complete cycles: {completed_cycles}; "
                           f"incomplete cycles: {incomplete_cycles}; details: {log_path}")


if __name__ == "__main__":
    main()
