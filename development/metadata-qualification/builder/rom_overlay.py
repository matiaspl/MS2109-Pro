"""ROM routines and reviewed overlay bytes used by the release layout."""
from __future__ import annotations
import hashlib
from pathlib import Path
from control_assembler import Asm, BASE
from release_builder import ORIGINAL_SHA, ROM_SHA, validate

ROOT = Path(__file__).resolve().parents[1]
COPY_START, COPY_END = 0xCF5E, 0xD03A
SWITCH_START, SWITCH_END, ROM_SWITCH = 0xD212, 0xD238, 0x0910
WRAPPERS = ((0xD2A2, 0x603C, 0xD27F), (0xD2A6, 0x5884, 0xD28A),
            (0xD2AA, 0x48E6, 0xCCC8), (0xD2AE, 0x6069, 0xCC28))


def compact_copy():
    """Same 149 descriptor writes and 171 DE08/09 counter writes as factory."""
    a = Asm(COPY_START)
    a.emit(0x7E, 0, 0x7A, 0xC0, 0x7B, 0xBF)  # row, destination base
    a.label('row')
    a.emit(0xE4)
    a.dptr(0xDE08)
    a.emit(0xF0, 0xA3, 0xF0, 0xFC)  # preserve original scratch writes; index=0
    a.emit(0x7D, 25, 0xEE, 0xC3, 0x94, 5)
    a.rel((0x40,), 'byte')
    a.emit(0x7D, 4)
    a.label('byte')
    a.dptr(0xCE52)
    a.emit(0xEC, 0x93, 0xFF)  # R7 = table[index]
    a.emit(0xEB, 0x2C, 0xF5, 0x82, 0xEA, 0x34, 0, 0xF5, 0x83,
           0xEF, 0xF0, 0x0C)  # write destination base + index
    a.dptr(0xDE09)
    a.emit(0xEC, 0xF0, 0x6D)
    a.rel((0x70,), 'byte')
    a.emit(0x0E, 0xEB, 0x24, 46, 0xFB, 0xEA, 0x34, 0, 0xFA)
    a.rel((0xBE, 11), 'row')
    # Restore the factory routine's observable bank-zero result registers.
    # Its final multiply has cleared OV; final comparisons leave carry clear.
    a.emit(0xE4, 0xFA, 0xFC, 0xFE, 0xF5, 0xF0,
           0x7B, 3, 0x7D, 4, 0x7F, 11, 0xC3, 0xC2, 0xD2, 0x22)
    return a


def load_inputs():
    original = (ROOT/'firmware/base/original-eeprom.bin').read_bytes()
    rom = (ROOT/'firmware/base/ms2109-maskrom.bin').read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA or hashlib.sha256(rom).hexdigest() != ROM_SHA:
        raise ValueError('Unreviewed inputs')
    return original, rom, original[48:48+validate(original)]


def experiment_overlay():
    """Return a same-length offline experiment; free bytes are poisoned FF."""
    original, rom, factory = load_inputs()
    if factory[SWITCH_START-BASE:SWITCH_END-BASE] != rom[ROM_SWITCH:ROM_SWITCH+38]:
        raise AssertionError('Switch helper is no longer a byte-exact ROM duplicate')
    a = compact_copy()
    if a.pc > COPY_END:
        raise AssertionError('Replacement exceeds factory copy region')
    b = bytearray(factory)
    b[COPY_START-BASE:COPY_END-BASE] = a.finish() + b'\xff'*(COPY_END-a.pc)
    b[0xD03C-BASE:0xD03E-BASE] = ROM_SWITCH.to_bytes(2, 'big')
    # The only two reviewed callers of the multiply are inside replaced code.
    b[0xD201-BASE:SWITCH_END-BASE] = b'\xff'*(SWITCH_END-0xD201)
    for wrapper, target, caller in WRAPPERS:
        if b[wrapper-BASE:wrapper-BASE+4] != bytes((0x12,target>>8,target&255,0x22)):
            raise AssertionError('ROM trampoline changed')
        if b[caller-BASE] not in (0x02,0x12) or b[caller-BASE+1:caller-BASE+3] != wrapper.to_bytes(2,'big'):
            raise AssertionError('Trampoline caller changed')
        b[caller-BASE+1:caller-BASE+3] = target.to_bytes(2,'big')
        b[wrapper-BASE:wrapper-BASE+4] = b'\xff'*4
    return bytes(b)


