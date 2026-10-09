import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ms2109_register_console import RegisterSession, parse_value, recover


class FakeDevice:
    def __init__(self):
        self.ram = bytearray(65536)
        self.eeprom = bytes((index * 17) & 0xFF for index in range(2048))
        self.writes = []

    def identify_eeprom(self):
        return len(self.eeprom)

    def read(self, region, address, count):
        return self.eeprom[address:address + count] if region == "eeprom" else bytes(self.ram[address:address + count])

    def exchange(self, command, address, value):
        assert command == 0xB6
        if not Path(self.journal_path).is_file():
            raise AssertionError("Journal must be durable before the first write")
        self.ram[address] = value
        self.writes.append((address, value))


class RegisterConsoleTests(unittest.TestCase):
    def test_byte_word_edit_bit_toggle_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            device = FakeDevice()
            path = Path(temp) / "session.json"
            device.journal_path = path
            digest = hashlib.sha256(device.eeprom).hexdigest()
            device.ram[0xFE84:0xFE86] = b"\x40\x00"
            session = RegisterSession(device, digest, path)
            self.assertEqual(session.read_value(0xFE84, 2), 0x0040)
            session.toggle_bit(0xFE84, 2, 9)
            self.assertEqual(session.read(0xFE84, 2), b"\x40\x02")
            self.assertEqual(json.loads(path.read_text())["original_bytes"],
                             {"FE84": "40", "FE85": "00"})
            session.write(0xFE84, (0x1234).to_bytes(2, "little"))
            session.restore_all()
            self.assertEqual(session.read(0xFE84, 2), b"\x40\x00")
            self.assertEqual(json.loads(path.read_text())["state"], "restored")
            self.assertEqual(hashlib.sha256(device.eeprom).hexdigest(), digest)

    def test_recovery_journal_restores_interrupted_session(self):
        with tempfile.TemporaryDirectory() as temp:
            device = FakeDevice()
            path = Path(temp) / "session.json"
            device.journal_path = path
            digest = hashlib.sha256(device.eeprom).hexdigest()
            device.ram[0x1234] = 0xA5
            session = RegisterSession(device, digest, path)
            session.write(0x1234, b"\x5A")
            recover(device, path)
            self.assertEqual(device.ram[0x1234], 0xA5)
            self.assertEqual(json.loads(path.read_text())["state"], "restored")

    def test_refuses_restoration_after_eeprom_change(self):
        with tempfile.TemporaryDirectory() as temp:
            device = FakeDevice()
            path = Path(temp) / "session.json"
            device.journal_path = path
            session = RegisterSession(device, hashlib.sha256(device.eeprom).hexdigest(), path)
            session.write(0x1234, b"\x5A")
            device.eeprom = b"\x00" * len(device.eeprom)
            with self.assertRaisesRegex(RuntimeError, "EEPROM changed"):
                session.restore_all()

    def test_hex_decimal_values_and_range_validation(self):
        self.assertEqual(parse_value("7f", 1), 127)
        self.assertEqual(parse_value("d:127", 1), 127)
        with self.assertRaises(ValueError):
            parse_value("100", 1)


if __name__ == "__main__":
    unittest.main()
