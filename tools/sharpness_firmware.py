"""Offline MS2109 control-path prototype and strict 2 KiB packaging gate.

Generated CODE can be executed by the ROM harness even when it exceeds the
EEPROM budget. Such an overlay is an offline prototype, never an EEPROM image.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from build_patch import ORIGINAL_SHA, ROM_SHA, stores, validate
from audit_sharpness_candidate_space import encode_delta, decode_delta

BASE = 0xCC00
DESC_BUFFER = 0xD800
EDID_BUFFER = 0xDD00
MAX_CODE = 1996
VIDEO_HELPER = bytes.fromhex('90de05ebf0a3eaf0a3e9f012634522')


class Asm:
    def __init__(self, origin):
        self.origin = origin
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    @property
    def pc(self):
        return self.origin + len(self.code)

    def label(self, name):
        if name in self.labels:
            raise ValueError(f'duplicate label {name}')
        self.labels[name] = self.pc

    def emit(self, *data):
        self.code.extend(data)

    def raw(self, data):
        self.code.extend(data)

    def rel(self, opcode, target):
        self.raw(bytes(opcode))
        self.fixups.append((len(self.code), target, 'rel'))
        self.emit(0)

    def absolute(self, opcode, target):
        self.emit(opcode)
        self.fixups.append((len(self.code), target, 'abs'))
        self.emit(0, 0)

    def call(self, target):
        self.absolute(0x12, target)

    def jump(self, target):
        self.absolute(0x02, target)

    def dptr(self, target):
        self.absolute(0x90, target)

    def far_if(self, opcode, target):
        # condition -> LJMP; false -> skip the long jump
        self.raw(bytes(opcode))
        self.emit(2, 0x80, 3)
        self.jump(target)

    def finish(self, external=None):
        symbols = (external or {}) | self.labels
        result = bytearray(self.code)
        for offset, target, kind in self.fixups:
            dest = symbols[target] if isinstance(target, str) else target
            if kind == 'rel':
                displacement = dest - (self.origin + offset + 1)
                if not -128 <= displacement <= 127:
                    raise ValueError(f'branch {target} out of range: {displacement}')
                result[offset] = displacement & 255
            else:
                result[offset:offset+2] = dest.to_bytes(2, 'big')
        return bytes(result)


def push(a, registers):
    for reg in registers:
        a.emit(0xC0, reg)


def pop(a, registers):
    for reg in reversed(registers):
        a.emit(0xD0, reg)


def descriptor_code(a, *, compact=False):
    """Copy selected descriptors, cap MJPEG rate, and send bounded packets."""
    a.label('descriptor')
    # Only index zero/interface zero descriptor requests are intercepted.
    a.emit(0xE5, 0x0E, 0x45, 0x0F, 0x45, 0x10)
    a.far_if((0x70,), 'delegate')
    a.emit(0xE5, 0x0D)
    a.rel((0xB4, 2), 'other_speed')
    a.call(0x4B10)  # source = XDATA[C002:C003], tag 01
    a.rel((0x80,), 'descriptor_source')
    a.label('other_speed')
    a.call(0x4B37)  # source = CODE 75CC, tag FF
    a.label('descriptor_source')
    a.dptr(0)
    a.call(0x0492)
    a.far_if((0xB4, 9), 'delegate')
    a.dptr(1)
    a.call(0x0492)
    a.emit(0x65, 0x0D)  # descriptor type must match request
    a.far_if((0x70,), 'delegate')
    a.dptr(2)
    a.call(0x0492)
    a.emit(0xFD)  # R5 = total length low
    a.dptr(3)
    a.call(0x0492)
    a.emit(0xFC)  # R4 = total length high
    # Only the two reviewed layouts fit the allocated buffer.
    a.rel((0xB4, 4), 'descriptor_fs_length')
    a.emit(0xED)
    a.far_if((0xB4, 0xBB), 'delegate')
    a.rel((0x80,), 'descriptor_copy')
    a.label('descriptor_fs_length')
    a.far_if((0xB4, 1), 'delegate')
    a.emit(0xED)
    a.far_if((0xB4, 0x63), 'delegate')
    a.label('descriptor_copy')
    a.emit(0x7E, DESC_BUFFER >> 8, 0x7F, DESC_BUFFER & 255)
    a.call(0x5038)  # generic source -> XDATA destination, R4:R5 count
    # The active configuration copy advertises 1080p MJPEG at
    # 60 fps first. Keep the mode at a qualified 30 fps default and replace
    # the 60 fps discrete interval with a duplicate 30 fps interval. Its
    # existing 46-byte frame descriptor and interval count stay well-formed.
    # The ROM copy helper uses R5 for the descriptor length, so inspect the
    # copied header rather than the now-clobbered setup register.
    a.dptr(DESC_BUFFER + 1)
    a.emit(0xE0)
    a.far_if((0xB4, 2), 'descriptor_rates_done')
    a.dptr(DESC_BUFFER + 2)
    a.emit(0xE0)
    a.far_if((0xB4, 0xBB), 'descriptor_rates_done')
    a.emit(0xA3, 0xE0)
    a.far_if((0xB4, 0x04), 'descriptor_rates_done')
    for address in (DESC_BUFFER + 0x70 + 21, DESC_BUFFER + 0x70 + 26):
        a.dptr(address)
        for i, value in enumerate(bytes.fromhex('15 16 05 00')):
            if i:
                a.emit(0xA3)
            a.emit(0x74, value, 0xF0)
    a.label('descriptor_rates_done')
    # Save original setup length and ROM's cached length. The stock FIFO helper
    # uses both when computing offsets on subsequent packets.
    push(a, (0x11, 0x12))
    a.dptr(0xC000)
    a.emit(0xE0, 0xC0, 0xE0, 0xA3, 0xE0, 0xC0, 0xE0)
    a.dptr(DESC_BUFFER + 2)
    a.emit(0xE0, 0xFD, 0xA3, 0xE0, 0xFC)
    a.emit(0xC3, 0xE5, 0x12, 0x9D, 0xE5, 0x11, 0x9C)
    a.rel((0x40,), 'descriptor_bounded')  # host asks less than total
    a.emit(0x8C, 0x11, 0x8D, 0x12)
    a.label('descriptor_bounded')
    a.dptr(0xC000)
    a.emit(0xE5, 0x11, 0xF0, 0xA3, 0xE5, 0x12, 0xF0)
    a.emit(0xE5, 0x08, 0x45, 0x09)
    a.rel((0x70,), 'descriptor_remaining')
    a.emit(0x85, 0x11, 0x08, 0x85, 0x12, 0x09)
    if compact:
        a.label('descriptor_remaining')
        a.call(0x4B5A)  # carry iff remaining < 64
        a.emit(0x7B, 1, 0x7A, DESC_BUFFER >> 8, 0x79, 0, 0xD2, 0x86)
        a.rel((0x40,), 'descriptor_last_packet')
        a.label('descriptor_packet')
        a.call(0x0DC2)  # R7=64; FIFO write; remaining -= 64
        a.rel((0x80,), 'descriptor_restore')
        a.label('descriptor_last_packet')
        a.emit(0xAF, 0x09)
        a.call(0x0DD9)  # FIFO write R7 bytes; remaining = 0
        a.label('descriptor_restore')
    else:
        a.label('descriptor_remaining')
        a.emit(0x7F, 64, 0xE5, 0x08)
        a.rel((0x70,), 'descriptor_packet')
        a.emit(0xE5, 0x09, 0xC3, 0x94, 64)
        a.rel((0x50,), 'descriptor_packet')
        a.emit(0xAF, 0x09)
        a.label('descriptor_packet')
        a.emit(0xEF, 0xC0, 0xE0, 0x7B, 1, 0x7A, DESC_BUFFER >> 8,
               0x79, DESC_BUFFER & 255, 0xD2, 0x86)
        a.call(0x49C2)
        a.emit(0xD0, 0xE0, 0xFF, 0xC3, 0xE5, 0x09, 0x9F, 0xF5, 0x09,
               0xE5, 0x08, 0x94, 0, 0xF5, 0x08)
    a.dptr(0xC001)
    a.emit(0xD0, 0xE0, 0xF0)
    a.dptr(0xC000)
    a.emit(0xD0, 0xE0, 0xF0)
    pop(a, (0x11, 0x12))
    a.jump('complete')


def compact_stores(address, values):
    data = bytearray((0x90, address>>8, address&255))
    previous = None
    for i, value in enumerate(values):
        if i: data.append(0xA3)
        if value != previous:
            data.extend((0xE4,) if value == 0 else (0x74, value))
        data.append(0xF0)
        previous=value
    return bytes(data)


def common_code(a, *, compact=False):
    a.label('common')
    context = (0xE0, 0xD0, 0x82, 0x83) if compact else (0xE0, 0xD0, 0xF0, 0x82, 0x83)
    write = compact_stores if compact else stores
    push(a, context)
    a.rel((0xBF, 1), 'common_stage2')
    a.raw(write(0xC6A0, [0xEE, 0xFF, 149, 0, 0, 0, 148, 0]))
    a.raw(write(0xFE90, [0xEE, 149, 148, 0]))
    a.rel((0x80,), 'common_apply')
    a.label('common_stage2')
    a.rel((0xBF, 2), 'common_done')
    a.raw(write(0xC4C5, [2]) + write(0xC4C9, [0x80, 0xBB, 0]) + write(0xFE60, [1]))
    a.label('common_apply')
    a.call('matrix')
    a.label('common_done')
    pop(a, context)
    a.dptr(0xDE0B)
    a.emit(0x22)
    a.label('matrix')
    a.dptr(0xC2A4)
    a.call('matrix_record')
    a.dptr(0xC43B)
    a.jump('matrix_record')
    a.label('matrix_record')
    for i, value in enumerate(bytes.fromhex('06240d010104')):
        if i:
            a.emit(0xA3)
        a.emit(0xE0)
        a.rel((0xB4, value), 'matrix_done')
    a.emit(0x74, 1, 0xF0)
    a.label('matrix_done')
    a.emit(0x22)


def main_code(origin, *, include_common=True, assembler=Asm, bank_zero=False,
              include_descriptor=True):
    a = assembler(origin)
    context = (0xE0, 0xD0, 0xF0, 0x82, 0x83)
    if include_common:
        common_code(a)
    a.label('cc10')
    # Preserve A, PSW and the active-bank R0 while inspecting the caller stack.
    a.emit(0xC0, 0xE0, 0xC0, 0xD0, 0xE8, 0xC0, 0xE0, 0xA8, 0x81,
           0x18, 0x18, 0x18, 0x18, 0xE6)
    a.rel((0xB4, 0x92), 'video_entry')
    a.emit(0x08, 0xE6)
    a.rel((0xB4, 0x47), 'video_entry')
    a.emit(0xD0, 0xE0, 0xF8, 0xD0, 0xD0, 0xD0, 0xE0)
    a.rel((0x80,), 'usb')
    a.label('video_entry')
    a.emit(0xD0, 0xE0, 0xF8, 0xD0, 0xD0, 0xD0, 0xE0)
    a.jump('video')
    a.label('usb')
    push(a, context)
    # Save active-bank registers without assuming PSW.RS == 0.
    if bank_zero:
        push(a, range(8))
    else:
        for r in range(8):
            a.emit(0xE8 + r, 0xC0, 0xE0)
    a.emit(0xE5, 0x0B)
    a.rel((0xB4, 0x80), 'classify_control')
    a.emit(0xE5, 0x0C)
    a.far_if((0xB4, 6), 'delegate')
    a.emit(0xE5, 0x0D)
    a.far_if((0xB4, 2), 'maybe_other_speed')
    a.jump('descriptor')
    a.label('maybe_other_speed')
    a.far_if((0xB4, 7), 'delegate')
    a.jump('descriptor')
    a.label('classify_control')
    # GET_DEF for the four advertised procamp controls is answered from the
    # same calibrated values installed at startup. All other requests retain
    # the stock ROM path (including GET_CUR and SET_CUR).
    a.emit(0xE5, 0x0C)
    a.far_if((0xB4, 0x87), 'classify_legacy')
    a.emit(0xE5, 0x0D)
    a.far_if((0xB4, 8), 'get_def_procamp')
    a.jump('classify_legacy')  # selector 8 remains on the stock ROM path
    a.label('get_def_procamp')
    a.emit(0xE5, 0x0B)
    a.far_if((0xB4, 0xA1), 'delegate')
    a.emit(0xE5, 0x0E)
    a.far_if((0x70,), 'delegate')  # wValue low byte must be zero
    a.emit(0xE5, 0x0F)
    a.far_if((0xB4, 2), 'delegate')  # Processing Unit entity 2
    a.emit(0xE5, 0x10)
    a.far_if((0x70,), 'delegate')  # interface zero
    a.emit(0xE5, 0x11)
    a.far_if((0x70,), 'delegate')  # exactly two response bytes
    a.emit(0xE5, 0x12)
    a.far_if((0xB4, 2), 'delegate')
    a.emit(0xE5, 0x0D)
    a.dptr(0xC020)
    a.far_if((0xB4, 2), 'get_def_contrast')
    a.emit(0x74, 0xEE, 0xF0, 0xA3, 0x74, 0xFF, 0xF0)
    a.rel((0x80,), 'get_def_send')
    a.label('get_def_contrast')
    a.far_if((0xB4, 3), 'get_def_hue')
    a.emit(0x74, 149, 0xF0, 0xA3, 0xE4, 0xF0)
    a.rel((0x80,), 'get_def_send')
    a.label('get_def_hue')
    a.far_if((0xB4, 6), 'get_def_saturation')
    a.emit(0xE4, 0xF0, 0xA3, 0xF0)
    a.rel((0x80,), 'get_def_send')
    a.label('get_def_saturation')
    a.far_if((0xB4, 7), 'classify_legacy')
    a.emit(0x74, 148, 0xF0, 0xA3, 0xE4, 0xF0)
    a.label('get_def_send')
    # The CC10 hook bypasses the ROM class-request dispatcher. The ROM's
    # 49C2 FIFO sender treats IRAM 08:09 as a transfer offset, so start this
    # fresh two-byte control reply at offset zero instead of inheriting a
    # stale offset from the previous EP0 transaction.
    a.emit(0x75, 0x08, 0x00, 0x75, 0x09, 0x00)
    a.call(0x4B69)  # R3:R2:R1 = 01:C0:20 for the generic FIFO helper
    a.emit(0x7F, 2, 0xD2, 0x86)
    a.call(0x49C2)
    a.jump('complete')
    a.label('classify_legacy')
    a.emit(0xE5, 0x0B)  # restore bmRequestType after checking bRequest above
    a.emit(0x54, 0x60)
    a.far_if((0xB4, 0x20), 'delegate')
    a.emit(0xE5, 0x0D)
    a.far_if((0xB4, 8), 'delegate')
    a.emit(0xE5, 0x0F)
    a.far_if((0xB4, 2), 'delegate')
    a.emit(0xE5, 0x10)
    a.far_if((0x70,), 'delegate')
    # This profile does not replace UVC controls; leave matching requests to ROM.
    a.jump('delegate')
    a.label('complete')
    a.call(0x2B8E)
    a.rel((0x80,), 'usb_return')
    a.label('delegate')
    a.raw(restore_bytes(bank_zero=bank_zero))
    a.call(0x2AD0)
    a.emit(0x22)  # transparent tail-return preserving ROM result registers
    a.label('usb_return')
    a.raw(restore_bytes(bank_zero=bank_zero))
    a.emit(0x22)
    if include_descriptor:
        descriptor_code(a)
    return a


def restore_bytes(*, bank_zero=False):
    result = bytearray()
    for r in reversed(range(8)):
        result.extend((0xD0, r) if bank_zero else (0xD0, 0xE0, 0xF8 + r))
    for reg in reversed((0xE0, 0xD0, 0xF0, 0x82, 0x83)):
        result.extend((0xD0, reg))
    return bytes(result)


def edid_code(origin):
    a = Asm(origin)
    a.label('video')
    for reg, value in ((3, 0xFF), (2, 0xCD), (1, 0x52)):
        a.rel((0xB8 + reg, value), 'factory_video')
    a.emit(0x7B, 0xFF, 0x7A, 0x77, 0x79, 0x38,
           0x7C, 1, 0x7D, 0, 0x7E, EDID_BUFFER >> 8, 0x7F, 0)
    a.call(0x5038)
    a.dptr(0xCD52)
    a.emit(0xE4, 0x93, 0xFC, 0xA3)
    a.label('edid_run')
    a.emit(0xE4, 0x93, 0xF8, 0xA3, 0xE4, 0x93, 0xFD, 0xA3)
    a.label('edid_byte')
    a.emit(0xE4, 0x93, 0xC0, 0x82, 0xC0, 0x83,
           0x88, 0x82, 0x75, 0x83, EDID_BUFFER >> 8, 0xF0,
           0xD0, 0x83, 0xD0, 0x82, 0x08, 0xA3)
    a.rel((0xDD,), 'edid_byte')
    a.rel((0xDC,), 'edid_run')
    a.emit(0x7B, 1, 0x7A, EDID_BUFFER >> 8, 0x79, 0)
    a.label('factory_video')
    a.raw(VIDEO_HELPER)
    return a


@dataclass
class Prototype:
    overlay: bytes
    symbols: dict
    report: dict

    def eeprom(self, original):
        required = len(self.overlay)
        if required > MAX_CODE:
            raise ValueError(f'Control-repair profile needs {required} code bytes; '
                             f'2 KiB EEPROM permits {MAX_CODE}: deficit {required - MAX_CODE} bytes')
        out = bytearray(original)
        out[4] = 7
        out[2:4] = required.to_bytes(2, 'big')
        out[48:] = bytes([255]) * (len(out) - 48)
        out[48:48+required] = self.overlay
        out[48+required:50+required] = (sum(out[2:48]) & 65535).to_bytes(2, 'big')
        out[50+required:52+required] = (sum(self.overlay) & 65535).to_bytes(2, 'big')
        validate(out)
        return bytes(out)


def assemble(original, rom, *, edid_source="custom"):
    if edid_source not in ("custom", "rom"):
        raise ValueError("EDID source must be custom or rom")
    n = validate(original)
    if len(original) != 2048 or hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise ValueError('Unqualified EEPROM input')
    if hashlib.sha256(rom).hexdigest() != ROM_SHA:
        raise ValueError('Unqualified mask ROM')
    if original[48+0x10:48+0x1F] != VIDEO_HELPER:
        raise ValueError('Factory CC10 helper changed')
    if original[48+0x518:48+0x521] != bytes.fromhex('7bff7acd795202cc10'):
        raise ValueError('Factory EDID caller changed')
    body = bytearray(original[48:48+n+4])
    if edid_source == 'custom':
        custom = original[48+0x152:48+0x252]
        delta = encode_delta(rom[0x7738:0x7838], custom)
        if decode_delta(rom[0x7738:0x7838], delta) != custom:
            raise AssertionError('EDID roundtrip failed')
        edid = edid_code(0xCD52 + len(delta))
        main = main_code(BASE+n+4)
        symbols = edid.labels | main.labels
        table = delta + edid.finish(symbols)
        decoder_bytes = len(edid.code)
    else:
        # Keep the stock EDID upload sequence, selecting its CODE-space table.
        # Relocate complete generated routines into the vacated custom table.
        shared = Asm(0xCD52)
        common_code(shared)
        video = Asm(shared.pc)
        video.label('video')
        video.label('factory_video')
        video.raw(VIDEO_HELPER)
        main = main_code(BASE+n+4, include_common=False)
        symbols = shared.labels | video.labels | main.labels
        table = shared.finish(symbols) + video.finish(symbols)
        body[0x51B], body[0x51D] = 0x77, 0x38
        delta = b''
        decoder_bytes = 0
    table_used = len(table)
    if table_used > 256:
        raise ValueError('Reclaimed EDID table overflow')
    body[0x152:0x252] = table + bytes([255]) * (256-table_used)
    body.extend(main.finish(symbols))
    body[0:3] = bytes((0x12, symbols['common'] >> 8, symbols['common'] & 255))
    body[0x10:0x13] = bytes((0x02, symbols['cc10'] >> 8, symbols['cc10'] & 255))
    if BASE+len(body) > DESC_BUFFER:
        raise ValueError('Offline prototype overlaps descriptor buffer')
    report = {
        'status': 'offline prototype; not hardware-qualified',
        'startup_procamp': {'brightness_signed': -18, 'contrast': 149,
                            'hue': 0, 'saturation': 148},
        'get_def': {'status': 'CC10 hook returns the startup procamp defaults',
                    'brightness_signed': -18, 'contrast': 149,
                    'hue': 0, 'saturation': 148},
        'eeprom_limit_bytes': 2048, 'code_limit_bytes': MAX_CODE,
        'required_code_bytes': len(body), 'deficit_bytes': max(0, len(body)-MAX_CODE),
        'required_image_bytes': len(body)+52,
        'main_routines_bytes': len(main.code), 'edid_delta_bytes': len(delta),
        'edid_source': edid_source,
        'edid_decoder_bytes': decoder_bytes,
        'edid_table_unused_bytes': 256-table_used,
        'overlay_sha256': hashlib.sha256(body).hexdigest(),
        'rom_sha256': ROM_SHA, 'original_sha256': ORIGINAL_SHA,
        'rollback': 'artifacts/ms2109-calibrated-stereo-channel-order.bin',
        'memory': {
            'overlay': [hex(BASE), hex(BASE+len(body)-1)],
            'descriptor_buffer': [hex(DESC_BUFFER), hex(DESC_BUFFER+1211-1)],
            'edid_buffer': [hex(EDID_BUFFER), hex(EDID_BUFFER+255)] if edid_source == 'custom' else None,
            'ep0_staging_rom_owned': ['0xc020', '0xc021'],
        },
        'symbols': {key: hex(value) for key, value in symbols.items()},
        'limitations': ['No real USB FIFO timing or physical-device qualification',
                        'Descriptor and EDID scratch allocation is a static proposal, not a hardware lease',
                        'An oversized raw overlay must never be passed to an EEPROM programmer'],
    }
    return Prototype(bytes(body), symbols, report)
