#!/usr/bin/env python3
"""Trace MS2109 audio SET_INTERFACE and first EP2 re-arm events using RAM hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from ms2109_hid import Device

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "artifacts/ms2109-calibrated-stereo-channel-order.bin"
REFERENCE = ROOT / "artifacts/mac-hdmi-reference.wav"
IMAGE_SHA = "83d13d9f31aee5301937adffbe8ed86c56ea5ec95a9880c4260cb7d25e1d5e82"
ROM_CODE = bytes.fromhex("12d2b8")
VIDEO_CALLBACK = bytes.fromhex("90de05ebf0a3eaf0a3e9f012634522")
VIDEO_CALLER = bytes.fromhex("02cc10")
IRQ_PREFIX = bytes.fromhex("e53330")
SCRATCH = 0xDE30
SCRATCH_SIZE = 0x50
CODE_BASE = 0xD400
IRQ_CODE = 0xD4B0
LOG_CODE = 0xD510
CALLBACK_CODE = 0xD540
CODE_SIZE = 0x150
EVENTS = {
    0x10: "SET_INTERFACE alt 0",
    0x11: "SET_INTERFACE alt 1",
    0x21: "first EP2 re-arm observation before any SET_INTERFACE",
    0x22: "first EP2 re-arm observation after latest SET_INTERFACE",
    0x31: "audio class SET_CUR request",
}


class Assembler:
    def __init__(self, origin: int):
        self.origin = origin
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str, str]] = []

    @property
    def pc(self) -> int:
        return self.origin + len(self.code)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate label {name}")
        self.labels[name] = self.pc

    def emit(self, *values: int) -> None:
        self.code.extend(values)

    def rel(self, opcode: bytes, label: str) -> None:
        self.code.extend(opcode)
        self.fixups.append((self.pc, label, "relative"))
        self.code.append(0)

    def abs(self, opcode: int, label: str) -> None:
        self.code.extend((opcode, 0, 0))
        self.fixups.append((self.pc - 3, label, "absolute"))

    def finish(self) -> bytes:
        for operand_at, label, kind in self.fixups:
            if label not in self.labels:
                raise ValueError(f"undefined label {label}")
            target = self.labels[label]
            if kind == "relative":
                displacement = target - (operand_at + 1)
                if not -128 <= displacement <= 127:
                    raise ValueError(f"relative branch to {label} is out of range: {displacement}")
                self.code[operand_at - self.origin] = displacement & 0xFF
            else:
                offset = operand_at - self.origin
                self.code[offset + 1:offset + 3] = target.to_bytes(2, "big")
        return bytes(self.code)


def build_logger() -> bytes:
    a = Assembler(LOG_CODE)
    a.emit(0xC0, 0xE0, 0xC0, 0xD0, 0xC0, 0x82, 0xC0, 0x83)  # save A, PSW, DPTR
    a.emit(0x90, 0xDE, 0x30, 0xE0)  # count in DE30
    a.rel(bytes((0xB4, 0x40)), "append")
    a.rel(bytes((0x80,)), "full")
    a.label("append")
    # Save the incremented count, then use the prior value as the ring index.
    a.emit(0x04, 0xF0, 0x14, 0x24, 0x40, 0xF5, 0x82, 0x75, 0x83, 0xDE)
    a.emit(0xE5, 0xF0, 0xF0)  # store event code from B in ring DE40..DE7F
    a.label("full")
    a.emit(0xD0, 0x83, 0xD0, 0x82, 0xD0, 0xD0, 0xD0, 0xE0, 0x22)
    result = a.finish()
    if len(result) > CALLBACK_CODE - LOG_CODE:
        raise ValueError("event logger overlaps callback code")
    return result


def build_usb_hook() -> bytes:
    a = Assembler(CODE_BASE)
    # The USB path calls CC10 at ROM 478F, returning to 4792. The video path
    # tail-jumps here and retains its caller's return address. Check that exact
    # return address before treating setup fields as a USB request.
    a.emit(0xC0, 0xE0, 0xC0, 0xD0, 0xE8, 0xC0, 0xE0, 0xA8, 0x81)
    a.emit(0x18, 0x18, 0x18, 0x18, 0xE6)
    a.rel(bytes((0xB4, 0x92)), "caller_mismatch")
    a.emit(0x08, 0xE6)
    a.rel(bytes((0xB4, 0x47)), "caller_mismatch")
    a.emit(0xD0, 0xE0, 0xF8, 0xD0, 0xD0, 0xD0, 0xE0)
    a.rel(bytes((0x80,)), "setup_check")
    a.label("caller_mismatch")
    a.emit(0xD0, 0xE0, 0xF8, 0xD0, 0xD0, 0xD0, 0xE0)
    a.abs(0x02, "video_callback")
    a.label("setup_check")

    # Save the caller context while checking the parsed setup packet.
    a.emit(0xC0, 0xE0, 0xC0, 0xD0, 0xC0, 0xF0, 0xC0, 0x82, 0xC0, 0x83)
    a.emit(0xE5, 0x0B)
    a.rel(bytes((0xB4, 0x01)), "class_req")
    a.emit(0xE5, 0x0C)
    a.rel(bytes((0xB4, 0x0B)), "dispatch")
    for address in (0x0D, 0x0F):
        a.emit(0xE5, address)
        a.rel(bytes((0x70,)), "dispatch")
    a.emit(0xE5, 0x10)
    a.rel(bytes((0xB4, 0x03)), "dispatch")
    for address in (0x11, 0x12):
        a.emit(0xE5, address)
        a.rel(bytes((0x70,)), "dispatch")
    a.emit(0xE5, 0x0E)
    a.rel(bytes((0x60,)), "alt0")
    a.rel(bytes((0xB4, 0x01)), "dispatch")
    a.emit(0x75, 0xF0, 0x11)
    a.abs(0x12, "record_set_interface")
    a.abs(0x02, "dispatch")
    a.label("alt0")
    a.emit(0x75, 0xF0, 0x10)
    a.abs(0x12, "record_set_interface")
    a.abs(0x02, "dispatch")

    a.label("class_req")
    a.emit(0xE5, 0x0B)
    a.rel(bytes((0xB4, 0x21)), "dispatch")
    a.emit(0xE5, 0x0C)
    a.rel(bytes((0xB4, 0x01)), "dispatch")
    a.emit(0x75, 0xF0, 0x31)
    a.abs(0x12, "logger")
    a.abs(0x02, "dispatch")

    a.label("record_set_interface")
    a.abs(0x12, "logger")
    a.emit(0x90, 0xDE, 0x31, 0x74, 0x01, 0xF0, 0xA3, 0xE4, 0xF0)
    # Both callers use LCALL and then branch to dispatch. Return here so the
    # helper's address does not remain on the caller's stack.
    a.emit(0x22)

    a.label("dispatch")
    a.emit(0xD0, 0x83, 0xD0, 0x82, 0xD0, 0xF0, 0xD0, 0xD0, 0xD0, 0xE0)
    a.abs(0x12, "stock_dispatch")
    a.emit(0x22)
    a.label("stock_dispatch")
    a.abs(0x02, "stock_rom")

    a.label("logger")
    a.abs(0x02, "logger_code")
    a.labels["logger_code"] = LOG_CODE
    a.labels["video_callback"] = CALLBACK_CODE
    a.labels["stock_rom"] = 0x2AD0
    result = a.finish()
    if len(result) > IRQ_CODE - CODE_BASE:
        raise ValueError(f"USB wrapper is {len(result)} bytes; overlaps IRQ wrapper")
    return result


def build_irq_hook() -> bytes:
    a = Assembler(IRQ_CODE)
    a.emit(0xC0, 0xE0, 0xC0, 0xD0, 0xC0, 0xF0, 0xC0, 0x82, 0xC0, 0x83)
    a.emit(0xE5, 0x20)
    a.rel(bytes((0x30, 0xE2)), "finish")  # only when ROM's EP2-ready gate is set
    a.emit(0x90, 0xDE, 0x31, 0xE0)
    a.rel(bytes((0x30, 0xE0)), "before_start")
    a.emit(0x90, 0xDE, 0x32, 0xE0)
    a.rel(bytes((0x60,)), "after_start")
    a.rel(bytes((0x80,)), "finish")
    a.label("before_start")
    a.emit(0x90, 0xDE, 0x33, 0xE0)
    a.rel(bytes((0x60,)), "log_before")
    a.rel(bytes((0x80,)), "finish")
    a.label("log_before")
    a.emit(0x75, 0xF0, 0x21)
    a.abs(0x12, "logger")
    a.emit(0x90, 0xDE, 0x33, 0x74, 0x01, 0xF0)
    a.rel(bytes((0x80,)), "finish")
    a.label("after_start")
    a.emit(0x75, 0xF0, 0x22)
    a.abs(0x12, "logger")
    a.emit(0x90, 0xDE, 0x32, 0x74, 0x01, 0xF0)
    a.label("finish")
    a.emit(0xD0, 0x83, 0xD0, 0x82, 0xD0, 0xF0, 0xD0, 0xD0, 0xD0, 0xE0)
    a.emit(0xE5, 0x33)
    a.rel(bytes((0x30, 0xE2)), "skip_original")
    a.abs(0x02, "original_tail")
    a.label("skip_original")
    a.abs(0x02, "original_skip")
    a.labels["original_tail"] = 0xCC25
    a.labels["original_skip"] = 0xCC2D
    a.labels["logger"] = LOG_CODE
    result = a.finish()
    return result


def build_patch() -> tuple[bytes, bytes, bytes, bytes]:
    usb = build_usb_hook()
    irq = build_irq_hook()
    logger = build_logger()
    if CALLBACK_CODE + len(VIDEO_CALLBACK) > CODE_BASE + CODE_SIZE:
        raise ValueError("video callback does not fit saved RAM window")
    buffer = bytearray(b"\x00" * CODE_SIZE)
    buffer[:len(usb)] = usb
    buffer[IRQ_CODE - CODE_BASE:IRQ_CODE - CODE_BASE + len(irq)] = irq
    buffer[LOG_CODE - CODE_BASE:LOG_CODE - CODE_BASE + len(logger)] = logger
    buffer[CALLBACK_CODE - CODE_BASE:CALLBACK_CODE - CODE_BASE + len(VIDEO_CALLBACK)] = VIDEO_CALLBACK
    return bytes(buffer), usb, irq, logger


class LiveTrace:
    def __init__(self, run_id: str, seconds: int, phase: str):
        if hashlib.sha256(IMAGE.read_bytes()).hexdigest() != IMAGE_SHA:
            raise RuntimeError("Local EEPROM image is not the reviewed calibrated image")
        self.run_id = run_id
        self.seconds = seconds
        self.phase = phase
        self.include_irq = phase == "usb-and-irq"
        self.hook_mask = 0x06 if self.include_irq else 0x02
        self.stem = f"audio-usb-hook-trace-{run_id}"
        self.audio = ROOT / f"artifacts/{self.stem}.wav"
        self.metadata = ROOT / f"artifacts/{self.stem}.json"
        self.hook_artifact = ROOT / f"artifacts/{self.stem}-ram.bin"
        if any(path.exists() for path in (self.audio, self.metadata, self.hook_artifact)):
            raise RuntimeError("Refusing to overwrite existing trace outputs")
        if not shutil_which("ffmpeg"):
            raise RuntimeError("ffmpeg is required for the stream-start trace")

        self.device = Device()
        try:
            size = self.device.identify_eeprom()
            eeprom = self.device.read("eeprom", 0, size)
            if hashlib.sha256(eeprom).hexdigest() != IMAGE_SHA:
                raise RuntimeError("Live EEPROM is not the reviewed calibrated image")
            self.flags = self.device.read("ram", 0xCBD4, 1)
            self.cc10 = self.device.read("ram", 0xCC10, len(VIDEO_CALLBACK))
            self.cc20 = self.device.read("ram", 0xCC20, 3)
            self.ram_hook = self.device.read("ram", CODE_BASE, CODE_SIZE)
            self.telemetry = self.device.read("ram", SCRATCH, SCRATCH_SIZE)
            self.entry = self.device.read("ram", 0xCC00, 3)
            self.state = {
                "fe60": self.device.read("ram", 0xFE60, 1)[0],
                "audio_channels": self.device.read("ram", 0xC4C5, 1)[0],
                "sample_rate_descriptor": self.device.read("ram", 0xC4C9, 3).hex(),
            }
            if self.flags != b"\x05" or self.entry != ROM_CODE:
                raise RuntimeError(f"Unexpected live hook state: flags={self.flags.hex()}, entry={self.entry.hex()}")
            if self.cc10 != VIDEO_CALLBACK or self.cc20 != IRQ_PREFIX:
                raise RuntimeError("Live overlay bytes differ from the reviewed image")
            if self.state != {"fe60": 1, "audio_channels": 2, "sample_rate_descriptor": "80bb00"}:
                raise RuntimeError(f"Unexpected audio configuration: {self.state}")
            self.patch, self.usb, self.irq, self.logger = build_patch()
            self.install_started = False
        except BaseException:
            self.device.close()
            raise

    def write(self, addr: int, data: bytes) -> None:
        for offset, value in enumerate(data):
            last_error = None
            for attempt in range(3):
                try:
                    self.device.exchange(0xB6, addr + offset, value)
                    last_error = None
                    break
                except RuntimeError as error:
                    last_error = error
                    if attempt < 2:
                        time.sleep(0.2)
            if last_error is not None:
                raise last_error

    def read(self, addr: int, length: int) -> bytes:
        return self.device.read("ram", addr, length)

    def install(self) -> None:
        # Disable only optional CC10/CC20 hooks while code and state are staged.
        self.install_started = True
        self.write(0xCBD4, bytes((self.flags[0] & ~self.hook_mask,)))
        self.write(CODE_BASE, self.patch)
        self.write(SCRATCH, bytes(SCRATCH_SIZE))
        if self.read(CODE_BASE, len(self.patch)) != self.patch:
            raise RuntimeError("RAM hook body readback mismatch")
        self.write(0xCC10, bytes.fromhex(f"02 {CODE_BASE >> 8:02x} {CODE_BASE & 255:02x}"))
        if self.read(0xCC10, 3) != bytes.fromhex("02 d4 00"):
            raise RuntimeError("USB hook vector readback mismatch")
        if self.include_irq:
            self.write(0xCC20, bytes.fromhex(f"02 {IRQ_CODE >> 8:02x} {IRQ_CODE & 255:02x}"))
            if self.read(0xCC20, 3) != bytes.fromhex(f"02 {IRQ_CODE >> 8:02x} {IRQ_CODE & 255:02x}"):
                raise RuntimeError("IRQ hook vector readback mismatch")
        self.write(0xCBD4, bytes((self.flags[0] | 0x02,)))
        if self.read(0xCBD4, 1) != bytes((self.flags[0] | 0x02,)):
            raise RuntimeError("USB hook flag did not enable")
        self.installed = True

    def restore(self) -> None:
        if not self.install_started:
            self.device.close()
            return
        try:
            # Keep both experimental dispatch paths disabled until all original
            # code, callback data, scratch bytes, and vectors have been restored.
            self.write(0xCBD4, bytes((self.flags[0] & ~self.hook_mask,)))
            self.write(0xCC10, self.cc10)
            if self.include_irq:
                self.write(0xCC20, self.cc20)
            self.write(CODE_BASE, self.ram_hook)
            self.write(SCRATCH, self.telemetry)
            checks = (self.read(0xCC10, len(self.cc10)) == self.cc10,
                      self.read(0xCC20, len(self.cc20)) == self.cc20,
                      self.read(CODE_BASE, len(self.ram_hook)) == self.ram_hook,
                      self.read(SCRATCH, len(self.telemetry)) == self.telemetry)
            if not all(checks):
                raise RuntimeError("RAM restore readback did not match saved bytes")
            self.write(0xCBD4, self.flags)
            if self.read(0xCBD4, 1) != self.flags:
                raise RuntimeError("Original hook flags did not restore")
            self.install_started = False
        except BaseException as error:
            self.device.close()
            raise RuntimeError(
                "RAM restore could not be verified; unplug/reconnect to clear volatile hooks and reload EEPROM"
            ) from error
        self.device.close()

    def capture(self, play_reference: bool = False) -> dict:
        command = ["ffmpeg", "-n", "-hide_banner", "-f", "avfoundation",
                   "-i", ":usb video", "-t", str(self.seconds), "-vn",
                   "-c:a", "pcm_s16le", str(self.audio)]
        audio_route = None
        playback_command = None
        if play_reference:
            if not REFERENCE.is_file() or not shutil_which("afplay"):
                raise RuntimeError("Reference WAV and afplay are required")
            from qualify_stereo_audio import default_hdmi_output
            audio_route = default_hdmi_output()
            playback_command = ["afplay", str(REFERENCE)]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True)
        playback = None
        playback_log = ""
        try:
            time.sleep(0.4)
            if playback_command:
                playback = subprocess.Popen(playback_command, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, text=True)
            _, log = process.communicate(timeout=self.seconds + 20)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            _, log = process.communicate()
            raise RuntimeError(f"AVFoundation capture timed out: {log[-3000:]}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if playback is not None:
                if playback.poll() is None:
                    playback.terminate()
                    try:
                        playback.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        playback.kill()
                        playback.wait(timeout=5)
                _, playback_log = playback.communicate()
        if process.returncode:
            raise RuntimeError(f"AVFoundation capture failed: {log[-3000:]}")
        events = self.read(SCRATCH + 0x10, 64)
        count = self.read(SCRATCH, 1)[0]
        result = {
            "capture_command": command,
            "capture_returncode": process.returncode,
            "capture_log_tail": log[-2000:],
            "capture_sha256": hashlib.sha256(self.audio.read_bytes()).hexdigest(),
            "capture_bytes": self.audio.stat().st_size,
            "event_count": count,
            "events": [
                {"index": index, "code": f"0x{code:02x}", "event": EVENTS.get(code, "unknown")}
                for index, code in enumerate(events[:count])
            ],
        }
        if play_reference:
            result["reference_playback"] = {
                "wav": str(REFERENCE.relative_to(ROOT)),
                "sha256": hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                "command": playback_command,
                "hdmi_output": audio_route,
                "playback_log_tail": playback_log[-1000:],
                "playback_returncode_after_capture_stop": playback.returncode,
            }
        return result


def shutil_which(command: str) -> str | None:
    from shutil import which
    return which(command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="assemble and validate offline only")
    parser.add_argument("--experiment", action="store_true", help="install guarded RAM hooks and capture the USB audio stream")
    parser.add_argument("--run-id", required=False, help="unique artifact suffix, letters/digits/_/- only")
    parser.add_argument("--phase", choices=("usb-only", "usb-and-irq"), default="usb-only",
                        help="incremental validation; leave CC20 unchanged unless explicitly selecting usb-and-irq")
    parser.add_argument("--seconds", type=int, default=6)
    parser.add_argument("--play-reference", action="store_true",
                        help="play the stereo HDMI fixture to the verified default HDMI output during capture")
    args = parser.parse_args()
    patch, usb, irq, logger = build_patch()
    if args.audit:
        print(json.dumps({"scope": "offline assembler only", "ram_window_bytes": len(patch),
                          "usb_wrapper_bytes": len(usb), "irq_wrapper_bytes": len(irq),
                          "logger_bytes": len(logger), "callback_bytes": len(VIDEO_CALLBACK),
                          "callback_preserved": True, "stock_usb_dispatch": "0x2AD0",
                          "hook_vectors": {"CC10": "02d400", "CC20": f"02{IRQ_CODE >> 8:02x}{IRQ_CODE & 255:02x}"}}, indent=2))
        return 0
    if not args.experiment:
        parser.error("pass --audit for offline validation or --experiment for RAM-only hardware testing")
    if not args.run_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.run_id):
        parser.error("--run-id is required and may contain letters, digits, '_' and '-' (max 32 chars)")
    if not 3 <= args.seconds <= 12:
        parser.error("--seconds must be between 3 and 12")
    trace = LiveTrace(args.run_id, args.seconds, args.phase)
    trace.hook_artifact.write_bytes(trace.patch)
    capture_result = None
    try:
        trace.install()
        capture_result = trace.capture(play_reference=args.play_reference)
    finally:
        trace.restore()
    output = {
        "scope": "temporary RAM hooks; EEPROM untouched",
        "run_id": args.run_id,
        "phase": args.phase,
        "eeprom_sha256": IMAGE_SHA,
        "audio_state_before": trace.state,
        "initial_hook_flags": trace.flags.hex(),
        "hook_sha256": hashlib.sha256(trace.patch).hexdigest(),
        "capture": capture_result,
        "ram_hooks_restored": True,
        "interpretation_limit": "EP2 re-arm is a ROM service event, not direct observation of the first USB packet or sample alignment",
    }
    trace.metadata.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if capture_result["event_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
