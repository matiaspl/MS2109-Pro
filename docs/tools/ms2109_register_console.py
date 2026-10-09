#!/usr/bin/env python3
"""Interactive volatile XDATA register viewer/editor for an MS2109.

Words are displayed little-endian. Every first edit is journaled to disk before
the HID write. Leaving the UI restores changed byte values; --recover restores
a journal left by an interrupted process. Some XDATA addresses are command or
data ports whose side effects cannot be undone by restoring the prior value.
The EEPROM is only read and hashed.
"""
from __future__ import annotations

import argparse
import curses
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import textwrap
from typing import NamedTuple

from ms2109_hid import Device

DEFAULT_SESSION_DIR = Path(tempfile.gettempdir()) / "ms2109-register-sessions"


class RegisterPurpose(NamedTuple):
    address: int
    width: int
    span: int
    name: str
    purpose: str
    confidence: str


# A curated map from docs/ms2109-reference/registers.md and linked reports.
# Helper literals without decoded silicon names remain explicitly unresolved.
REGISTER_PURPOSES = (
    RegisterPurpose(0xF800, 1, 3, "Silicon ID", "First byte of the three-byte target identity; expected bytes are A7 10 9A.", "Observed identity check; bytes are not independently decoded revision fields."),
    RegisterPurpose(0xE33C, 1, 4, "Overlay setup block", "The installed command-0B path writes F5 0F 00 00 to E33C–E33F. This is a four-byte setup payload; its silicon meaning is unresolved.", "Exact installed-overlay writes verified; hardware function unknown."),
    RegisterPurpose(0xEFD0, 1, 4, "Overlay reset block", "The installed command-0F path clears EFD0–EFD3. Do not treat this as ordinary RAM.", "Exact installed-overlay writes verified; hardware function unknown."),
    RegisterPurpose(0xEFE0, 1, 1, "Overlay status input", "The installed overlay tests bit 6. When set, it writes a response block at EFE8–EFEB and updates C776–C777.", "Exact branch and response writes verified; status meaning unknown."),
    RegisterPurpose(0xEFE8, 1, 4, "Overlay response block", "Written as 40 00 00 00 when EFE0 bit 6 is set. The response role is clear from code; the peripheral protocol is not.", "Exact installed-overlay writes verified; hardware function unknown."),
    RegisterPurpose(0xF000, 1, 1, "Core command latch", "ROM writes 07 then 02 during startup and later sets or clears bit 1. This is active command/control state, not a passive tuning byte.", "Decoded read-modify-write paths verified; silicon meaning unknown."),
    RegisterPurpose(0xF002, 1, 1, "Startup control byte", "ROM writes this byte in the reset/setup path; no stable silicon label is established.", "Decoded write path verified; hardware function unknown."),
    RegisterPurpose(0xF003, 1, 1, "Startup control byte", "ROM writes this byte in the reset/setup path; no stable silicon label is established.", "Decoded write path verified; hardware function unknown."),
    RegisterPurpose(0xF005, 1, 1, "Interrupt service clear", "A ROM interrupt path writes zero here when its overlay hook is disabled.", "Decoded handler branch verified; silicon meaning unknown."),
    RegisterPurpose(0xF006, 1, 1, "Interrupt service clear", "A ROM interrupt path writes zero here when its overlay hook is disabled.", "Decoded handler branch verified; silicon meaning unknown."),
    RegisterPurpose(0xF0EE, 1, 2, "Startup parameter pair", "ROM writes 04 to F0EE and B8 to F0EF during startup. No read path or silicon field names were found.", "Decoded constants verified; hardware meaning unknown."),
    RegisterPurpose(0xF1F0, 1, 1, "Procamp apply gate", "A nonzero value returns from the ROM procamp apply routine before it copies the UVC shadows to FE90–FE93. Live value in this snapshot: 05.", "Exact ROM branch and live read verified; gate polarity is established, silicon purpose is not."),
    RegisterPurpose(0xF1F3, 1, 2, "Signal-path state pair", "ROM writes F1F3–F1F4 in video/signal state paths. The byte order and downstream hardware effect are not decoded.", "Decoded write sites verified; hardware meaning unknown."),
    RegisterPurpose(0xF1F8, 1, 1, "UAC Feature Unit mute value", "Bit 0 backs AudioControl Feature Unit 2 selector 1. A live standard SET_CUR changed 00 to 01; GET_CUR and raw readback agreed, then the original 00 was restored.", "Live standard request and XDATA readback verified; exact silicon implementation and audible effect remain inferred."),
    RegisterPurpose(0xF1F9, 1, 1, "Signal handshake byte", "ROM pulses this byte through 01 then 00 in the USB signal-state path.", "Decoded write sequence verified; hardware meaning unknown."),
    RegisterPurpose(0xF1FA, 1, 1, "Interrupt signal state", "The ROM checks this byte and, on a nonzero result, writes 01 and sets an internal state flag.", "Decoded handler behavior verified; status source unknown."),
    RegisterPurpose(0xF1FB, 1, 1, "Interrupt signal state", "The ROM reads this byte and compares it with 03 in its USB interrupt state machine.", "Decoded comparison verified; status meaning unknown."),
    RegisterPurpose(0xF1FC, 1, 1, "Interrupt signal state", "Read and written by the USB/video state machine; ROM writes 01 during one transition.", "Decoded read/write paths verified; state encoding unknown."),
    RegisterPurpose(0xF1FF, 1, 1, "Interrupt command/status", "ROM writes 04, sets bit 1, later writes 07, and uses this byte in interrupt handling.", "Decoded write and bit operations verified; silicon meaning unknown."),
    RegisterPurpose(0xF500, 1, 4, "Setup command block", "ROM writes 00 00 00 01 to F500–F503, then uses nearby F5xx addresses for a setup stream. The port protocol is not decoded.", "Decoded write sequence verified; hardware meaning unknown."),
    RegisterPurpose(0xF504, 1, 3, "Setup parameter block", "ROM writes three values to F504–F506 from a code table as part of the F5xx setup sequence.", "Decoded sequence verified; table fields and hardware meaning unknown."),
    RegisterPurpose(0xF50A, 1, 3, "Setup parameter bytes", "ROM writes code-table bytes to F50A–F50C through DPTR-preserving helper calls.", "Decoded caller/helper flow verified; hardware meaning unknown."),
    RegisterPurpose(0xF50D, 1, 13, "Setup data stream", "ROM writes a multi-byte sequence across F50D–F519, including table values and fixed command bytes. Avoid arbitrary edits while streaming.", "Decoded writes and helper calls verified; hardware meaning unknown."),
    RegisterPurpose(0xF520, 1, 1, "Setup command port", "ROM writes 02, 00, then 01 to this same address and later writes it again during setup.", "Decoded writes verified; command semantics unknown."),
    RegisterPurpose(0xF521, 1, 4, "Setup data block", "ROM writes four bytes across F521–F524 from values prepared by the setup routine.", "Decoded writes verified; hardware meaning unknown."),
    RegisterPurpose(0xF526, 1, 1, "Setup table selector", "ROM writes zero, then streams 128 code-table bytes to F527.", "Decoded loop verified; exact peripheral protocol unknown."),
    RegisterPurpose(0xF527, 1, 1, "Setup table data port", "Receives 128 bytes from a ROM table after F526 is cleared. It is a streaming port, not ordinary storage.", "Decoded 128-byte loop verified; table purpose unknown."),
    RegisterPurpose(0xFE20, 1, 1, "Command latch", "ROM writes 2B in the sequence called at 23EB; the installed EEPROM command-01 handler writes 2A before its setup helper. This is an active command path, not a passive configuration byte.", "Exact writes and call paths verified; silicon function unresolved."),
    RegisterPurpose(0xFE22, 1, 1, "Status input", "ROM reads this after writing FE20=2B and branches on zero versus nonzero.", "Exact read/branch behavior verified; status meaning unresolved."),
    RegisterPurpose(0xFE28, 1, 1, "Response output", "ROM writes 00 when FE22 is zero, otherwise writes 01.", "Exact response behavior verified; peripheral side effect unresolved."),
    RegisterPurpose(0xFE90, 1, 1, "Brightness hardware byte", "Signed 8-bit brightness value written by the stock procamp path.", "Verified ROM write target and live UVC SET/GET."),
    RegisterPurpose(0xFE91, 1, 1, "Contrast hardware byte", "Nonnegative contrast byte written by the stock procamp path.", "Verified ROM write target and live UVC SET/GET."),
    RegisterPurpose(0xFE92, 1, 1, "Saturation hardware byte", "Nonnegative saturation byte written by the stock procamp path.", "Verified ROM write target and live UVC SET/GET."),
    RegisterPurpose(0xFE93, 1, 1, "Hue hardware byte", "Signed hue byte written by the stock procamp path.", "Verified ROM write target and live UVC SET/GET."),
    RegisterPurpose(0xFE60, 1, 1, "Audio channel-routing control", "Value 01 produced corrected left/right routing in the qualified patch; the full bitfield is unknown.", "Observed audio result; sample alignment is not established."),
    RegisterPurpose(0xFE61, 1, 1, "Audio rate/path control", "ROM sets bit 3 for equal rates; unequal rates use set bit 0 then clear bit 3.", "Exact operations verified; physical bit meanings remain inferred."),
    RegisterPurpose(0xFE62, 1, 3, "Input-rate value", "Start of a 24-bit little-endian input-rate value spanning FE62–FE64.", "ROM rate path verified offline; hardware timing meaning is not fully mapped."),
    RegisterPurpose(0xFE65, 1, 3, "Output-rate value", "Start of a 24-bit little-endian output-rate value spanning FE65–FE67.", "ROM rate path verified offline; hardware timing meaning is not fully mapped."),
    RegisterPurpose(0xF809, 1, 1, "Rate setup control", "ROM sets bit 7 before writing FE62–FE67 and leaves it set.", "Software operation verified; hardware function unresolved."),
    RegisterPurpose(0xF803, 1, 1, "Mode setup mask field", "ROM performs read-modify-write operations here in rate/video initialization. It is not an input-dimension field.", "Decoded masks verified; silicon bit meanings unknown."),
    RegisterPurpose(0xF804, 1, 1, "Mode setup mask field", "ROM repeatedly reads this byte, changes selected bits, and writes it back during mode setup.", "Decoded masks verified; silicon bit meanings unknown."),
    RegisterPurpose(0xF806, 1, 1, "Mode setup field", "ROM and the installed overlay write mode-dependent values here.", "Decoded writes verified; hardware encoding unknown."),
    RegisterPurpose(0xF807, 1, 1, "Mode selector value", "ROM reads and writes this byte in mode setup; the installed overlay writes values selected from the active mode path.", "Decoded paths verified; exact mode encoding unknown."),
    RegisterPurpose(0xF80B, 1, 1, "Mode setup control", "ROM reads and updates bit 6, writes paired values to F80D–F80E, and changes this byte across setup branches.", "Decoded masks and writes verified; silicon meaning unknown."),
    RegisterPurpose(0xF815, 1, 2, "Mode parameter pair", "ROM writes a two-byte value to F815–F816 using parameters loaded by the mode path.", "Decoded writes verified; parameter encoding unknown."),
    RegisterPurpose(0xF817, 1, 1, "Mode parameter", "ROM writes values here in the same mode-selection path that writes F807 and F840.", "Decoded writes verified; parameter meaning unknown."),
    RegisterPurpose(0xF83A, 1, 2, "Video state pair", "ROM writes F83A during state transitions and sets bit 0 of F83B during initialization.", "Decoded write/update paths verified; hardware state meaning unknown."),
    RegisterPurpose(0xF83F, 1, 1, "Mode-derived value", "ROM computes a value from RAM-backed mode state and writes it here.", "Decoded data flow verified; hardware meaning unknown."),
    RegisterPurpose(0xF840, 1, 1, "Mode parameter", "ROM writes values here alongside F807 and F817 during mode selection.", "Decoded writes verified; parameter meaning unknown."),
    RegisterPurpose(0xF8E4, 1, 2, "Read-only mode parameters", "ROM reads F8E4–F8E5 and F8EC–F8ED in setup paths and copies the bytes into RAM state.", "Decoded read/copy flow verified; parameter encoding unknown."),
    RegisterPurpose(0xF8EC, 1, 2, "Read-only mode parameters", "ROM reads F8EC–F8ED in setup paths and copies the bytes into RAM state.", "Decoded read/copy flow verified; parameter encoding unknown."),
    RegisterPurpose(0xF921, 1, 2, "Sparse mode control fields", "ROM changes selected bits in F921–F922 during mode initialization; the stored values are not decoded as dimensions.", "Decoded masked updates verified; hardware meanings unknown."),
    RegisterPurpose(0xF92C, 1, 1, "Overlay mode command", "The installed command-0B path writes 20 here before programming E33C–E33F.", "Exact installed-overlay sequence verified; silicon meaning unknown."),
    RegisterPurpose(0xF944, 1, 1, "Mode-path status selector", "ROM tests bit 2 to choose between two setup paths using the F927/F928 and F948/F949 helper sequences.", "Decoded branch verified; status meaning unknown."),
    RegisterPurpose(0xF9AF, 1, 1, "Overlay mode command", "The installed command-0A path writes 22 and then 02 here; another branch writes 22 once.", "Exact installed-overlay sequence verified; silicon meaning unknown."),
    RegisterPurpose(0xFDBF, 1, 1, "Interrupt read input", "A ROM interrupt branch loads this byte through DPTR; the returned value is not used by the following visible instructions.", "Instruction path verified; read side effect and hardware meaning unknown."),
    RegisterPurpose(0xFE80, 1, 1, "Video mode / horizontal detail flag", "ROM mode setup updates bit 0. A live 1→0 probe lowered horizontal line-pair contrast at native 1080p and 1080p→720p capture, without moving the corner markers. The effect resembles FE84=40, but the silicon function is not decoded.", "ROM bit path and repeatable live image response verified; internal role unresolved."),
    RegisterPurpose(0xFE81, 1, 1, "Unresolved video byte FE81", "ROM audit found no direct access. Bit 0 was tested during live native and downscaled chart capture; its small response was close to capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE82, 1, 1, "Unresolved video byte FE82", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE83, 1, 1, "Unresolved video byte FE83", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE84, 1, 1, "Horizontal detail / resampling parameter", "ROM mode setup writes 7A. Live 7A→40 chart probes reduced X-varying line-pair contrast while flat fields and corner geometry stayed stable. FE84 is not identified as width/height or a sharpness gain; exact coefficient semantics remain unknown.", "ROM write path and repeatable live horizontal-frequency response verified; exact meaning unresolved."),
    RegisterPurpose(0xFE85, 1, 1, "Horizontal phase / resampling candidate", "ROM clears bit 1. Live 00→02 changes high-frequency pattern response; the tested native and 1080p→720p corner markers retained their fitted scale and position. This is not an input width/height mapping.", "ROM bit path and live pattern response verified; exact arithmetic unresolved."),
    RegisterPurpose(0xFE86, 1, 1, "Unresolved video byte FE86", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE87, 1, 1, "Unresolved video byte FE87", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE88, 1, 1, "Unresolved video byte FE88", "ROM audit found no direct access. With live baseline 11, bit 0 was toggled to 10 during native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE89, 1, 1, "Unresolved video byte FE89", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE8A, 1, 1, "Unresolved video byte FE8A", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE8B, 1, 1, "Unresolved video byte FE8B", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE8C, 1, 1, "Unresolved video byte FE8C", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE8D, 1, 1, "Unresolved video byte FE8D", "ROM audit found no direct access. Bit 0 was toggled during live native and downscaled chart capture without a clear response above capture variation. Other bits were not tested.", "One-bit RAM probe; purpose unresolved."),
    RegisterPurpose(0xFE8E, 1, 1, "Video luma-transfer flags", "ROM updates bits 0 and 4 alongside FE8F. Live bit 0 added about 18 Y codes to dark/mid/high flat fields at native mode and 12 codes at 720p; bit 4 reduced output levels and contrast. Field encoding is unresolved.", "ROM paired-bit update and strong live luma response verified; silicon labels unresolved."),
    RegisterPurpose(0xFE8F, 1, 1, "Video luma / mode flags", "ROM updates bits 0 and 4 alongside FE8E. Live bit 0 changed flat-field levels at 720p but showed no clear native-1080p response; bit 4 had no clear effect in tested modes.", "ROM paired-bit update and mode-dependent live response verified; field encoding unresolved."),
    RegisterPurpose(0xFE8E, 1, 1, "Video-mode flag pair", "Mode setup read-modify-writes bits 0 and 4 from the inverse of IRAM bit 20.0; the reviewed callers set 20.0 first, so they clear both bits.", "Exact software bit behavior verified; silicon function unresolved."),
    RegisterPurpose(0xFE8F, 1, 1, "Video-mode flag pair", "Mode setup read-modify-writes bits 0 and 4 from the inverse of IRAM bit 20.0; the reviewed callers set 20.0 first, so they clear both bits.", "Exact software bit behavior verified; silicon function unresolved."),
    RegisterPurpose(0xFEB9, 1, 1, "Video-mode flag candidate", "Mode setup read-modify-writes bit 0 from IRAM bit 20.4; one path copies IRAM bit 20.3 into 20.4 first.", "Exact software bit behavior verified; silicon function unresolved."),
    RegisterPurpose(0xFEBA, 1, 1, "No-signal pattern selector", "ROM read-modify-writes bits 4:0 from the current R7/IRAM 07 value and preserves bits 7:5. Prior live sweeps identified the low field as the no-signal pattern selector.", "Exact write mask verified; pattern role confirmed by prior live sweep; field details are in the linked report."),
    RegisterPurpose(0xF9A0, 1, 1, "Scaler-enable candidate", "ROM uses bit 0 in video-mode paths; tested writes did not establish a bypass effect.", "Static ROM and cross-family evidence; live effect unresolved."),
    RegisterPurpose(0xF819, 1, 1, "EDID upload/access candidate", "ROM sets bit 0 before copying 256 bytes to FB00–FBFF, then clears it.", "Software sequence verified; electrical behavior and vendor bit name are inferred."),
    RegisterPurpose(0xC4C5, 1, 1, "Audio channel-count descriptor", "USB audio descriptor byte; value 02 declares two channels.", "Saved descriptor layout and enumeration verified."),
    RegisterPurpose(0xC4C9, 1, 3, "Audio sample-rate descriptor", "Start of a 24-bit little-endian USB rate declaration; 80 BB 00 means 48 kHz.", "Saved descriptor layout and enumeration verified."),
    RegisterPurpose(0xC6A0, 2, 2, "Brightness UVC shadow", "Signed 16-bit little-endian current value at C6A0–C6A1.", "ROM procamp path and live UVC SET/GET verified."),
    RegisterPurpose(0xC6A2, 2, 2, "Contrast UVC shadow", "Nonnegative 16-bit little-endian current value at C6A2–C6A3.", "ROM procamp path and live UVC SET/GET verified."),
    RegisterPurpose(0xC6A4, 2, 2, "Hue UVC shadow", "Signed 16-bit little-endian current value at C6A4–C6A5.", "ROM procamp path and live UVC SET/GET verified."),
    RegisterPurpose(0xC6A6, 2, 2, "Saturation UVC shadow", "Nonnegative 16-bit little-endian current value at C6A6–C6A7.", "ROM procamp path and live UVC SET/GET verified."),
)

# These addresses were resolved as literal arguments to shared ROM XDATA
# helpers. Their callsites establish that firmware accesses them, but the
# available code does not give most of them unique silicon field names.
_HELPER_LITERAL_ADDRESSES = (
    0xF803, 0xF804, 0xF805, 0xF808, 0xF809, 0xF80A, 0xF819, 0xF831,
    0xF83C, 0xF83D,
    0xF921, 0xF922, 0xF923, 0xF926, 0xF929, 0xF92B, 0xF92C, 0xF92E,
    0xF933, 0xF936, 0xF944, 0xF947, 0xF94A,
    0xF960, 0xF962, 0xF963, 0xF966, 0xF969, 0xF980, 0xF983, 0xF986,
    0xF987, 0xF9A0, 0xF9A1, 0xF9A2, 0xF9AF, 0xF9C0, 0xF9C1, 0xF9C2,
    0xF9C3, 0xF9C5, 0xF9CD, 0xF9E4, 0xF9E5, 0xF9F5,
    0xFA00, 0xFA07, 0xFA08, 0xFA09, 0xFA0A, 0xFA10, 0xFA13, 0xFA14,
    0xFA80, 0xFA83, 0xFA85, 0xFA8C, 0xFA8F, 0xFA90, 0xFA9C, 0xFAA0,
    0xFAA1, 0xFAA2, 0xFAA3, 0xFAA4, 0xFAA5, 0xFAA9, 0xFAAA, 0xFAAD,
    0xFAAE, 0xFAB1, 0xFAB2, 0xFAB9, 0xFAC1, 0xFAC2, 0xFAC3, 0xFAC4,
    0xFAC5, 0xFAC6, 0xFAC7, 0xFAC9, 0xFACA,
    0xFD00, 0xFD01, 0xFD3A, 0xFD3F,
    0xFF00, 0xFF01, 0xFF08, 0xFF09, 0xFF0A, 0xFF11, 0xFF12, 0xFF16,
    0xFF17, 0xFF18, 0xFF19, 0xFF1A, 0xFF1B, 0xFF35, 0xFF47, 0xFF48,
    0xFF90, 0xFF91, 0xFFA0, 0xFFA1, 0xFFA3, 0xFFA5, 0xFFA6, 0xFFA7,
    0xFFA8, 0xFFAB, 0xFFAF, 0xFFB0, 0xFFBC,
)
_MAPPED_BYTES = {address for item in REGISTER_PURPOSES
                 for address in range(item.address, item.address + item.span)}
REGISTER_PURPOSES += tuple(
    RegisterPurpose(
        address, 1, 1, f"Sparse {address >> 8:02X}xx helper field",
        "This literal address reaches one or more shared ROM XDATA helpers in mode, setup, or interrupt paths. The access is real, but the field encoding and silicon purpose remain unresolved; see the non-FE audit report.",
        "Instruction-aligned helper callsites decoded; exact per-mode hardware meaning is not established. Treat as a live register/port, not ordinary storage.",
    )
    for address in _HELPER_LITERAL_ADDRESSES if address not in _MAPPED_BYTES
)


def purpose_for_address(address: int) -> RegisterPurpose | None:
    return next((item for item in REGISTER_PURPOSES
                 if item.address <= address < item.address + item.span), None)


def stable_eeprom_hash(device: Device) -> str:
    size = device.identify_eeprom()
    first = device.read("eeprom", 0, size)
    second = device.read("eeprom", 0, size)
    if first != second:
        raise RuntimeError("Two EEPROM reads disagree; refusing register session")
    return hashlib.sha256(first).hexdigest()


def validate_access(address: int, width: int) -> None:
    if width not in (1, 2):
        raise ValueError("Width must be one byte or one word")
    if not 0 <= address <= 0xFFFF or address + width > 0x10000:
        raise ValueError("Address range is outside XDATA")


class RegisterSession:
    def __init__(self, device: Device, eeprom_sha256: str, journal_path: Path):
        self.device = device
        self.eeprom_sha256 = eeprom_sha256
        self.journal_path = journal_path
        self.original: dict[int, int] = {}
        self.latest: dict[int, int] = {}
        self.state = "clean"

    def read(self, address: int, width: int = 1) -> bytes:
        validate_access(address, width)
        return self.device.read("ram", address, width)

    def read_value(self, address: int, width: int = 1) -> int:
        return int.from_bytes(self.read(address, width), "little")

    def write(self, address: int, data: bytes) -> bytes:
        width = len(data)
        validate_access(address, width)
        if width not in (1, 2):
            raise ValueError("Only byte and word writes are supported")
        before = self.read(address, width)
        for offset, value in enumerate(before):
            self.original.setdefault(address + offset, value)
        self.state = "active"
        self._save_journal()  # Write-ahead recovery record precedes hardware mutation.
        for offset, value in enumerate(data):
            self.device.exchange(0xB6, address + offset, value)
        actual = self.read(address, width)
        for offset, value in enumerate(actual):
            self.latest[address + offset] = value
        if actual != data:
            self._save_journal()
            raise RuntimeError(f"XDATA readback mismatch at {address:04X}: {actual.hex()}")
        self._save_journal()
        return actual

    def toggle_bit(self, address: int, width: int, bit: int) -> bytes:
        validate_access(address, width)
        if not 0 <= bit < width * 8:
            raise ValueError(f"Bit must be between 0 and {width * 8 - 1}")
        current = self.read_value(address, width)
        updated = current ^ (1 << bit)
        return self.write(address, updated.to_bytes(width, "little"))

    def restore_addresses(self, addresses: set[int]) -> None:
        pending = {address: self.original[address] for address in addresses
                   if address in self.original}
        if not pending:
            return
        self.state = "restoring"
        self._save_journal()
        for address, value in sorted(pending.items()):
            self.device.exchange(0xB6, address, value)
        failures = {address: self.device.read("ram", address, 1)[0]
                    for address, value in pending.items()
                    if self.device.read("ram", address, 1) != bytes((value,))}
        if failures:
            self.state = "restore_failed"
            self._save_journal()
            raise RuntimeError(f"Could not restore XDATA bytes: {failures}")
        for address, value in pending.items():
            self.latest[address] = value
        self.state = ("restored" if all(self.latest.get(address) == value
                                        for address, value in self.original.items())
                      else "active")
        self._save_journal()

    def restore_all(self, *, verify_eeprom: bool = True) -> None:
        if not self.original:
            return
        if verify_eeprom:
            current_hash = stable_eeprom_hash(self.device)
            if current_hash != self.eeprom_sha256:
                self.state = "eeprom_changed_restore_refused"
                self._save_journal()
                raise RuntimeError("EEPROM changed since the session; RAM recovery was refused")
        self.restore_addresses(set(self.original))
        if verify_eeprom and stable_eeprom_hash(self.device) != self.eeprom_sha256:
            self.state = "eeprom_changed_after_restore"
            self._save_journal()
            raise RuntimeError("EEPROM hash changed during the RAM session")

    def _save_journal(self) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "format": 1,
            "chip": "MS2109",
            "region": "volatile XDATA only",
            "eeprom_sha256": self.eeprom_sha256,
            "state": self.state,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "original_bytes": {f"{address:04X}": f"{value:02X}"
                               for address, value in sorted(self.original.items())},
            "latest_bytes": {f"{address:04X}": f"{value:02X}"
                             for address, value in sorted(self.latest.items())},
            "recovery_command": f"python3 tools/ms2109_register_console.py --recover {self.journal_path}",
        }
        temp = self.journal_path.with_suffix(self.journal_path.suffix + ".tmp")
        temp.write_text(json.dumps(content, indent=2) + "\n")
        temp.replace(self.journal_path)


def session_path(directory: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"ms2109-xdata-{stamp}-{os.getpid()}.json"
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite session journal {path}")
    return path


def parse_value(text: str, width: int) -> int:
    value = int(text[2:], 10) if text.lower().startswith("d:") else int(text, 16)
    if not 0 <= value < (1 << (width * 8)):
        raise ValueError(f"Value is outside the {width * 8}-bit range")
    return value


def prompt(stdscr, label: str) -> str | None:
    height, width = stdscr.getmaxyx()
    y = max(0, height - 2)
    stdscr.move(y, 0)
    stdscr.clrtoeol()
    stdscr.addstr(y, 0, label[:max(1, width - 1)])
    stdscr.refresh()
    curses.echo()
    try:
        raw = stdscr.getstr(y, min(len(label), max(0, width - 2)), max(1, width - len(label) - 1))
    finally:
        curses.noecho()
    if raw in (b"\x1b", b""):
        return None
    return raw.decode("ascii", errors="ignore").strip()


def select_register(stdscr) -> RegisterPurpose | None:
    selected = 0
    while True:
        height, columns = stdscr.getmaxyx()
        detail_top = max(3, height - 7)
        list_top = 2
        visible_rows = max(1, detail_top - list_top)
        first = max(0, min(selected - visible_rows + 1,
                           len(REGISTER_PURPOSES) - visible_rows))
        confidence_top = max(detail_top + 2, height - 4)

        stdscr.erase()
        stdscr.addnstr(0, 0, "Mapped XDATA register selector", max(0, columns - 1))
        stdscr.addnstr(1, 0, "Up/Down or j/k: move   Enter: select   Esc/q: return",
                       max(0, columns - 1))
        for row in range(visible_rows):
            index = first + row
            if index >= len(REGISTER_PURPOSES):
                break
            item = REGISTER_PURPOSES[index]
            marker = ">" if index == selected else " "
            line = f"{marker} {item.address:04X}  {item.width}B  {item.name}"
            stdscr.addnstr(list_top + row, 0, line, max(0, columns - 1),
                           curses.A_REVERSE if index == selected else curses.A_NORMAL)

        item = REGISTER_PURPOSES[selected]
        if detail_top < height:
            stdscr.addnstr(detail_top, 0, "-" * max(0, columns - 1),
                           max(0, columns - 1))
        description_width = max(1, columns - 2)
        description_lines = textwrap.wrap(item.purpose, description_width) or [""]
        description_capacity = max(1, confidence_top - detail_top - 1)
        for offset, line in enumerate(description_lines[:description_capacity]):
            y = detail_top + 1 + offset
            if y < confidence_top:
                stdscr.addnstr(y, 0, line, max(0, columns - 1))

        evidence_lines = textwrap.wrap("Evidence: " + item.confidence,
                                       description_width) or [""]
        evidence_capacity = max(1, height - confidence_top - 2)
        for offset, line in enumerate(evidence_lines[:evidence_capacity]):
            y = confidence_top + offset
            if y < height - 2:
                stdscr.addnstr(y, 0, line, max(0, columns - 1))
        if height >= 3:
            stdscr.addnstr(height - 2, 0,
                           "Mapped use does not make writes safe; port side effects may survive byte restoration.",
                           max(0, columns - 1))
        if height >= 2:
            stdscr.addnstr(height - 1, 0, "Page Up/Down changes selection by one screen.",
                           max(0, columns - 1))
        stdscr.refresh()

        key = stdscr.getch()
        if key in (27, ord("q"), ord("Q")):
            return None
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(REGISTER_PURPOSES)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(REGISTER_PURPOSES)
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - visible_rows)
        elif key == curses.KEY_NPAGE:
            selected = min(len(REGISTER_PURPOSES) - 1, selected + visible_rows)
        elif key in (curses.KEY_ENTER, 10, 13):
            return item


def console(stdscr, session: RegisterSession) -> None:
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    address, width = 0xFE84, 1
    message = ("Read-only. Check purpose first: port side effects may survive byte restoration; "
               "q restores changed byte values.")
    while True:
        raw = session.read(address, width)
        value = int.from_bytes(raw, "little")
        purpose = purpose_for_address(address)
        height, columns = stdscr.getmaxyx()
        stdscr.erase()
        lines = [
            "MS2109 live XDATA register console  |  volatile writes; EEPROM is read-only",
            f"EEPROM SHA-256: {session.eeprom_sha256}",
            f"Address: 0x{address:04X}    Width: {width} byte(s)    Bytes: {raw.hex(' ').upper()}",
            f"Value: 0x{value:0{width * 2}X}    Decimal: {value}    Word order: little-endian",
            f"Purpose: {purpose.name if purpose else 'Not mapped in the curated register reference'}",
            f"Session journal: {session.journal_path}",
            "",
            "p  select mapped register/purpose   a  set address   w  switch byte/word",
            "b  flip bit and write live          e  edit hex / d:decimal and write",
            "u  restore selected byte values",
            "R  restore every changed byte value       q  restore values and quit",
            "Up/Down  move by selected width           PgUp/PgDn  move by 0x10",
            "",
            message,
        ]
        for row, line in enumerate(lines[:max(0, height - 1)]):
            stdscr.addnstr(row, 0, line, max(0, columns - 1))
        stdscr.refresh()
        key = stdscr.getch()
        try:
            if key in (ord("q"), ord("Q")):
                session.restore_all()
                return
            if key in (ord("w"), ord("W")):
                width = 2 if width == 1 else 1
                message = "Word reads/writes use little-endian byte order."
            elif key in (ord("p"), ord("P")):
                choice = select_register(stdscr)
                if choice is not None:
                    address, width = choice.address, choice.width
                    message = f"Selected {choice.name}; purpose and evidence are shown in the selector."
            elif key in (curses.KEY_UP, ord("+")):
                address = min(0x10000 - width, address + width)
            elif key in (curses.KEY_DOWN, ord("-")):
                address = max(0, address - width)
            elif key == curses.KEY_NPAGE:
                address = min(0x10000 - width, address + 0x10)
            elif key == curses.KEY_PPAGE:
                address = max(0, address - 0x10)
            elif key in (ord("a"), ord("A")):
                text = prompt(stdscr, "Address (hex, e.g. FE84): ")
                if text is not None:
                    candidate = int(text.removeprefix("0x").removeprefix("0X"), 16)
                    validate_access(candidate, width)
                    address = candidate
            elif key in (ord("b"), ord("B")):
                text = prompt(stdscr, f"Bit number (0–{width * 8 - 1}): ")
                if text is not None:
                    session.toggle_bit(address, width, int(text, 10))
                    message = f"Flipped bit {text}; readback verified. Side effects may remain."
            elif key in (ord("e"), ord("E")):
                text = prompt(stdscr, "Value (hex, or d:decimal): ")
                if text is not None:
                    new_value = parse_value(text, width)
                    session.write(address, new_value.to_bytes(width, "little"))
                    message = "Live write and readback verified. Side effects may remain."
            elif key in (ord("u"), ord("U")):
                session.restore_addresses(set(range(address, address + width)))
                message = "Selected byte values restored; peripheral side effects may remain."
            elif key == ord("R"):
                session.restore_all()
                message = "All changed byte values restored; EEPROM hash is unchanged."
        except (ValueError, RuntimeError) as exc:
            message = str(exc)


def recover(device: Device, path: Path) -> None:
    record = json.loads(path.read_text())
    if (record.get("format") != 1 or record.get("chip") != "MS2109"
            or record.get("region") not in ("XDATA RAM only", "volatile XDATA only")):
        raise ValueError("Unsupported recovery journal")
    current_hash = stable_eeprom_hash(device)
    if current_hash != record.get("eeprom_sha256"):
        raise RuntimeError("EEPROM does not match this journal; refusing stale RAM restoration")
    originals = {int(address, 16): int(value, 16)
                 for address, value in record.get("original_bytes", {}).items()}
    session = RegisterSession(device, current_hash, path)
    session.original = originals
    session.latest = {address: device.read("ram", address, 1)[0]
                      for address in originals}
    session.state = "recovering"
    session._save_journal()
    session.restore_all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    parser.add_argument("--recover", type=Path, help="restore a saved session journal and exit")
    args = parser.parse_args()
    device = Device()
    session = None
    try:
        print("Verifying MS2109 identity and two EEPROM reads…", flush=True)
        fingerprint = stable_eeprom_hash(device)
        if args.recover:
            recover(device, args.recover)
            print(f"Restored XDATA from {args.recover}; EEPROM fingerprint unchanged.")
            return
        path = session_path(args.session_dir)
        session = RegisterSession(device, fingerprint, path)
        print("Starting register console. Use q to restore and exit.", flush=True)
        curses.wrapper(console, session)
        if session.original:
            print(f"Restoration journal: {path}")
    finally:
        try:
            if session is not None and session.original and session.state != "restored":
                session.restore_all()
        finally:
            device.close()


if __name__ == "__main__":
    main()
