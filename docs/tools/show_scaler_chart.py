#!/usr/bin/env python3
"""Present the scaler target as a 1:1 full-screen image on HDMI TO USB."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DEFAULT_IMAGE = ROOT / "artifacts/scaler-f9a0/test-chart-1920x1080.png"
DEFAULT_MANIFEST = ROOT / "artifacts/scaler-f9a0/test-chart-1920x1080.json"
FRAMEWORKS = (
    "Cocoa", "AVFoundation", "CoreMedia", "CoreVideo", "CoreGraphics",
    "ImageIO", "UniformTypeIdentifiers", "ScreenCaptureKit",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path,
                        help="new directory for display-ready metadata and a rendered source reference")
    parser.add_argument("--seconds", type=int, default=3600,
                        help="keep the chart on screen for this many seconds (default: 3600)")
    parser.add_argument("--render-space", choices=("native", "srgb"), default="native")
    args = parser.parse_args()

    image = args.image.resolve()
    manifest = args.manifest.resolve()
    if not image.is_file() or not manifest.is_file():
        parser.error(f"chart image and manifest must exist: {image} / {manifest}")
    with Image.open(image) as chart:
        raster_size = list(chart.size)
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    output = args.output.resolve() if args.output else ROOT / "artifacts/scaler-f9a0" / (
        "chart-session-" + datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    )
    if output.exists():
        parser.error(f"refusing to overwrite {output}")

    with tempfile.TemporaryDirectory(prefix="ms2109-scaler-chart-") as temp:
        binary = Path(temp) / "color_probe_macos"
        command = ["clang", "-fobjc-arc", "-Wno-deprecated-declarations"]
        for framework in FRAMEWORKS:
            command.extend(("-framework", framework))
        command.extend((str(TOOLS / "color_probe_macos.m"), "-o", str(binary)))
        subprocess.run(command, check=True)
        run = [str(binary), "--manifest", str(manifest), "--output", str(output),
               "--transport", "display", "--full-frame-image", str(image),
               "--render-space", args.render_space, "--seconds", str(args.seconds)]
        print(f"Launching the {raster_size[0]}x{raster_size[1]} scaler chart on HDMI TO USB.", flush=True)
        print(f"Session record: {output / 'display-ready.json'}", flush=True)
        print("Press Ctrl-C in this terminal to close the chart early.", flush=True)
        process = subprocess.Popen(run)
        ready_path = output / "display-ready.json"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None and not ready_path.is_file():
            time.sleep(0.1)
        if not ready_path.is_file():
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError("Presenter did not confirm the target display; chart was stopped")
        state = json.loads(ready_path.read_text())
        if (not state.get("target_display_available") or
                not state.get("display_profile_matches") or
                state.get("window_screen") != "HDMI TO USB" or
                state.get("chart_kind") != "full-frame-raster" or
                state.get("full_frame_image_size") != raster_size):
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError(f"Presenter readiness checks failed: {state}")
        print(f"Scaler chart is full-screen on HDMI TO USB at {raster_size[0]}x{raster_size[1]}.", flush=True)
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
