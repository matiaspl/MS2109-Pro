#!/usr/bin/env python3
"""Capture MJPEG then YUY2 on one persistent UVC handle, with control reads only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone

from probe_colors import write_json

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
              "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be between 60 and 1800")
    root = args.capture_root.resolve()
    inputs_path = root / "qualification-inputs.json"
    output = root / "raw" / "same-handle"
    chart = root / "same-handle-chart"
    log_path = root / "same-handle-runner.log"
    if not inputs_path.is_file() or output.exists() or chart.exists() or log_path.exists():
        parser.error("capture_root must be an existing qualification bundle with no same-handle trial yet")

    with tempfile.TemporaryDirectory(prefix="ms2109-same-handle-") as temporary:
        temp = Path(temporary)
        capture = temp / "capture"
        admin = temp / "admin"
        display = temp / "display"
        commands = {
            "capture": ["clang", "-Wall", "-Wextra", "-Werror", "-O2", "-I/opt/homebrew/include",
                        "-L/opt/homebrew/lib", str(ROOT / "tools/capture_uvc_same_handle.c"),
                        "-luvc", "-lhidapi", "-lusb-1.0", "-o", str(capture)],
            "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit", "-framework", "Security",
                      str(ROOT / "tools/run_capture_video_uvc_admin.m"), "-o", str(admin)],
            "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                        *[item for framework in FRAMEWORKS for item in ("-framework", framework)],
                        str(ROOT / "tools/color_probe_macos.m"), "-o", str(display)],
        }
        for command in commands.values():
            subprocess.run(command, check=True)
        run_command = [str(admin), str(capture), str(display), str(root / "chart.json"),
                       str(output), "same-handle"]
        try:
            result = subprocess.run(run_command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            log_path.write_text(partial + "\nSame-handle acquisition timed out; no success is implied.\n")
            raise RuntimeError(f"Same-handle capture timed out; log: {log_path}") from error
        log_path.write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f"Same-handle capture failed ({result.returncode}); log: {log_path}")
        inputs = json.loads(inputs_path.read_text())
        inputs["same_handle_switch"] = {
            "order": ["mjpeg", "yuy2"],
            "persistent_uvc_handle": True,
            "control_access": "GET_CUR only; no SET_CUR calls",
            "utc_completed": datetime.now(timezone.utc).isoformat(),
            "source_sha256": {
                "capture_uvc_same_handle.c": sha256(ROOT / "tools/capture_uvc_same_handle.c"),
                "run_capture_video_uvc_admin.m": sha256(ROOT / "tools/run_capture_video_uvc_admin.m"),
                "color_probe_macos.m": sha256(ROOT / "tools/color_probe_macos.m"),
            },
            "compiled_tools": {name: sha256(path) for name, path in
                                (("capture", capture), ("admin", admin), ("display", display))},
        }
        write_json(inputs_path, inputs)

    replay = subprocess.run(["python3", str(ROOT / "tools/reanalyze_color_capture.py"), str(root)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    print(result.stdout, end="")
    print(replay.stdout, end="")


if __name__ == "__main__":
    main()
