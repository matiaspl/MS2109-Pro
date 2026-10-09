#!/usr/bin/env python3
"""Capture a reproducible MS2109 raw-USB and AVFoundation color bundle.

The native helper shows one administrator prompt, preserves original YUY2 and
MJPEG payloads, runs paired control-getter/reapply and format-order trials,
restores the UVC driver, then records AVFoundation packed YUV and BGRA output.
Run the command outside the macOS shell sandbox because USB/AVFoundation access
and the native administrator authorization dialog are hardware-dependent.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from calibrate_colors import chart
from probe_colors import write_json

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = ["Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
              "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit"]


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(args):
    out = args.output.resolve()
    if out.exists():
        raise ValueError("Use a new output directory; previous evidence is preserved")
    out.parent.mkdir(parents=True, exist_ok=True)
    pattern_path = out.parent / (out.name + ".chart.json")
    if pattern_path.exists():
        raise ValueError(f"Chart manifest already exists: {pattern_path}")
    write_json(pattern_path, chart())
    compile_commands = {}
    with tempfile.TemporaryDirectory(prefix="ms2109-qualification-") as td:
        temp = Path(td)
        capture, admin, display, decoder = (temp / name for name in ("capture", "admin", "display", "decode"))
        commands = {
            "capture": ["clang", "-Wall", "-Wextra", "-O2", "-I/opt/homebrew/include",
                        "-L/opt/homebrew/lib", str(ROOT / "tools/capture_video_uvc.c"), "-luvc", "-o", str(capture)],
            "admin": ["clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit", "-framework", "Security",
                      str(ROOT / "tools/run_capture_video_uvc_admin.m"), "-o", str(admin)],
            "display": ["clang", "-fobjc-arc", "-Wno-deprecated-declarations",
                        *[v for f in FRAMEWORKS for v in ("-framework", f)],
                        str(ROOT / "tools/color_probe_macos.m"), "-o", str(display)],
            "decode": ["clang", "-Wall", "-Wextra", "-O2", "-I/opt/homebrew/include",
                       "-L/opt/homebrew/lib", str(ROOT / "tools/decode_jpeg_ycbcr.c"), "-ljpeg", "-o", str(decoder)],
        }
        for name, command in commands.items():
            subprocess.run(command, check=True)
            compile_commands[name] = {"command": command, "binary_sha256": sha256({"capture": capture, "admin": admin, "display": display, "decode": decoder}[name])}
        log_path = out.parent / (out.name + ".runner.log")
        try:
            result = subprocess.run([str(admin), str(capture), str(display), str(pattern_path), str(out), "qualify"],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            log_path.write_text(partial + "\nNative authorization/acquisition timed out; no success is implied.\n")
            if out.exists():
                (out / "runner.log").write_text(log_path.read_text())
            raise RuntimeError(f"Native acquisition timed out after {args.timeout_seconds}s; log: {log_path}") from error
        log_path.write_text(result.stdout)
        if out.exists():
            (out / "runner.log").write_text(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"Native acquisition failed with status {result.returncode}; log: {log_path}")
        source = Path(str(out) + "-source")
        if not source.is_dir():
            raise RuntimeError("Chart source evidence was not preserved by the capture helper")
        shutil.copytree(source, out / "chart-source")
        shutil.copy2(pattern_path, out / "chart.json")
        input_record = {
            "utc_started": datetime.now(timezone.utc).isoformat(),
            "runner": str(Path(__file__).resolve()),
            "compiled_tools": compile_commands,
            "source_hashes": {str((ROOT / "tools" / name).relative_to(ROOT)): sha256(ROOT / "tools" / name)
                              for name in ("qualify_color_path.py", "analyze_color_capture.py", "capture_video_uvc.c",
                                           "color_probe_macos.m", "run_capture_video_uvc_admin.m", "decode_jpeg_ycbcr.c",
                                           "calibrate_colors.py", "probe_colors.py")},
            "capture_design": {
                "chart": "1920x1080 60x32 patch grid; 7 complete RGB ramps plus mixed colors",
                "pre_chart_claim": "GET_CUR only, claim/release USB, with macOS state snapshots before and after",
                "paired_raw_trials": ["all getters, MJPEG then YUY2", "GET_CUR only, MJPEG then YUY2",
                                      "GET_CUR only + SET_CUR same current controls, MJPEG then YUY2",
                                      "all getters, YUY2 then MJPEG"],
                "avfoundation": ["packed YUV", "BGRA"],
                "control_restoration": "checked per raw session; same-value SET_CUR trial restores and readbacks controls",
            },
        }
        write_json(out / "qualification-inputs.json", input_record)
        subprocess.run(["python3", str(ROOT / "tools/analyze_color_capture.py"), str(out),
                        "--chart-source", str(out / "chart-source"), "--jpeg-decoder", str(decoder)], check=True)
        hashes = {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob("*"))
                  if p.is_file() and p.name != "sha256.json"}
        write_json(out / "sha256.json", hashes)
    print(f"Qualification bundle: {out}")
    print(f"Hash manifest: {out / 'sha256.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be between 60 and 1800")
    run(args)


if __name__ == "__main__":
    main()
