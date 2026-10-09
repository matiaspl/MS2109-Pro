"""After a cold power cycle, qualify the installed 1080p MJPEG rate cap."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from ms2109_hid import Device
from build_patch import validate
from qualify_mjpeg_rate_cap_ram import UVC, parse_frame

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/uvc-mode-cap-20261009"
EXPECTED_SHA = "0d8d3139b51edc4ff283dab33f00c2270f2134d95bce4bf7a351dcf38c14bb82"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_hid(timeout: float = 45.0) -> Device:
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            return Device()
        except Exception as exc:
            error = exc
            time.sleep(0.25)
    raise RuntimeError(f"MS2109 HID is unavailable: {error}")


def verify_eeprom(device: Device, candidate: bytes) -> dict:
    if device.identify_eeprom() != 2048:
        raise RuntimeError("Expected a 2 KiB EEPROM")
    e1 = device.read("eeprom", 0, 2048)
    e2 = device.read("eeprom", 0, 2048)
    if e1 != e2 or e1 != candidate:
        raise RuntimeError("EEPROM readback does not match the approved candidate")
    return {"eeprom_sha256_read1": sha(e1), "eeprom_sha256_read2": sha(e2)}


def verify_loaded(device: Device, candidate: bytes, overlay_len: int) -> dict:
    result = verify_eeprom(device, candidate)
    header = device.read("ram", 0xCBD0, 48)
    overlay = device.read("ram", 0xCC00, overlay_len + 4)
    if header != candidate[:48] or overlay != candidate[48:48 + overlay_len + 4]:
        raise RuntimeError("EEPROM candidate is not the overlay currently loaded in RAM")
    result.update({"loaded_header_matches": True, "loaded_overlay_and_checksums_match": True})
    return result


def run(output: Path, candidate_path: Path, capture_bin: Path) -> dict:
    candidate = candidate_path.read_bytes()
    overlay_len = validate(candidate)
    if len(candidate) != 2048 or sha(candidate) != EXPECTED_SHA:
        raise RuntimeError("Installed candidate file does not match the reviewed image")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite report: {output}")
    capture_dir = output.parent / "installed-mjpeg-1080p30-capture"
    if capture_dir.exists():
        raise RuntimeError(f"Refusing to overwrite capture directory: {capture_dir}")

    report = {"scope": "cold-start EEPROM, descriptor and MJPEG capture qualification",
              "candidate_sha256": sha(candidate), "overlay_bytes": overlay_len}
    hid = None
    uvc = None
    try:
        # Confirm the full image and whether a physical cold start loaded it.
        hid = open_hid()
        report["installed_eeprom"] = verify_eeprom(hid, candidate)
        header = hid.read("ram", 0xCBD0, 48)
        overlay = hid.read("ram", 0xCC00, overlay_len + 4)
        report["loaded_header_matches"] = header == candidate[:48]
        report["loaded_overlay_and_checksums_match"] = overlay == candidate[48:48 + overlay_len + 4]
        if not (report["loaded_header_matches"] and report["loaded_overlay_and_checksums_match"]):
            report["loaded_header_hex"] = header.hex()
            report["loaded_overlay_sha256"] = sha(overlay)
            report["status"] = (
                "pending: EEPROM candidate is verified but the old overlay remains in RAM; "
                "a cold power cycle is required"
            )
            return report
        hid.close()
        hid = None

        uvc = UVC()
        desc = uvc.descriptor(2, 1211)
        report["descriptor_type_2"] = parse_frame(desc)
        report["descriptor_processing_unit_bitmap"] = desc[0x41:0x43].hex()
        uvc.close()
        uvc = None

        capture_bin = capture_bin.resolve()
        if not capture_bin.is_file():
            raise RuntimeError(f"Capture helper not found: {capture_bin}")
        proc = subprocess.run([str(capture_bin), "mjpeg", str(capture_dir)],
                              capture_output=True, text=True, timeout=35)
        report["capture_process"] = {"returncode": proc.returncode,
            "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-4000:],
            "output_directory": str(capture_dir)}
        if proc.returncode:
            raise RuntimeError(f"Direct UVC capture failed with status {proc.returncode}")
        metadata = json.loads((capture_dir / "usb-capture.json").read_text())
        frames = metadata.get("frames", [])
        if len(frames) != 8:
            raise RuntimeError(f"Expected 8 captured frames, got {len(frames)}")
        if any((f.get("width"), f.get("height"), f.get("pixel_format"), f.get("jpeg_soi")) !=
               (1920, 1080, "jpeg", True) for f in frames):
            raise RuntimeError("Capture contains an invalid 1080p MJPEG frame")
        if metadata.get("interval_100ns") != 333333:
            raise RuntimeError(f"UVC negotiated unexpected frame interval: {metadata.get('interval_100ns')}")
        times = [f["pts_seconds"] for f in frames]
        elapsed = times[-1] - times[0]
        callback_rate = (len(times) - 1) / elapsed if elapsed > 0 else 0
        report["capture_summary"] = {"frames": len(frames), "frame_interval_100ns": metadata["interval_100ns"],
            "callback_rate_fps": callback_rate,
            "note": "timestamps are host callback arrival times, not device PTS"}
        if not 20 <= callback_rate <= 35:
            raise RuntimeError(f"Captured callback rate {callback_rate:.2f} fps is outside 30 fps tolerance")

        hid = open_hid()
        report["post_capture"] = verify_loaded(hid, candidate, overlay_len)
        hid.close()
        hid = None
        report["status"] = "passed; cold-start overlay, 1080p <=30 fps descriptor, and MJPEG data flow verified"
    except BaseException as exc:
        report["status"] = f"FAILED: {exc}"
        raise
    finally:
        if uvc is not None:
            uvc.close()
        if hid is not None:
            hid.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ART / "ms2109-mjpeg-max-30-stock-controls-v2.bin")
    parser.add_argument("--capture-helper", type=Path, default=Path("/tmp/ms2109-capture-video-uvc"))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.candidate, args.capture_helper), indent=2))
