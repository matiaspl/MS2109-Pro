from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from qualify_sharpness_ram import classify_runtime_overrides


class RuntimeOverrideGuardTests(unittest.TestCase):
    def setUp(self):
        self.saved = bytearray(1904)
        self.loaded = bytearray(self.saved)
        self.candidate = bytearray(2048)
        self.loaded[0x1A] = 0x7F
        self.saved[0x1A] = 0x40
        self.loaded[0x4D8:0x4DA] = b'\x00\x00'
        self.saved[0x4D8:0x4DA] = b'\x02\xD2'
        for address, value in ((0xCC1A, 0xFF), (0xD0D8, 0x02), (0xD0D9, 0xD2)):
            self.candidate[48 + address - 0xCC00] = value

    def test_accepts_only_reviewed_stable_runtime_overrides(self):
        report = classify_runtime_overrides(self.saved, self.loaded, self.candidate)
        self.assertEqual([item['address'] for item in report],
                         ['0xCC1A', '0xD0D8', '0xD0D9'])

    def test_rejects_any_additional_runtime_difference(self):
        self.loaded[0x20] = 1
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed loaded-overlay differences'):
            classify_runtime_overrides(self.saved, self.loaded, self.candidate)

    def test_rejects_changed_candidate_bytes_at_reviewed_locations(self):
        self.candidate[48 + 0xD0D8 - 0xCC00] = 0
        with self.assertRaisesRegex(RuntimeError, 'Candidate byte at D0D8'):
            classify_runtime_overrides(self.saved, self.loaded, self.candidate)


if __name__ == '__main__':
    unittest.main()
