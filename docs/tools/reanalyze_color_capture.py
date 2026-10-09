#!/usr/bin/env python3
"""Replay color analysis on an existing qualification bundle, without USB access."""
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


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_root", type=Path)
    args = parser.parse_args()
    root = args.capture_root.resolve()
    chart_source = root / "chart-source"
    inputs_path = root / "qualification-inputs.json"
    if not root.is_dir() or not chart_source.is_dir() or not inputs_path.is_file():
        parser.error("capture_root must contain chart-source/ and qualification-inputs.json")

    with tempfile.TemporaryDirectory(prefix="ms2109-color-reanalysis-") as temporary:
        decoder = Path(temporary) / "decode-jpeg-ycbcr"
        subprocess.run([
            "clang", "-Wall", "-Wextra", "-O2", "-I/opt/homebrew/include",
            "-L/opt/homebrew/lib", str(ROOT / "tools/decode_jpeg_ycbcr.c"),
            "-ljpeg", "-o", str(decoder),
        ], check=True)
        command = ["python3", str(ROOT / "tools/analyze_color_capture.py"), str(root),
                   "--chart-source", str(chart_source), "--jpeg-decoder", str(decoder)]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, check=True)

    replay_log = root / "analysis-replay.log"
    replay_log.write_text(completed.stdout)
    inputs = json.loads(inputs_path.read_text())
    inputs["post_capture_analysis"] = {
        "utc_completed": datetime.now(timezone.utc).isoformat(),
        "command": command[:-1] + ["<temporary decoder path>"],
        "analyzer_sha256": sha256(ROOT / "tools/analyze_color_capture.py"),
        "decoder_source_sha256": sha256(ROOT / "tools/decode_jpeg_ycbcr.c"),
        "reanalysis_tool_sha256": sha256(Path(__file__).resolve()),
        "log": replay_log.name,
    }
    write_json(inputs_path, inputs)
    hashes = {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "sha256.json"
    }
    write_json(root / "sha256.json", hashes)
    print(completed.stdout, end="")
    print(f"Reanalysis log: {replay_log}")
    print(f"Hash manifest: {root / 'sha256.json'}")


if __name__ == "__main__":
    main()
