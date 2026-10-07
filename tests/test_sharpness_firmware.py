"""Execute emitted firmware and the pinned ROM EP0 services, not API stubs."""
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from mcs51_rom_harness import CPU
from sharpness_firmware import assemble, DESC_BUFFER, EDID_BUFFER
from build_patch import build, validate, COLOR_RECORDS

ORIGINAL = (ROOT / 'backups/ms2109-original.bin').read_bytes()
ROM = (ROOT / 'backups/ms2109-maskrom.bin').read_bytes()
PROTOTYPE = assemble(ORIGINAL, ROM)


def cpu():
    return CPU(ROM, PROTOTYPE.overlay)


def request(c, code, payload=None, **fields):
    setup = {'bm': 0x21 if code == 1 else 0xA1, 'request': code,
             'value': 0x0800, 'index': 0x0200,
             'length': 1 if code == 0x86 else 2} | fields
    c.iram[0x0B:0x13] = bytes((setup['bm'], setup['request'])) + \
        setup['value'].to_bytes(2, 'big') + setup['index'].to_bytes(2, 'big') + \
        setup['length'].to_bytes(2, 'big')
    c.iram[8:10] = b'\0\0'
    c.xdata[0xC000:0xC002] = setup['length'].to_bytes(2, 'big')
    c.output.clear()
    c.put(0x80, 1 if payload is not None else 0)
    if payload is not None:
        c.input.extend(payload.to_bytes(2, 'little'))
    c.run(0xCC10, return_to=0x4792)
    return bytes(c.output)


class SharpnessFirmwareTests(unittest.TestCase):
    def test_all_128_values_queries_and_rom_fifo_contract(self):
        c = cpu()
        for selected in range(128):
            request(c, 1, selected)
            self.assertEqual(c.xdata[PROTOTYPE.symbols['selected']], selected)
            self.assertEqual(c.xdata[0xFE84:0xFE86], bytes((selected, 0)))
            self.assertFalse(c.input)
            self.assertEqual(request(c, 0x81), bytes((selected, 0)))
            for code, expected in ((0x82, b'\0\0'), (0x83, b'\x7f\0'),
                                   (0x84, b'\1\0'), (0x85, b'\2\0'),
                                   (0x86, b'\3'), (0x87, b'\x40\0')):
                self.assertEqual(request(c, code), expected)
            self.assertEqual(c.direct(0x81), 0x50)
        self.assertTrue({0x62CA, 0x49C2, 0x2B8E}.issubset(c.visits))

    def test_invalid_control_requests_stall_without_state_change(self):
        for fields in ({'length': 0}, {'length': 1}, {'length': 3},
                       {'length': 258}, {'value': 0x0801}, {'bm': 0xA1}):
            c = cpu()
            request(c, 1, 37, **fields)
            self.assertEqual(c.xdata[PROTOTYPE.symbols['selected']], 64)
            self.assertTrue(c.bit(0x85), fields)
            self.assertFalse(any(addr in (0xFE84, 0xFE85) for addr, _ in c.writes))
        for value in (128, 255, 256, 0x7FFF, 0x8000, 0xFFFF):
            c = cpu()
            request(c, 1, value)
            self.assertEqual(c.xdata[PROTOTYPE.symbols['selected']], 64)
            self.assertTrue(c.bit(0x85))
        for code in (0, 2, 0x80, 0x88, 0xFF):
            c = cpu()
            request(c, code)
            self.assertTrue(c.bit(0x85))

    def test_query_directions_and_lengths(self):
        for code in range(0x81, 0x88):
            for fields in ({'bm': 0x21}, {'bm': 0xA0}, {'length': 0},
                           {'length': 3}, {'length': 0x102}):
                c = cpu()
                self.assertEqual(request(c, code, **fields), b'')
                self.assertTrue(c.bit(0x85))

    def test_register_preservation_at_rom_bank_zero_abi(self):
        for flags in (0, 0x84, 0xC6):
            c = cpu()
            c.put(0xD0, flags)
            c.a = 0xD9
            c.put(0xF0, 0xA7)
            c.dptr = 0xBCDE
            for r in range(8):
                c.setreg(r, 0x91+r)
            request(c, 0x81)
            self.assertEqual([c.reg(r) for r in range(8)], list(range(0x91, 0x99)))
            self.assertEqual(c.a, 0xD9)
            self.assertEqual(c.direct(0xF0), 0xA7)
            self.assertEqual(c.dptr, 0xBCDE)
            self.assertEqual(c.direct(0xD0), flags)

    def test_poll_repairs_only_differences_and_retains_selection(self):
        c = cpu()
        request(c, 1, 29)
        for mode in range(3):
            c.xdata[0xFE84:0xFE86] = b'\x7a\x02'
            c.setreg(7, 2)
            c.run(PROTOTYPE.symbols['common'])
            self.assertEqual(c.xdata[0xFE84:0xFE86], b'\x1d\0')
            c.writes.clear()
            c.run(PROTOTYPE.symbols['repair'])
            self.assertEqual(c.writes, [])
        c.setreg(7, 1)
        c.run(PROTOTYPE.symbols['common'])
        self.assertEqual(c.xdata[PROTOTYPE.symbols['selected']], 64)
        self.assertEqual(c.xdata[0xFE84:0xFE86], b'\x40\0')

    def test_edid_factory_call_reconstructs_and_uploads_exact_bytes(self):
        c = cpu()
        c.xdata[EDID_BUFFER:EDID_BUFFER+256] = bytes([0xA5])*256
        c.run(0xD118)  # Execute the actual factory pointer setup, then CC10.
        if PROTOTYPE.report['edid_source'] == 'custom':
            expected = ORIGINAL[48+0x152:48+0x252]
            self.assertEqual(c.xdata[EDID_BUFFER:EDID_BUFFER+256], expected)
        else:
            expected = ROM[0x7738:0x7838]
            self.assertEqual(c.xdata[EDID_BUFFER:EDID_BUFFER+256], bytes([0xA5])*256)

        self.assertEqual(c.xdata[0xFB00:0xFC00], expected)
        self.assertIn(0x6345, c.visits)
        self.assertNotIn(0x2AD0, c.visits)
        self.assertEqual(c.direct(0x81), 0x50)

    def test_descriptor_packets_preserve_selected_configuration(self):
        cases = ((2, 0xC03A, ROM[0x7111:0x75CC]),
                 (2, 0xC800, bytes((9, 2)) + ROM[0x75CE:0x772F]),
                 (7, 0xC03A, ROM[0x75CC:0x772F]))
        for kind, pointer, source in cases:
            for length in (0, 9, 63, 64, 65, 128, len(source), len(source)+64, 65535):
                with self.subTest(kind=kind, pointer=pointer, length=length):
                    c = cpu()
                    c.xdata[0xC002:0xC004] = pointer.to_bytes(2, 'big')
                    if kind == 2:
                        c.xdata[pointer:pointer+len(source)] = source
                        c.xdata[pointer+101] ^= 0x20  # Preserve a non-PU field.
                        source_bytes = bytes(c.xdata[pointer:pointer+len(source)])
                    else:
                        source_bytes = source
                    expected = bytearray(source_bytes)
                    expected[0x41] |= 0x10
                    c.xdata[DESC_BUFFER-1] = 0xA5
                    c.xdata[DESC_BUFFER+1211] = 0x5A
                    received = bytearray(request(c, 6, bm=0x80, value=kind << 8,
                                                 index=0, length=length))
                    for _ in range(32):
                        if not any(c.iram[8:10]): break
                        c.output.clear()
                        c.put(0x80, 0)
                        c.run(0xCC10, return_to=0x4792)
                        received.extend(c.output)
                    else:
                        self.fail('descriptor transfer did not terminate')
                    self.assertEqual(received, expected[:length])
                    self.assertEqual(c.xdata[0xC002:0xC004], pointer.to_bytes(2, 'big'))
                    self.assertEqual(c.xdata[0xC000:0xC002], length.to_bytes(2, 'big'))
                    self.assertEqual(c.iram[0x11:0x13], length.to_bytes(2, 'big'))
                    self.assertEqual(c.xdata[DESC_BUFFER-1], 0xA5)
                    self.assertEqual(c.xdata[DESC_BUFFER+1211], 0x5A)
                    self.assertEqual(c.direct(0x81), 0x50)
                    if kind == 2:
                        self.assertEqual(c.xdata[pointer:pointer+len(source)], source_bytes)

    def test_descriptor_guards_delegate_without_changing_source(self):
        for offset in (0, 1, 2, 3, *range(0x39, 0x41)):
            c = cpu()
            c.xdata[0xC03A:0xC03A+1211] = ROM[0x7111:0x75CC]
            c.xdata[0xC002:0xC004] = b'\xc0\x3a'
            c.xdata[0xC03A+offset] ^= 0x80
            before = bytes(c.xdata[0xC03A:0xC03A+1211])
            calls = []
            c.traps[0x2AD0] = lambda machine: (calls.append(machine.pc), machine.ret())
            request(c, 6, bm=0x80, value=0x0200, index=0, length=1211)
            self.assertEqual(calls, [0x2AD0])
            self.assertEqual(c.xdata[0xC03A:0xC03A+1211], before)

    def test_legacy_procamp_uses_unchanged_rom_dispatch(self):
        for selector, value in ((2, 0xFFEE), (3, 149), (6, 0), (7, 147)):
            for code in (1, 0x81, 0x82, 0x83, 0x84, 0x86, 0x87):
                actual, stock = cpu(), cpu()
                # Route stock directly through ROM, maintaining the same return ABI.
                stock.traps[0xCC10] = lambda machine: setattr(machine, 'pc', 0x2AD0)
                args = {'value': selector << 8}
                payload = value if code == 1 else None
                self.assertEqual(request(actual, code, payload, **args),
                                 request(stock, code, payload, **args))
                self.assertEqual(actual.xdata[0xC6A0:0xC6A8], stock.xdata[0xC6A0:0xC6A8])
                self.assertEqual(actual.direct(0x80), stock.direct(0x80))
                for reg in (*range(8), 0xE0, 0xD0, 0x82, 0x83, 0xF0):
                    self.assertEqual(actual.direct(reg), stock.direct(reg), (selector, code, reg))
                self.assertIn(0x2AD0, actual.visits)

    def test_retained_calibration_audio_and_factory_code(self):
        baseline, _, entry = build(ORIGINAL, channel_order=True,
                                  calibrated_color=True, rom=ROM)
        self.assertEqual(baseline, (ROOT / PROTOTYPE.report['rollback']).read_bytes())
        for stage in range(32):
            for damaged in (None, *(address+i for address in COLOR_RECORDS for i in range(6))):
                actual = cpu()
                stock = CPU(ROM, baseline[48:48+validate(baseline)])
                for machine in (actual, stock):
                    if damaged is not None:
                        machine.xdata[damaged] ^= 0x80
                    machine.setreg(7, stage)
                actual.run(PROTOTYPE.symbols['common'])
                stock.run(entry)
                retained = [(address, value) for address, value in actual.writes
                            if address not in (0xFE84, 0xFE85, PROTOTYPE.symbols['selected'])]
                self.assertEqual(retained, stock.writes, (stage, damaged))
                self.assertEqual(actual.dptr, stock.dptr)
        old = ORIGINAL[48:48+validate(ORIGINAL)]
        changed = {i for i, byte in enumerate(old) if byte != PROTOTYPE.overlay[i]}
        self.assertFalse(changed - self.allowed_factory_changes(),
                         'Factory code changed outside audited patch regions')

    def allowed_factory_changes(self):
        allowed = set(range(3)) | set(range(0x10, 0x13)) | set(range(0x152, 0x252))
        if PROTOTYPE.report['edid_source'] == 'rom':
            allowed |= {0x51B, 0x51D}
        return allowed

    def test_unrelated_requests_delegate_with_original_context(self):
        # Routing ABI test only: trap isolates delegation from device side effects.
        cases = ({'value': 0x0800, 'index': 0x0201},
                 {'value': 0x0800, 'index': 0x0100},
                 {'bm': 0xA1, 'value': 0x0100, 'index': 0x0102},  # audio
                 {'bm': 0xA1, 'value': 0x0100, 'index': 0x0001},  # streaming
                 {'bm': 0xA1, 'value': 0x0300, 'index': 0x0004},  # HID
                 {'bm': 0x80, 'request': 6, 'value': 0x0100, 'index': 0})
        for fields in cases:
            c = cpu()
            c.a, c.dptr = 0xA5, 0xB123
            for r in range(8): c.setreg(r, 0x40+r)
            called = []
            def stock(machine):
                called.append(True)
                self.assertEqual(machine.a, 0xA5)
                self.assertEqual(machine.dptr, 0xB123)
                self.assertEqual([machine.reg(r) for r in range(8)], list(range(0x40, 0x48)))
                machine.ret()
            c.traps[0x2AD0] = stock
            request(c, 0x81, **fields)
            self.assertEqual(called, [True])
            self.assertEqual(c.xdata[PROTOTYPE.symbols['selected']], 64)

    def test_oversize_profile_never_emits_eeprom(self):
        self.assertGreater(PROTOTYPE.report['deficit_bytes'], 0)
        with self.assertRaisesRegex(ValueError, 'deficit'):
            PROTOTYPE.eeprom(ORIGINAL)
        with self.assertRaisesRegex(ValueError, f"deficit {PROTOTYPE.report['deficit_bytes']}"):
            build(ORIGINAL, rom=ROM, sharpness_profile=True,
                  sharpness_edid=PROTOTYPE.report['edid_source'])


if __name__ == '__main__':
    unittest.main()
